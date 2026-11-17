#!/usr/bin/env python3
"""
FUXA Enterprise Fleet Manager - Autonomous SCADA Orchestrator
Hosts and controls Storage and View servers autonomously via PM2.
Generates Nginx routes and pre-provisions zero-driver OPC-UA project databases.
"""

import os
import sys
import json
import shutil
import datetime
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pm2_adapter import PM2Adapter
from port_engine import PortEngine
from project_builder import generate_fuxa_database, import_project_to_database, inspect_project_data

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

class ReconfigurePortRequest(BaseModel):
    new_port: int

class StorageActionRequest(BaseModel):
    plant_id: int

class ImportProjectRequest(BaseModel):
    project_data: dict = None
    preserve_bridge: bool = True
    auto_restart: bool = True
    opcua_endpoint: str = "opc.tcp://127.0.0.1:4840"

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
    # 1. Allocate or validate port
    if req.custom_port:
        available, msg = port_engine.check_port_available(req.custom_port)
        if not available:
            raise HTTPException(status_code=400, detail=msg)
        port = req.custom_port
    else:
        port = port_engine.calculate_port(req.plant, req.division, req.line)

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

@app.get("/api/ports/check")
def check_port(port: int, current_id: str = None):
    """Pre-checks if a port is free or occupied before launching or reconfiguring."""
    available, msg = port_engine.check_port_available(port, current_id=current_id)
    return {"port": port, "available": available, "message": msg}

@app.post("/api/storage/{plant_id}/reconfigure")
def reconfigure_storage_port(plant_id: int, req: ReconfigurePortRequest):
    """
    Versatile Port Reconfiguration for Plant Storage Server:
    1. Pre-checks port availability.
    2. Backs up current project database.
    3. Restarts PM2 process with new port.
    4. Updates registry & master fuxa-fleet-registry.json.
    """
    new_port = req.new_port
    plants = port_engine.registry.get("plants", {})
    p_info = plants.get(str(plant_id))
    if not p_info:
        raise HTTPException(status_code=404, detail="Plant not found")

    old_port = p_info.get("storage_port")
    if old_port == new_port:
        return {"success": True, "message": f"Port is already {new_port}", "port": new_port}

    available, msg = port_engine.check_port_available(new_port, current_id=f"storage_{plant_id}")
    if not available:
        raise HTTPException(status_code=400, detail=msg)

    pm2_name = p_info.get("storage_pm2_name", f"P{plant_id}_Storage_Server")
    storage_work_dir = os.path.join(STORAGE_DIR, f"plant_{plant_id}")
    os.makedirs(storage_work_dir, exist_ok=True)

    # 1. Back up database before modifying port
    db_file = os.path.join(storage_work_dir, "_appdata", "_app.db")
    if os.path.exists(db_file) and os.path.getsize(db_file) > 0:
        backups_dir = os.path.join(LOCATIONS_DIR, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dest = os.path.join(backups_dir, f"plant_{plant_id}_storage_p{old_port}_to_p{new_port}_{ts}.db")
        shutil.copy2(db_file, backup_dest)
        logger.info(f"Database backed up before port switch: {backup_dest}")

    # 2. Update PM2 if currently registered/running
    pm2_status = pm2_adapter.get_process_status(pm2_name)
    was_running = pm2_status.get("exists") and pm2_status.get("status") == "online"
    if pm2_status.get("exists"):
        pm2_adapter.delete_instance(pm2_name)

    if was_running:
        pm2_res = pm2_adapter.start_instance(
            name=pm2_name,
            script_path=FUXA_SERVER_PATH,
            port=new_port,
            user_dir=storage_work_dir,
            role="storage"
        )
        status_text = "ONLINE" if pm2_res.get("success") else "STOPPED"
    else:
        status_text = "STOPPED"

    # 3. Update Registry
    p_info["storage_port"] = new_port
    port_engine._save_registry()

    return {
        "success": True,
        "plant_id": plant_id,
        "old_port": old_port,
        "new_port": new_port,
        "pm2_name": pm2_name,
        "status": status_text,
        "message": f"Plant {plant_id} Storage Server port updated to {new_port} successfully."
    }

@app.post("/api/instances/{instance_id}/reconfigure")
def reconfigure_instance_port(instance_id: str, req: ReconfigurePortRequest):
    """
    Versatile Port Reconfiguration for HMI View Server:
    1. Pre-checks port availability.
    2. Backs up current project database.
    3. Re-provisions PM2 with new port.
    4. Regenerates Nginx reverse-proxy configuration.
    5. Updates registry & master fuxa-fleet-registry.json.
    """
    new_port = req.new_port
    instances = port_engine.get_all_instances()
    if instance_id not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    inst = instances[instance_id]
    old_port = inst.get("port")
    if old_port == new_port:
        return {"success": True, "message": f"Port is already {new_port}", "port": new_port}

    available, msg = port_engine.check_port_available(new_port, current_id=instance_id)
    if not available:
        raise HTTPException(status_code=400, detail=msg)

    work_dir = inst.get("work_dir")
    pm2_name = inst.get("pm2_name", instance_id)

    # 1. Back up database before modifying port
    if work_dir:
        db_file = os.path.join(work_dir, "_appdata", "_app.db")
        if os.path.exists(db_file) and os.path.getsize(db_file) > 0:
            backups_dir = os.path.join(LOCATIONS_DIR, "backups")
            os.makedirs(backups_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dest = os.path.join(backups_dir, f"view_{instance_id}_p{old_port}_to_p{new_port}_{ts}.db")
            shutil.copy2(db_file, backup_dest)
            logger.info(f"Database backed up before port switch: {backup_dest}")

    # 2. Update PM2 if currently registered/running
    pm2_status = pm2_adapter.get_process_status(pm2_name)
    was_running = pm2_status.get("exists") and pm2_status.get("status") == "online"
    if pm2_status.get("exists"):
        pm2_adapter.delete_instance(pm2_name)

    if was_running:
        pm2_res = pm2_adapter.start_instance(
            name=pm2_name,
            script_path=FUXA_SERVER_PATH,
            port=new_port,
            user_dir=work_dir,
            subpath=inst.get("subpath", ""),
            role="view"
        )
        inst["status"] = "RUNNING" if pm2_res.get("success") else "STOPPED"
    else:
        inst["status"] = "STOPPED"

    # 3. Update Nginx configuration with new port
    try:
        generate_nginx_conf(
            plant=inst.get("plant", 9),
            division=inst.get("division", 6),
            line=inst.get("line", 1),
            port=new_port,
            project_name=inst.get("name", instance_id),
            output_dir=NGINX_CONF_DIR
        )
        reload_nginx()
    except Exception as e:
        logger.warning(f"Failed to update Nginx for {instance_id}: {e}")

    # 4. Update Registry
    inst["port"] = new_port
    port_engine.register_instance(instance_id, inst)

    return {
        "success": True,
        "instance_id": instance_id,
        "old_port": old_port,
        "new_port": new_port,
        "status": inst["status"],
        "message": f"View Server {instance_id} port updated to {new_port} successfully."
    }

@app.get("/api/logs/{target}")
def get_logs(target: str, lines: int = 100):
    """
    Returns recent stdout and stderr logs for a PM2 process by port or name.
    Example: /api/logs/5810 or /api/logs/P9_Storage_Server
    """
    return pm2_adapter.get_process_logs(target, lines=lines)

@app.post("/api/project/inspect")
@app.post("/api/project/inspect/")
async def api_inspect_project(request: Request):
    """Parses and inspects a project.json or .fuxap payload and returns a structural summary."""
    try:
        body = await request.json()
        if isinstance(body, dict) and "project_data" in body and isinstance(body["project_data"], dict):
            pdata = body["project_data"]
        else:
            pdata = body
        return inspect_project_data(pdata)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse project JSON: {str(e)}")

@app.post("/api/storage/{plant_id}/import-project")
@app.post("/api/storage/{plant_id}/import-project/")
async def api_import_storage_project(plant_id: str, request: Request):
    """
    Imports a full project.json / .fuxap into the specified Plant Storage Server.
    1. Validates project payload and plant.
    2. Creates automatic timestamped backup in locations/backups/.
    3. Replaces tables with imported project (all devices, tags, views, alarms, etc.).
    4. Automatically reloads PM2 storage server if active.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")

    if isinstance(body, dict) and "project_data" in body and isinstance(body["project_data"], dict):
        pdata = body["project_data"]
        auto_restart = body.get("auto_restart", True)
    else:
        pdata = body
        auto_restart = True

    p_clean = str(plant_id).replace("plant_", "")
    plant_num = int(p_clean) if p_clean.isdigit() else 9

    storage_work_dir = os.path.join(STORAGE_DIR, f"plant_{plant_num}")
    os.makedirs(storage_work_dir, exist_ok=True)

    result = import_project_to_database(
        target_work_dir=storage_work_dir,
        project_data=pdata,
        role="storage",
        plant_id=plant_num
    )

    pm2_res = {"restarted": False, "status": "unchanged"}
    plants = port_engine.registry.get("plants", {})
    p_info = plants.get(str(plant_num), {})
    pm2_name = p_info.get("storage_pm2_name", f"P{plant_num}_Storage_Server")

    if auto_restart:
        pm2_status = pm2_adapter.get_process_status(pm2_name)
        if pm2_status.get("exists") and pm2_status.get("status") == "online":
            res = pm2_adapter.restart_instance(pm2_name)
            pm2_res = {"restarted": res.get("success", False), "status": "online"}
        elif not pm2_status.get("exists") and p_info.get("storage_port"):
            res = pm2_adapter.start_instance(
                name=pm2_name,
                script_path=FUXA_SERVER_PATH,
                port=p_info["storage_port"],
                user_dir=storage_work_dir,
                role="storage"
            )
            pm2_res = {"restarted": res.get("success", False), "status": "started"}

    return {
        "success": True,
        "plant_id": plant_num,
        "details": result,
        "pm2": pm2_res,
        "message": f"Successfully imported project into Plant {plant_num} Storage Server ({result.get('devices_count', 0)} devices, {result.get('views_count', 0)} views)."
    }

@app.post("/api/instances/{instance_id}/import-project")
@app.post("/api/instances/{instance_id}/import-project/")
async def api_import_view_project(instance_id: str, request: Request):
    """
    Imports HMI views and screens from project.json / .fuxap into the specified View Server.
    1. Validates project payload and target view server.
    2. Creates automatic timestamped backup in locations/backups/.
    3. Imports views, layouts, and general settings.
    4. Preserves OPC-UA Bridge to Central Storage Server by default (zero direct PLC drivers).
    5. Automatically reloads PM2 view server if active.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")

    if isinstance(body, dict) and "project_data" in body and isinstance(body["project_data"], dict):
        pdata = body["project_data"]
        preserve_bridge = body.get("preserve_bridge", True)
        auto_restart = body.get("auto_restart", True)
        opcua_endpoint = body.get("opcua_endpoint", "opc.tcp://127.0.0.1:4840")
    else:
        pdata = body
        preserve_bridge = True
        auto_restart = True
        opcua_endpoint = "opc.tcp://127.0.0.1:4840"

    instances = port_engine.get_all_instances()
    inst = instances.get(instance_id)

    # Allow lookup by port (e.g. 9610 or "9610")
    if not inst:
        for i_id, i_data in instances.items():
            if str(i_data.get("port")) == str(instance_id):
                instance_id = i_id
                inst = i_data
                break

    if not inst:
        # Resolve port and instance directory
        port = None
        if instance_id.isdigit():
            port = int(instance_id)
            instance_id = f"fuxa_port_{port}"
        elif "port_" in instance_id:
            try:
                port = int(instance_id.split("port_")[1])
            except Exception:
                port = None

        work_dir = os.path.join(VIEWS_DIR, instance_id)
        p_str = str(port) if port else ""
        plant_id = int(p_str[0]) if len(p_str) >= 4 else 9
        pm2_name = instance_id

        if port:
            div = int(p_str[1]) if len(p_str) >= 4 else 6
            line = int(p_str[2]) if len(p_str) >= 4 else 1
            port_engine.register_instance(instance_id, {
                "id": instance_id,
                "name": f"Imported View Server (Port {port})",
                "plant": plant_id,
                "division": div,
                "line": line,
                "port": port,
                "subpath": f"/p{plant_id}/div{div}/l{line}",
                "work_dir": work_dir,
                "status": "STOPPED",
                "pm2_managed": True
            })
    else:
        work_dir = inst.get("work_dir") or os.path.join(VIEWS_DIR, instance_id)
        plant_id = inst.get("plant", 9)
        pm2_name = inst.get("pm2_name", instance_id)

    os.makedirs(work_dir, exist_ok=True)

    result = import_project_to_database(
        target_work_dir=work_dir,
        project_data=pdata,
        role="view",
        plant_id=plant_id,
        preserve_bridge=preserve_bridge,
        opcua_endpoint=opcua_endpoint
    )

    pm2_res = {"restarted": False, "status": "unchanged"}
    if auto_restart:
        pm2_status = pm2_adapter.get_process_status(pm2_name)
        if pm2_status.get("exists") and pm2_status.get("status") == "online":
            res = pm2_adapter.restart_instance(pm2_name)
            pm2_res = {"restarted": res.get("success", False), "status": "online"}
        elif inst and inst.get("port"):
            res = pm2_adapter.start_instance(
                name=pm2_name,
                script_path=FUXA_SERVER_PATH,
                port=inst["port"],
                user_dir=work_dir,
                subpath=inst.get("subpath", ""),
                role="view"
            )
            pm2_res = {"restarted": res.get("success", False), "status": "started"}

    return {
        "success": True,
        "instance_id": instance_id,
        "details": result,
        "pm2": pm2_res,
        "message": f"Successfully imported project into View Server {instance_id} ({result.get('views_count', 0)} views)."
    }

@app.post("/api/import-project")
@app.post("/api/import-project/")
async def api_import_unified_project(request: Request):
    """
    Unified Import Endpoint:
    Accepts target_type ('storage' or 'view') and delegates accordingly.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")

    target_type = body.get("target_type", "storage")
    target_id = str(body.get("target_id", "9"))

    if target_type == "view":
        return await api_import_view_project(target_id, request)
    else:
        return await api_import_storage_project(target_id, request)

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
