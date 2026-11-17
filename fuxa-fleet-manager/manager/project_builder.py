#!/usr/bin/env python3
"""
FUXA Project Builder & Importer
- Pre-provisions SQLite database (project.fuxap.db) for new view servers.
- Imports FUXA project.json / .fuxap exports directly into Storage or View servers.
- Provides pre-import backup and schema validation.
"""

import sqlite3
import json
import os
import shutil
import datetime

FUXA_TABLES = [
    "general", "views", "devices", "devicesSecurity", "texts",
    "alarms", "recipes", "notifications", "scripts", "reports",
    "locations", "arMarkers"
]

def generate_fuxa_database(target_dir: str, plant_id: int, division_name: str, line_name: str, opcua_endpoint: str = "opc.tcp://127.0.0.1:4840"):
    """Pre-provisions a fresh View Server database with OPC-UA Storage bridge."""
    appdata_dir = os.path.join(target_dir, "_appdata")
    os.makedirs(appdata_dir, exist_ok=True)

    db_path = os.path.join(appdata_dir, "project.fuxap.db")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create FUXA core tables
    cur.execute("CREATE TABLE IF NOT EXISTS general (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS views (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS devices (name TEXT PRIMARY KEY, value TEXT, connection TEXT, cntid TEXT, cntpwd TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS devicesSecurity (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS texts (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS alarms (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS recipes (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS notifications (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS scripts (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS reports (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS locations (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS arMarkers (name TEXT PRIMARY KEY, value TEXT);")

    # 1. General settings
    general_data = {
        "version": "1.02",
        "title": f"Plant {plant_id} - {division_name} ({line_name})",
        "header": {
            "title": f"Plant {plant_id} | {division_name}",
            "alarms": True,
            "login": True
        }
    }
    cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES (?, ?);", ("version", "1.02"))
    cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES (?, ?);", ("general", json.dumps(general_data)))

    # 2. Pre-configure OPC-UA Storage Device
    device_id = f"dev_opcua_plant_{plant_id}"
    device_obj = {
        "id": device_id,
        "name": f"Plant_{plant_id}_Storage_OPCUA",
        "type": "OPCUA",
        "enabled": True,
        "property": {
            "address": opcua_endpoint,
            "options": {
                "securityMode": "None",
                "securityPolicy": "None"
            }
        },
        "tags": {}  # Populated via native OPC-UA "Browse Tags" in the UI
    }
    cur.execute(
        "INSERT OR REPLACE INTO devices (name, value, connection, cntid, cntpwd) VALUES (?, ?, ?, ?, ?);",
        (device_id, json.dumps(device_obj), "opc-ua", "", "")
    )

    # 3. Create Default HMI View
    view_id = "view_overview"
    view_obj = {
        "id": view_id,
        "name": f"{line_name.replace(' ', '_')}_Overview",
        "profile": {
            "width": 1920,
            "height": 1080,
            "bkcolor": "#1e222d",
            "margin": 10
        },
        "items": {}
    }
    cur.execute("INSERT OR REPLACE INTO views (name, value) VALUES (?, ?);", (view_id, json.dumps(view_obj)))

    conn.commit()
    conn.close()

    # Also keep a copy at target_dir/project.fuxap.db for direct fallback
    root_db = os.path.join(target_dir, "project.fuxap.db")
    shutil.copy2(db_path, root_db)

    return db_path


def inspect_project_data(project_data: dict) -> dict:
    """Inspects raw project JSON or dictionary and returns a human-readable structure summary."""
    if not isinstance(project_data, dict):
        return {"valid": False, "error": "Invalid project file format: root must be a JSON object."}

    # Extract title
    title = project_data.get("name")
    if not title:
        gen = project_data.get("general", {})
        if isinstance(gen, dict):
            title = gen.get("title")
    title = title or "FUXA Project"

    version = str(project_data.get("version", "1.00"))

    # Extract devices
    devs = project_data.get("devices", {})
    if isinstance(devs, dict):
        dev_list = list(devs.values())
    elif isinstance(devs, list):
        dev_list = devs
    else:
        dev_list = []

    dev_names = []
    total_tags = 0
    for d in dev_list:
        if isinstance(d, dict):
            name = d.get("name") or d.get("id") or "Unnamed Device"
            dev_names.append(name)
            tags = d.get("tags", {})
            if isinstance(tags, (dict, list)):
                total_tags += len(tags)

    # Check top-level server device
    has_server = "server" in project_data and isinstance(project_data["server"], dict)
    if has_server:
        s_name = project_data["server"].get("name", "FUXA Server")
        if s_name not in dev_names:
            dev_names.append(s_name)

    # Extract views
    views = []
    hmi = project_data.get("hmi", {})
    if isinstance(hmi, dict) and "views" in hmi:
        views = hmi["views"]
    elif "views" in project_data:
        views = project_data["views"]

    if isinstance(views, dict):
        view_list = list(views.values())
    elif isinstance(views, list):
        view_list = views
    else:
        view_list = []

    view_names = [v.get("name") or v.get("id") or "Unnamed Screen" for v in view_list if isinstance(v, dict)]

    alarms = project_data.get("alarms", [])
    alarms_cnt = len(alarms) if isinstance(alarms, (list, dict)) else 0

    scripts = project_data.get("scripts", [])
    scripts_cnt = len(scripts) if isinstance(scripts, (list, dict)) else 0

    texts = project_data.get("texts", [])
    texts_cnt = len(texts) if isinstance(texts, (list, dict)) else 0

    recipes = project_data.get("recipes", [])
    recipes_cnt = len(recipes) if isinstance(recipes, (list, dict)) else 0

    return {
        "valid": True,
        "title": title,
        "version": version,
        "devices_count": len(dev_names),
        "device_names": dev_names,
        "tags_count": total_tags,
        "views_count": len(view_names),
        "view_names": view_names,
        "alarms_count": alarms_cnt,
        "scripts_count": scripts_cnt,
        "texts_count": texts_cnt,
        "recipes_count": recipes_cnt,
        "has_server": has_server
    }


def import_project_to_database(
    target_work_dir: str,
    project_data: dict,
    role: str = "storage",
    plant_id: int = 9,
    preserve_bridge: bool = True,
    opcua_endpoint: str = "opc.tcp://127.0.0.1:4840",
    backup_dir: str = None
) -> dict:
    """
    Imports a full FUXA project into the target server's SQLite database.

    Args:
        target_work_dir: Base directory for the instance (e.g. locations/storage/plant_9)
        project_data: Parsed dictionary from project.json / .fuxap
        role: "storage" or "view"
        plant_id: Associated plant number (default 9)
        preserve_bridge: For view servers, maintain the zero-driver OPC-UA bridge device
        opcua_endpoint: Target OPC-UA server address for the bridge
        backup_dir: Directory where pre-import backup is stored
    """
    appdata_dir = os.path.join(target_work_dir, "_appdata")
    os.makedirs(appdata_dir, exist_ok=True)

    db_path = os.path.join(appdata_dir, "project.fuxap.db")
    mirror_db_path = os.path.join(target_work_dir, "project.fuxap.db")

    # 1. Automated Pre-Import Backup
    if backup_dir is None:
        backup_dir = os.path.abspath(os.path.join(target_work_dir, "..", "..", "backups"))
    os.makedirs(backup_dir, exist_ok=True)

    existing_source = None
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        existing_source = db_path
    elif os.path.exists(mirror_db_path) and os.path.getsize(mirror_db_path) > 0:
        existing_source = mirror_db_path

    backup_file = None
    if existing_source:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_tag = f"plant_{plant_id}" if role == "storage" else os.path.basename(target_work_dir)
        backup_file = os.path.join(backup_dir, f"project_{role}_{target_tag}_backup_{ts}.fuxap.db")
        shutil.copy2(existing_source, backup_file)

    # 2. Initialize Database & Tables
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    for t in FUXA_TABLES:
        if t == "devices":
            cur.execute("CREATE TABLE IF NOT EXISTS devices (name TEXT PRIMARY KEY, value TEXT, connection TEXT, cntid TEXT, cntpwd TEXT);")
        else:
            cur.execute(f"CREATE TABLE IF NOT EXISTS {t} (name TEXT PRIMARY KEY, value TEXT);")

    # Clear prior configuration cleanly
    for t in FUXA_TABLES:
        cur.execute(f"DELETE FROM {t};")

    # 3. Import Views
    hmi = project_data.get("hmi", {})
    views = []
    if isinstance(hmi, dict) and "views" in hmi:
        views = hmi["views"]
    elif "views" in project_data:
        views = project_data["views"]

    if isinstance(views, dict):
        view_list = list(views.values())
    elif isinstance(views, list):
        view_list = views
    else:
        view_list = []

    imported_views = []
    for v in view_list:
        if not isinstance(v, dict):
            continue
        v_id = v.get("id") or f"view_{len(imported_views)}"
        v_name = v.get("name", v_id)
        cur.execute("INSERT OR REPLACE INTO views (name, value) VALUES (?, ?);", (v_id, json.dumps(v)))
        imported_views.append(v_name)

    # 4. Import General Settings & HMI Layout
    if isinstance(hmi, dict):
        for hk, hv in hmi.items():
            if hk != "views":
                cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES (?, ?);", (hk, json.dumps(hv)))

    reserved_top_keys = {
        "devices", "hmi", "server", "texts", "alarms", "recipes",
        "notifications", "scripts", "reports", "mapsLocations", "ar", "views"
    }
    for k, v in project_data.items():
        if k not in reserved_top_keys:
            cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES (?, ?);", (k, json.dumps(v)))

    # 5. Import Texts
    texts = project_data.get("texts", [])
    if isinstance(texts, dict):
        texts = list(texts.values())
    if isinstance(texts, list):
        for item in texts:
            if isinstance(item, dict):
                t_name = item.get("name") or item.get("id")
                if t_name:
                    cur.execute("INSERT OR REPLACE INTO texts (name, value) VALUES (?, ?);", (t_name, json.dumps(item)))

    # 6. Import Alarms
    alarms = project_data.get("alarms", [])
    if isinstance(alarms, dict):
        alarms = list(alarms.values())
    if isinstance(alarms, list):
        for item in alarms:
            if isinstance(item, dict):
                a_name = item.get("name") or item.get("id")
                if a_name:
                    cur.execute("INSERT OR REPLACE INTO alarms (name, value) VALUES (?, ?);", (a_name, json.dumps(item)))

    # 7. Import Recipes
    recipes = project_data.get("recipes", [])
    if isinstance(recipes, dict):
        recipes = list(recipes.values())
    if isinstance(recipes, list):
        for item in recipes:
            if isinstance(item, dict):
                r_id = item.get("id") or item.get("name")
                if r_id:
                    cur.execute("INSERT OR REPLACE INTO recipes (name, value) VALUES (?, ?);", (r_id, json.dumps(item)))

    # 8. Import Notifications
    notifs = project_data.get("notifications", [])
    if isinstance(notifs, dict):
        notifs = list(notifs.values())
    if isinstance(notifs, list):
        for item in notifs:
            if isinstance(item, dict):
                n_id = item.get("id") or item.get("name")
                if n_id:
                    cur.execute("INSERT OR REPLACE INTO notifications (name, value) VALUES (?, ?);", (n_id, json.dumps(item)))

    # 9. Import Scripts
    scripts = project_data.get("scripts", [])
    if isinstance(scripts, dict):
        scripts = list(scripts.values())
    if isinstance(scripts, list):
        for item in scripts:
            if isinstance(item, dict):
                s_id = item.get("id") or item.get("name")
                if s_id:
                    cur.execute("INSERT OR REPLACE INTO scripts (name, value) VALUES (?, ?);", (s_id, json.dumps(item)))

    # 10. Import Reports
    reports = project_data.get("reports", [])
    if isinstance(reports, dict):
        reports = list(reports.values())
    if isinstance(reports, list):
        for item in reports:
            if isinstance(item, dict):
                rp_id = item.get("id") or item.get("name")
                if rp_id:
                    cur.execute("INSERT OR REPLACE INTO reports (name, value) VALUES (?, ?);", (rp_id, json.dumps(item)))

    # 11. Import Maps Locations
    locs = project_data.get("mapsLocations", [])
    if isinstance(locs, dict):
        locs = list(locs.values())
    if isinstance(locs, list):
        for item in locs:
            if isinstance(item, dict):
                l_id = item.get("id") or item.get("name")
                if l_id:
                    cur.execute("INSERT OR REPLACE INTO locations (name, value) VALUES (?, ?);", (l_id, json.dumps(item)))

    # 12. Import AR Markers
    ar = project_data.get("ar", {})
    if isinstance(ar, dict) and ar:
        markers = ar.get("markers", [])
        ar_copy = {k: v for k, v in ar.items() if k != "markers"}
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('ar', ?);", (json.dumps(ar_copy),))
        if isinstance(markers, list):
            for m in markers:
                if isinstance(m, dict):
                    m_id = m.get("id") or m.get("name")
                    if m_id:
                        cur.execute("INSERT OR REPLACE INTO arMarkers (name, value) VALUES (?, ?);", (m_id, json.dumps(m)))

    # 13. Import Devices based on Role
    imported_devices = []
    total_tags = 0

    if role == "storage" or not preserve_bridge:
        devs = project_data.get("devices", {})
        if isinstance(devs, list):
            dev_list = devs
        elif isinstance(devs, dict):
            dev_list = list(devs.values())
        else:
            dev_list = []

        for dev in dev_list:
            if not isinstance(dev, dict):
                continue
            d_id = dev.get("id")
            if not d_id:
                continue
            d_name = dev.get("name", d_id)
            d_tags = dev.get("tags", {})
            if isinstance(d_tags, (dict, list)):
                total_tags += len(d_tags)
            cur.execute("INSERT OR REPLACE INTO devices (name, value) VALUES (?, ?);", (d_id, json.dumps(dev)))
            imported_devices.append(d_name)

        # Top-level server device
        if "server" in project_data and isinstance(project_data["server"], dict):
            srv = project_data["server"]
            s_name = srv.get("name", "FUXA Server")
            cur.execute("INSERT OR REPLACE INTO devices (name, value) VALUES ('server', ?);", (json.dumps(srv),))
            if s_name not in imported_devices:
                imported_devices.append(s_name)
    else:
        # View Server Bridge Mode: Connect to central storage server via OPC-UA
        bridge_id = f"dev_opcua_plant_{plant_id}"
        bridge_name = f"Plant_{plant_id}_Storage_OPCUA"
        bridge_dev = {
            "id": bridge_id,
            "name": bridge_name,
            "type": "OPCUA",
            "enabled": True,
            "property": {
                "address": opcua_endpoint,
                "options": {
                    "securityMode": "None",
                    "securityPolicy": "None"
                }
            },
            "tags": {}
        }
        cur.execute(
            "INSERT OR REPLACE INTO devices (name, value, connection, cntid, cntpwd) VALUES (?, ?, ?, ?, ?);",
            (bridge_id, json.dumps(bridge_dev), "opc-ua", "", "")
        )
        imported_devices.append(bridge_name)

    conn.commit()
    conn.close()

    # Mirror copy for root directory fallback
    try:
        shutil.copy2(db_path, mirror_db_path)
    except Exception:
        pass

    return {
        "success": True,
        "db_path": db_path,
        "backup_path": backup_file,
        "views_count": len(imported_views),
        "view_names": imported_views,
        "devices_count": len(imported_devices),
        "device_names": imported_devices,
        "tags_count": total_tags
    }
