#!/usr/bin/env python3
"""
FUXA Enterprise Fleet Manager - Autonomous SCADA Orchestrator
Hosts and controls Storage and View servers autonomously via PM2.
Generates Nginx routes and pre-provisions zero-driver OPC-UA project databases.
"""

import os
import sys
import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pm2_adapter import PM2Adapter
from port_engine import PortEngine
from project_builder import generate_fuxa_database

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from nginx.fuxa_route_generator import generate_nginx_conf, reload_nginx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FleetManager")

app = FastAPI(title="FUXA Enterprise Fleet Manager")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCATIONS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "locations"))
VIEWS_DIR = os.path.join(LOCATIONS_DIR, "views")
STORAGE_DIR = os.path.join(LOCATIONS_DIR, "storage")
FUXA_SERVER_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "server", "main.js"))
NGINX_CONF_DIR = os.path.join(BASE_DIR, "nginx", "conf.d")

os.makedirs(VIEWS_DIR, exist_ok=True)
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(NGINX_CONF_DIR, exist_ok=True)

pm2_adapter = PM2Adapter()
port_engine = PortEngine(pm2_adapter=pm2_adapter)

class CreateViewRequest(BaseModel):
    plant: int
    division: int
    line: int
    project_name: str
    custom_port: int = None

class StorageActionRequest(BaseModel):
    plant_id: int

@app.on_event("startup")
def on_startup():
    logger.info("FUXA Fleet Manager initialized. Scanning PM2 and local instances...")
    port_engine.auto_sync_instances(VIEWS_DIR)

@app.get("/api/matrix")
def get_matrix():
    """Returns visual port map, active plants, and live PM2 resource status"""
    port_engine.auto_sync_instances(VIEWS_DIR)
    return {
        "matrix": port_engine.get_port_matrix(),
        "plants": port_engine.registry.get("plants", {}),
        "divisions": port_engine.registry.get("divisions", {}),
        "pm2_available": pm2_adapter.is_available()
    }

@app.post("/api/create-view")
def create_view_server(req: CreateViewRequest):
    """
    Autonomously provisions a new View Server:
    1. Allocates deterministic port.
    2. Builds clean SQLite project database with OPC-UA bridge to Storage Server.
    3. Starts View Server in PM2 with -p port and -u workDir.
    4. Generates Nginx configuration and reloads Nginx.
    5. Saves instance to registry.
    """
    # 1. Allocate port
    port = req.custom_port if req.custom_port else port_engine.calculate_port(req.plant, req.division, req.line)
    instance_id = f"fuxa_p{req.plant}_d{req.division}_l{req.line}_{port}"

    logger.info(f"Provisioning new View Server: {instance_id} on Port {port}")

    # 2. Setup isolated userDir inside locations/views/<location_folder> & pre-provision project.fuxap.db
    folder_name = f"p{req.plant}_div{req.division}_l{req.line}_port{port}"
    instance_work_dir = os.path.join(VIEWS_DIR, folder_name)
    os.makedirs(instance_work_dir, exist_ok=True)

    div_name = port_engine.registry.get("divisions", {}).get(str(req.division), f"Division_{req.division}")
    line_name = f"Line {req.line}"

    # Target OPC-UA storage endpoint (central bridge or storage server)
    storage_info = port_engine.registry.get("plants", {}).get(str(req.plant), {})
    storage_port = storage_info.get("storage_port", 5801)
    opcua_endpoint = f"opc.tcp://127.0.0.1:4840"

    generate_fuxa_database(
        target_dir=instance_work_dir,
        plant_id=req.plant,
        division_name=div_name,
        line_name=line_name,
        opcua_endpoint=opcua_endpoint
    )

    # 3. Generate Nginx reverse-proxy configuration & attempt reload
    conf_path, subpath = generate_nginx_conf(
        plant=req.plant,
        division=req.division,
        line=req.line,
        port=port,
        project_name=req.project_name,
        output_dir=NGINX_CONF_DIR
    )
    nginx_reloaded, nginx_msg = reload_nginx()

    # 4. Start instance autonomously in PM2 (role="view" disables plugin installation)
    pm2_res = pm2_adapter.start_instance(
        name=instance_id,
        script_path=FUXA_SERVER_PATH,
        port=port,
        user_dir=instance_work_dir,
        subpath=subpath,
        role="view"
    )

    # 5. Persist in registry
    instance_meta = {
        "id": instance_id,
        "name": req.project_name,
        "plant": req.plant,
        "division": req.division,
        "line": req.line,
        "port": port,
        "subpath": subpath,
        "work_dir": instance_work_dir,
        "pm2_name": instance_id,
        "pm2_managed": True,
        "status": "RUNNING" if pm2_res.get("success") else "STOPPED",
        "nginx_conf": conf_path,
        "nginx_reloaded": nginx_reloaded,
        "editor_url": f"http://127.0.0.1:{port}/editor",
        "home_url": f"http://127.0.0.1:{port}/home"
    }
    port_engine.register_instance(instance_id, instance_meta)

    return {
        "success": True,
        "instance": instance_meta,
        "pm2_status": pm2_res,
        "nginx_status": {"reloaded": nginx_reloaded, "message": nginx_msg},
        "message": f"View Server successfully created and hosted on Port {port} via PM2!"
    }

@app.post("/api/instances/{instance_id}/start")
def start_view_server(instance_id: str):
    instances = port_engine.get_all_instances()
    if instance_id not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    inst = instances[instance_id]
    pm2_name = inst.get("pm2_name") or instance_id

    # If already known to PM2, restart
    pm2_status = pm2_adapter.get_process_status(pm2_name)
    if pm2_status.get("exists"):
        res = pm2_adapter.restart_instance(pm2_name)
    else:
        # Register fresh into PM2 as View Server
        res = pm2_adapter.start_instance(
            name=pm2_name,
            script_path=FUXA_SERVER_PATH,
            port=inst["port"],
            user_dir=inst["work_dir"],
            subpath=inst.get("subpath", ""),
            role="view"
        )

    inst["status"] = "RUNNING" if res.get("success") else "STOPPED"
    port_engine.register_instance(instance_id, inst)
    return {"success": res.get("success"), "status": inst["status"]}

@app.post("/api/instances/{instance_id}/stop")
def stop_view_server(instance_id: str):
    instances = port_engine.get_all_instances()
    if instance_id not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    inst = instances[instance_id]
    pm2_name = inst.get("pm2_name") or instance_id
    res = pm2_adapter.stop_instance(pm2_name)

    inst["status"] = "STOPPED"
    port_engine.register_instance(instance_id, inst)
    return {"success": res.get("success"), "status": "STOPPED"}

@app.delete("/api/instances/{instance_id}")
def delete_view_server(instance_id: str):
    instances = port_engine.get_all_instances()
    if instance_id in instances:
        inst = instances[instance_id]
        pm2_name = inst.get("pm2_name") or instance_id
        pm2_adapter.delete_instance(pm2_name)
        port_engine.unregister_instance(instance_id)

    return {"success": True, "message": f"Instance {instance_id} removed from PM2 and registry."}

@app.post("/api/storage/{plant_id}/start")
def start_storage_server(plant_id: int):
    """Starts or restarts the plant's Storage Server via PM2"""
    plants = port_engine.registry.get("plants", {})
    p_info = plants.get(str(plant_id))
    if not p_info:
        raise HTTPException(status_code=404, detail="Plant not found")

    pm2_name = p_info.get("storage_pm2_name", f"P{plant_id}_Storage_Server")
    port = p_info["storage_port"]

    pm2_status = pm2_adapter.get_process_status(pm2_name)
    if pm2_status.get("exists"):
        res = pm2_adapter.restart_instance(pm2_name)
    else:
        # Prepare dedicated storage workDir inside locations/storage/plant_<id>
        storage_work_dir = os.path.join(STORAGE_DIR, f"plant_{plant_id}")
        os.makedirs(storage_work_dir, exist_ok=True)
        res = pm2_adapter.start_instance(
            name=pm2_name,
            script_path=FUXA_SERVER_PATH,
            port=port,
            user_dir=storage_work_dir,
            role="storage"
        )

    return {"success": res.get("success"), "pm2_name": pm2_name, "port": port}

@app.post("/api/storage/{plant_id}/stop")
def stop_storage_server(plant_id: int):
    plants = port_engine.registry.get("plants", {})
    p_info = plants.get(str(plant_id))
    if not p_info:
        raise HTTPException(status_code=404, detail="Plant not found")

    pm2_name = p_info.get("storage_pm2_name", f"P{plant_id}_Storage_Server")
    res = pm2_adapter.stop_instance(pm2_name)
    return {"success": res.get("success"), "pm2_name": pm2_name}

@app.post("/api/sync")
def sync_unregistered():
    """Manual sync trigger to detect new PM2 or folder-based view servers"""
    port_engine.auto_sync_instances(VIEWS_DIR)
    return {"success": True, "matrix": port_engine.get_port_matrix()}

@app.get("/api/logs/{target}")
def get_logs(target: str, lines: int = 100):
    """
    Returns recent stdout and stderr logs for a PM2 process by port or name.
    Example: /api/logs/5801 or /api/logs/P9_FUXA_Enterprise
    """
    return pm2_adapter.get_process_logs(target, lines=lines)

# Static files for the Manager UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MANAGER_PORT", "9000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
