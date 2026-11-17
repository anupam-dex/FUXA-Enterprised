#!/usr/bin/env python3
"""
FUXA Project Builder & Importer
- Pre-provisions SQLite database (project.fuxap.db) for new view servers.
- Imports FUXA project.json / .fuxap exports directly into Storage or View servers.
- Role-Specific Rules:
  * Storage Server: Imports ONLY unique devices & tags. Strictly skips all views/screens and removes duplicates.
  * View Server: Imports HMI screens, SVGs & layout. Preserves zero-driver OPC-UA Storage bridge.
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

    # 1. Create Default HMI View
    view_id = "view_overview"
    view_obj = {
        "id": view_id,
        "name": f"{line_name.replace(' ', '_')}_Overview",
        "profile": {
            "width": 1920,
            "height": 1080,
            "bkcolor": "#12171f",
            "margin": 10
        },
        "items": {},
        "variables": [],
        "svgcontent": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">'
            '<rect width="1920" height="1080" fill="#12171f"/>'
            '<rect x="260" y="240" width="1400" height="600" rx="16" fill="#1e222d" stroke="#30363d" stroke-width="2"/>'
            f'<text x="960" y="380" fill="#58a6ff" font-size="40" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle" font-weight="bold">Plant {plant_id} - {division_name}</text>'
            f'<text x="960" y="440" fill="#7ee787" font-size="24" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle" font-weight="600">Line: {line_name}</text>'
            '<text x="960" y="520" fill="#c9d1d9" font-size="20" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle">Central OPC-UA Bridge Connected (opc.tcp://127.0.0.1:4840)</text>'
            '<text x="960" y="580" fill="#8b949e" font-size="16" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle">Ready for HMI screen design and tag binding in the Editor</text>'
            '</svg>'
        )
    }
    cur.execute("INSERT OR REPLACE INTO views (name, value) VALUES (?, ?);", (view_id, json.dumps(view_obj)))

    # 2. General settings and complete HMI Layout
    layout_data = {
        "start": view_id,
        "navigation": {
            "mode": "fix",
            "type": "inline",
            "bkcolor": "#161b22",
            "fgcolor": "#c9d1d9",
            "items": [
                {
                    "icon": "home",
                    "view": view_id,
                    "link": "",
                    "text": f"{division_name} Overview"
                }
            ]
        },
        "header": {
            "title": f"Plant {plant_id} | {division_name}",
            "alarms": True,
            "login": True,
            "items": []
        },
        "showdev": True,
        "zoom": "autoresize",
        "inputdialog": "false",
        "hidenavigation": False,
        "theme": "",
        "loginonstart": False
    }
    cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('layout', ?);", (json.dumps(layout_data),))
    cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('version', '1.02');")
    cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('name', ?);", (json.dumps(f"Plant {plant_id} - {division_name}"),))

    # 3. Pre-configure OPC-UA Storage Device
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

    conn.commit()
    conn.close()

    # Also keep a copy at target_dir/project.fuxap.db for direct fallback
    root_db = os.path.join(target_dir, "project.fuxap.db")
    try:
        shutil.copy2(db_path, root_db)
    except Exception:
        pass

    return db_path


def dedup_device_candidates(dev_list):
    """
    Strictly deduplicates device definitions:
    1. Normalizes device names (strip whitespace, case-insensitive comparison).
    2. Groups copies by normalized name.
    3. For duplicate names, sorts by tags count descending and retains ONLY the copy with the most tags.
    4. Ensures device IDs are completely unique.
    Returns (final_devices, skipped_duplicates).
    """
    candidates = []
    for dev in dev_list:
        if not isinstance(dev, dict):
            continue
        d_id = dev.get("id")
        if not d_id:
            continue
        d_name = dev.get("name", d_id).strip()
        tags = dev.get("tags", {})
        tags_count = len(tags) if isinstance(tags, (dict, list)) else 0
        candidates.append({
            "id": d_id,
            "name": d_name,
            "tags_count": tags_count,
            "data": dev
        })

    # Group by normalized name
    by_norm_name = {}
    for c in candidates:
        norm = c["name"].strip().lower()
        by_norm_name.setdefault(norm, []).append(c)

    deduped = []
    skipped = []

    for norm, group in by_norm_name.items():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            # Sort by tags_count descending: keep the copy with the most configured tags
            group.sort(key=lambda x: x["tags_count"], reverse=True)
            keeper = group[0]
            deduped.append(keeper)
            for dup in group[1:]:
                skipped.append(f"{dup['name']} (ID: {dup['id']}, tags: {dup['tags_count']})")

    # Also deduplicate by ID in case different names had the same ID
    seen_ids = set()
    final_devices = []
    for d in deduped:
        if d["id"] not in seen_ids:
            seen_ids.add(d["id"])
            final_devices.append(d)
        else:
            skipped.append(f"{d['name']} (Duplicate ID: {d['id']})")

    return final_devices, skipped


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

    # Check top-level server device
    if "server" in project_data and isinstance(project_data["server"], dict):
        srv = project_data["server"]
        has_srv = any(d.get("id") in ("0", "server") or d.get("type") == "FuxaServer" for d in dev_list if isinstance(d, dict))
        if not has_srv:
            if not srv.get("id"):
                srv["id"] = "0"
            dev_list.insert(0, srv)

    deduped_devs, skipped_devs = dedup_device_candidates(dev_list)

    dev_names = [d["name"] for d in deduped_devs]
    total_tags = sum(d["tags_count"] for d in deduped_devs)

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
        "duplicate_devices_skipped": len(skipped_devs),
        "skipped_device_names": skipped_devs,
        "tags_count": total_tags,
        "views_count": len(view_names),
        "view_names": view_names,
        "alarms_count": alarms_cnt,
        "scripts_count": scripts_cnt,
        "texts_count": texts_cnt,
        "recipes_count": recipes_cnt,
        "has_server": any(d["id"] in ("0", "server") for d in deduped_devs)
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
    Imports a FUXA project into the target server's SQLite database according to its role:

    ROLE = "storage":
      - Imports ONLY unique devices & tags.
      - Strictly deduplicates devices (by normalized name & ID).
      - SKIPS all views, screens, widgets, layouts, alarms, scripts to keep storage lean.
      - Sets a clean default overview view.

    ROLE = "view":
      - Imports HMI views, screens, SVGs, layouts, texts.
      - Preserves zero-driver OPC-UA Storage bridge device (opc.tcp://127.0.0.1:4840).
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

    # -----------------------------------------------------------------
    # BRANCH A: STORAGE SERVER (DEVICES ONLY)
    # -----------------------------------------------------------------
    if role == "storage":
        devs = project_data.get("devices", {})
        if isinstance(devs, list):
            dev_list = devs
        elif isinstance(devs, dict):
            dev_list = list(devs.values())
        else:
            dev_list = []

        # Server device check
        if "server" in project_data and isinstance(project_data["server"], dict):
            srv = project_data["server"]
            has_srv = any(d.get("id") in ("0", "server") or d.get("type") == "FuxaServer" for d in dev_list if isinstance(d, dict))
            if not has_srv:
                if not srv.get("id"):
                    srv["id"] = "0"
                dev_list.insert(0, srv)

        final_devices, skipped_duplicates = dedup_device_candidates(dev_list)

        total_tags = 0
        imported_devices = []
        for d in final_devices:
            dev_obj = d["data"]
            cur.execute("INSERT OR REPLACE INTO devices (name, value) VALUES (?, ?);", (d["id"], json.dumps(dev_obj)))
            imported_devices.append(d["name"])
            total_tags += d["tags_count"]

        # Storage server has NO screens/views from project.json
        # Only 1 clean default overview view
        view_id = f"view_storage_plant_{plant_id}"
        view_obj = {
            "id": view_id,
            "name": f"Plant_{plant_id}_Storage_Overview",
            "profile": {
                "width": 1920,
                "height": 1080,
                "bkcolor": "#12171f",
                "margin": 10
            },
            "items": {},
            "variables": [],
            "svgcontent": (
                '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">'
                '<rect width="1920" height="1080" fill="#12171f"/>'
                '<rect x="260" y="240" width="1400" height="600" rx="16" fill="#1e222d" stroke="#30363d" stroke-width="2"/>'
                f'<text x="960" y="380" fill="#58a6ff" font-size="40" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle" font-weight="bold">Plant {plant_id} Master Storage Server</text>'
                '<text x="960" y="440" fill="#7ee787" font-size="24" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle" font-weight="600">&#9679; Central PLC Driver Gateway &amp; Tag Cache Active</text>'
                f'<text x="960" y="520" fill="#c9d1d9" font-size="20" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle">Total Connected Devices: {len(imported_devices)} | Monitored Tags: {total_tags:,}</text>'
                '<text x="960" y="580" fill="#8b949e" font-size="16" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle">HMI Screens are hosted on dedicated View Servers via OPC-UA Bridge (Port 4840)</text>'
                '<text x="960" y="660" fill="#8b949e" font-size="14" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle">Managed by FUXA Enterprise Fleet Manager</text>'
                '</svg>'
            )
        }
        cur.execute("INSERT OR REPLACE INTO views (name, value) VALUES (?, ?);", (view_id, json.dumps(view_obj)))

        # Complete HMI layout settings for storage server
        layout_data = {
            "start": view_id,
            "navigation": {
                "mode": "fix",
                "type": "inline",
                "bkcolor": "#161b22",
                "fgcolor": "#c9d1d9",
                "items": [
                    {
                        "icon": "home",
                        "view": view_id,
                        "link": "",
                        "text": f"Plant {plant_id} Storage"
                    }
                ]
            },
            "header": {
                "title": f"Plant {plant_id} Master Storage (PLC Gateway)",
                "alarms": False,
                "login": True,
                "items": []
            },
            "showdev": True,
            "zoom": "autoresize",
            "inputdialog": "false",
            "hidenavigation": False,
            "theme": "",
            "loginonstart": False
        }
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('layout', ?);", (json.dumps(layout_data),))
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('version', '1.02');")
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('name', ?);", (json.dumps(f"Plant {plant_id} Master Storage Server"),))

        general_data = {
            "version": "1.02",
            "title": f"Plant {plant_id} Master Storage Server",
            "header": {
                "title": f"Plant {plant_id} | Master Storage (PLC Gateway)",
                "alarms": False,
                "login": True
            }
        }
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('general', ?);", (json.dumps(general_data),))

        conn.commit()
        conn.close()

        try:
            shutil.copy2(db_path, mirror_db_path)
        except Exception:
            pass

        raw_views = project_data.get("hmi", {}).get("views", []) if isinstance(project_data.get("hmi"), dict) else project_data.get("views", [])
        skipped_views_count = len(raw_views) if isinstance(raw_views, (list, dict)) else 0

        return {
            "success": True,
            "role": "storage",
            "db_path": db_path,
            "backup_path": backup_file,
            "devices_count": len(imported_devices),
            "device_names": imported_devices,
            "tags_count": total_tags,
            "views_count": 0,
            "skipped_views_count": skipped_views_count,
            "skipped_duplicates_count": len(skipped_duplicates),
            "skipped_duplicates": skipped_duplicates,
            "message": f"Successfully imported {len(imported_devices)} unique devices into Plant {plant_id} Storage Server. Skipped {skipped_views_count} HMI screens and {len(skipped_duplicates)} duplicate devices."
        }

    # -----------------------------------------------------------------
    # BRANCH B: VIEW SERVER (HMI SCREENS, SVGs & LAYOUT)
    # -----------------------------------------------------------------
    else:
        # 1. Import Views
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

        # 2. Import General Settings & HMI Layout
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

        # Ensure layout in View server has required fields and valid navigation
        cur.execute("SELECT value FROM general WHERE name = 'layout';")
        layout_row = cur.fetchone()
        existing_layout = json.loads(layout_row[0]) if (layout_row and layout_row[0]) else {}

        if not existing_layout.get("start"):
            cur.execute("SELECT name FROM views LIMIT 1;")
            fv = cur.fetchone()
            if fv:
                existing_layout["start"] = fv[0]

        if not isinstance(existing_layout.get("navigation"), dict) or not existing_layout["navigation"].get("mode"):
            start_v = existing_layout.get("start", "")
            existing_layout["navigation"] = {
                "mode": "fix",
                "type": "inline",
                "bkcolor": "#161b22",
                "fgcolor": "#c9d1d9",
                "items": [{"icon": "home", "view": start_v, "link": "", "text": "Home"}]
            }

        if not isinstance(existing_layout.get("header"), dict):
            existing_layout["header"] = {"title": "FUXA HMI", "alarms": True, "login": True, "items": []}

        if "loginonstart" not in existing_layout:
            existing_layout["loginonstart"] = False

        if "showdev" not in existing_layout:
            existing_layout["showdev"] = True

        if "zoom" not in existing_layout:
            existing_layout["zoom"] = "autoresize"

        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('layout', ?);", (json.dumps(existing_layout),))
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('version', '1.02');")

        # 3. Import Texts
        texts = project_data.get("texts", [])
        if isinstance(texts, dict):
            texts = list(texts.values())
        if isinstance(texts, list):
            for item in texts:
                if isinstance(item, dict):
                    t_name = item.get("name") or item.get("id")
                    if t_name:
                        cur.execute("INSERT OR REPLACE INTO texts (name, value) VALUES (?, ?);", (t_name, json.dumps(item)))

        # 4. Import Alarms
        alarms = project_data.get("alarms", [])
        if isinstance(alarms, dict):
            alarms = list(alarms.values())
        if isinstance(alarms, list):
            for item in alarms:
                if isinstance(item, dict):
                    a_name = item.get("name") or item.get("id")
                    if a_name:
                        cur.execute("INSERT OR REPLACE INTO alarms (name, value) VALUES (?, ?);", (a_name, json.dumps(item)))

        # 5. Import Recipes
        recipes = project_data.get("recipes", [])
        if isinstance(recipes, dict):
            recipes = list(recipes.values())
        if isinstance(recipes, list):
            for item in recipes:
                if isinstance(item, dict):
                    r_id = item.get("id") or item.get("name")
                    if r_id:
                        cur.execute("INSERT OR REPLACE INTO recipes (name, value) VALUES (?, ?);", (r_id, json.dumps(item)))

        # 6. Import Notifications
        notifs = project_data.get("notifications", [])
        if isinstance(notifs, dict):
            notifs = list(notifs.values())
        if isinstance(notifs, list):
            for item in notifs:
                if isinstance(item, dict):
                    n_id = item.get("id") or item.get("name")
                    if n_id:
                        cur.execute("INSERT OR REPLACE INTO notifications (name, value) VALUES (?, ?);", (n_id, json.dumps(item)))

        # 7. Import Scripts
        scripts = project_data.get("scripts", [])
        if isinstance(scripts, dict):
            scripts = list(scripts.values())
        if isinstance(scripts, list):
            for item in scripts:
                if isinstance(item, dict):
                    s_id = item.get("id") or item.get("name")
                    if s_id:
                        cur.execute("INSERT OR REPLACE INTO scripts (name, value) VALUES (?, ?);", (s_id, json.dumps(item)))

        # 8. Import Reports
        reports = project_data.get("reports", [])
        if isinstance(reports, dict):
            reports = list(reports.values())
        if isinstance(reports, list):
            for item in reports:
                if isinstance(item, dict):
                    rp_id = item.get("id") or item.get("name")
                    if rp_id:
                        cur.execute("INSERT OR REPLACE INTO reports (name, value) VALUES (?, ?);", (rp_id, json.dumps(item)))

        # 9. Import Maps Locations
        locs = project_data.get("mapsLocations", [])
        if isinstance(locs, dict):
            locs = list(locs.values())
        if isinstance(locs, list):
            for item in locs:
                if isinstance(item, dict):
                    l_id = item.get("id") or item.get("name")
                    if l_id:
                        cur.execute("INSERT OR REPLACE INTO locations (name, value) VALUES (?, ?);", (l_id, json.dumps(item)))

        # 10. Import AR Markers
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

        # 11. Devices Configuration for View Server
        imported_devices = []
        total_tags = 0

        if preserve_bridge:
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
        else:
            devs = project_data.get("devices", {})
            dev_list = list(devs.values()) if isinstance(devs, dict) else (devs if isinstance(devs, list) else [])
            final_devices, _ = dedup_device_candidates(dev_list)
            for d in final_devices:
                cur.execute("INSERT OR REPLACE INTO devices (name, value) VALUES (?, ?);", (d["id"], json.dumps(d["data"])))
                imported_devices.append(d["name"])
                total_tags += d["tags_count"]

        conn.commit()
        conn.close()

        try:
            shutil.copy2(db_path, mirror_db_path)
        except Exception:
            pass

        return {
            "success": True,
            "role": "view",
            "db_path": db_path,
            "backup_path": backup_file,
            "views_count": len(imported_views),
            "view_names": imported_views,
            "devices_count": len(imported_devices),
            "device_names": imported_devices,
            "tags_count": total_tags,
            "message": f"Successfully imported {len(imported_views)} HMI screens into View Server."
        }
