#!/usr/bin/env python3
"""
==============================================================================
FUXA Enterprise SCADA - 1-Click Dashboard & View Migration Utility
==============================================================================
Migrates dashboards, HMI pages, SVG layouts, and widgets from an existing
production FUXA server or .fuxap / project.json export into a target
FUXA Enterprise View Server instance.

Automatically:
1. Extracts all views and layout definitions.
2. Analyzes widget tag bindings and auto-remaps tag IDs to the new Central Storage
   tags by matching tag names (zero manual remapping).
3. Injects views directly into the target View Server's SQLite database.
4. Generates navigation links in the top header.
5. Hot-reloads the View Server so dashboards are instantly accessible.
==============================================================================
"""

import sys
import os
import json
import sqlite3
import argparse
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INSTANCES_DIR = os.path.join(BASE_DIR, "instances")
FLEET_MANAGER_URL = os.environ.get("FLEET_MANAGER_URL", "http://localhost:9000")

sys.path.insert(0, os.path.join(BASE_DIR, "manager"))
sys.path.insert(0, SCRIPT_DIR)
from project_builder import get_storage_devices_catalog, get_plant_opcua_endpoint
from import_devices_to_storage import compute_device_signature, normalize_string, is_ignored_device


def load_source_project(source_path_or_url) -> dict:
    """Loads FUXA project JSON from a Python dict, remote URL, a .fuxap, or a .json file."""
    if isinstance(source_path_or_url, dict):
        return source_path_or_url
    if isinstance(source_path_or_url, (bytes, bytearray)):
        return json.loads(source_path_or_url.decode("utf-8"))
    if source_path_or_url.startswith("http://") or source_path_or_url.startswith("https://"):
        endpoint = source_path_or_url
        if not endpoint.endswith("/api/project"):
            endpoint = endpoint.rstrip("/") + "/api/project"
        print(f"[*] Fetching live project from {endpoint}...")
        req = urllib.request.Request(endpoint, headers={"User-Agent": "FUXA-Migrator/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    else:
        fpath = os.path.abspath(source_path_or_url)
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Source file not found: {fpath}")
        print(f"[*] Reading project export from {fpath}...")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data


def get_target_db_path(target: str) -> tuple[str, str, int, int]:
    """
    Resolves the target SQLite DB path, instance ID, port, and plant ID.
    target can be:
    - port number (e.g. 9610)
    - instance id (e.g. fuxa_p9_d6_l1_9610)
    - subpath (e.g. /p9/ps/ems)
    """
    reg_path = os.path.join(INSTANCES_DIR, "registry.json")
    instances = {}
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r") as f:
                reg = json.load(f)
                instances = reg.get("instances", {})
        except Exception:
            pass

    # Try matching by port or string
    matched_inst = None
    target_str = str(target).strip()
    
    for i_id, i_info in instances.items():
        if str(i_info.get("port")) == target_str:
            matched_inst = i_info
            break
        if i_id == target_str or i_info.get("name", "").lower() == target_str.lower():
            matched_inst = i_info
            break
        if i_info.get("subpath", "").rstrip("/") == target_str.rstrip("/"):
            matched_inst = i_info
            break

    if matched_inst:
        port = matched_inst["port"]
        inst_id = matched_inst["id"]
        plant_id = int(matched_inst.get("plant", 9))
        canonical_work_dir = os.path.abspath(os.path.join(INSTANCES_DIR, f"port_{port}"))
        work_dir = matched_inst.get("work_dir")
        if not work_dir or not os.path.exists(work_dir) or "FUXA-Enterprised-master" in str(work_dir):
            work_dir = canonical_work_dir
    else:
        # Fallback to port folder
        if target_str.isdigit():
            port = int(target_str)
            inst_id = f"port_{port}"
            plant_id = int(str(port)[1]) if str(port).startswith("5") and len(str(port)) >= 4 else 9
            work_dir = os.path.abspath(os.path.join(INSTANCES_DIR, f"port_{port}"))
        else:
            raise ValueError(f"Could not identify View Server instance for '{target}'. Check Fleet Manager.")

    db_path = os.path.join(work_dir, "project.fuxap.db")
    if not os.path.exists(db_path):
        os.makedirs(work_dir, exist_ok=True)
        from project_builder import generate_fuxa_database
        print(f"[*] Target View Server database not found at {db_path}. Auto-generating initial database...")
        db_path = generate_fuxa_database(
            target_dir=work_dir,
            plant_id=plant_id,
            division_name=f"Plant {plant_id}",
            line_name=f"Line {port}",
            project_name=matched_inst.get("name") if matched_inst else f"View Server Port {port}",
            opcua_endpoint=get_plant_opcua_endpoint(plant_id),
            base_dir=BASE_DIR
        )

    return db_path, inst_id, port, plant_id


def sync_matching_storage_devices_to_view(
    src_project: dict,
    db_path: str,
    plant_id: int,
    dry_run: bool = False
) -> dict:
    """
    1. Extracts incoming devices from src_project.
    2. Strictly ignores/filters direct PLC devices (Modbus/S7/etc.) - they are NEVER added directly.
    3. Matches incoming devices against the Plant Storage Server catalog (by hardware signature, name, or ID).
    4. Imports/syncs those matched devices FROM THE STORAGE SERVER into this View Server's SQLite DB:
       - Configured as Central Storage OPC-UA bridged devices (opc.tcp://127.0.0.1:4845/fuxa/server/ or plant hub).
       - Pre-populated with the Central Storage tags.
    """
    report = {
        "matched_from_storage": [],
        "ignored_direct_devices": [],
        "missing_in_storage": []
    }

    # Extract source devices
    src_devs = src_project.get("devices") or {}
    if isinstance(src_devs, list):
        src_devs = {d.get("id") or f"d_{i}": d for i, d in enumerate(src_devs) if isinstance(d, dict)}

    # Filter out internal server device (id 0 / server)
    filtered_src = {}
    for d_k, d_v in src_devs.items():
        if isinstance(d_v, dict) and not is_ignored_device(d_v):
            filtered_src[d_k] = d_v

    if not filtered_src:
        return report

    print(f"\n[*] Auditing {len(filtered_src)} device(s) from source project against Plant {plant_id} Storage Server...")

    # Load Central Storage catalog for this plant
    storage_catalog = get_storage_devices_catalog(plant_id, base_dir=BASE_DIR)
    plant_endpoint = get_plant_opcua_endpoint(plant_id)

    # Build signature and name lookup tables
    storage_by_sig = {}
    storage_by_name = {}
    storage_by_id = {}

    for s_dev in storage_catalog:
        sig = compute_device_signature(s_dev)
        storage_by_sig[sig] = s_dev
        n_name = normalize_string(s_dev.get("name") or "")
        if n_name:
            storage_by_name[n_name] = s_dev
        if s_dev.get("id"):
            storage_by_id[s_dev["id"]] = s_dev

    devices_to_inject = []

    for d_k, d_obj in filtered_src.items():
        dev_name = d_obj.get("name") or d_k
        dev_type = d_obj.get("type") or "Unknown"
        report["ignored_direct_devices"].append({"name": dev_name, "type": dev_type})

        sig = compute_device_signature(d_obj)
        name_norm = normalize_string(dev_name)

        # Match against Storage Server catalog
        matched_s_dev = None
        match_reason = None

        if name_norm and name_norm in storage_by_name:
            matched_s_dev = storage_by_name[name_norm]
            match_reason = f"Normalized Name match ('{dev_name}')"
        elif d_obj.get("id") and d_obj["id"] in storage_by_id:
            matched_s_dev = storage_by_id[d_obj["id"]]
            match_reason = f"Device ID match ('{d_obj['id']}')"
        elif sig in storage_by_sig and len([s for s in storage_catalog if compute_device_signature(s) == sig]) == 1:
            matched_s_dev = storage_by_sig[sig]
            match_reason = f"Hardware Signature match ({sig})"

        clean_dev_name = (matched_s_dev.get("name") if matched_s_dev else dev_name).replace(" ", "_")

        if matched_s_dev:
            # Strictly configure View Server device as an OPC-UA Client device to the Plant Hub
            # Zero direct physical PLC connections are permitted on View Servers
            bridged_dev = strip_historical_daq_for_view(matched_s_dev)
            bridged_dev["type"] = "OPCUA"
            bridged_dev["connection"] = "opc-ua"
            bridged_dev["enabled"] = True
            bridged_dev["polling"] = 1000
            bridged_dev["influxdb_logging"] = False
            bridged_dev["property"] = {
                "address": plant_endpoint,
                "options": {
                    "securityMode": "None",
                    "securityPolicy": "None"
                }
            }

            # Map all tags to OPC-UA address space on Plant Hub and strictly disable DAQ
            tags = bridged_dev.get("tags") or {}
            for t_id, t_info in tags.items():
                if isinstance(t_info, dict):
                    t_name = t_info.get("name", t_id)
                    t_info["address"] = f"ns=2;s=Plant_{plant_id}.{clean_dev_name}.{t_name}"
                    t_info["daq"] = {
                        "enabled": False,
                        "changed": False,
                        "interval": 0,
                        "restored": False
                    }
            bridged_dev["tags"] = tags

            tag_count = len(tags)
            devices_to_inject.append((bridged_dev, "opc-ua"))
            report["matched_from_storage"].append({
                "source_name": dev_name,
                "storage_name": matched_s_dev.get("name"),
                "tags_count": tag_count,
                "reason": match_reason
            })
            print(f"    ✓ Matched '{dev_name}' -> Configured as OPC-UA Client Device ({tag_count} tags, Endpoint: {plant_endpoint}, DAQ: disabled)")
        else:
            # Source device not yet in Central Storage: Convert directly to OPC-UA Client device so widgets work!
            opcua_dev = {
                "id": d_obj.get("id") or f"dev_opc_{name_norm or 'dev'}",
                "name": dev_name,
                "type": "OPCUA",
                "connection": "opc-ua",
                "enabled": True,
                "polling": 1000,
                "influxdb_logging": False,
                "property": {
                    "address": plant_endpoint,
                    "options": {
                        "securityMode": "None",
                        "securityPolicy": "None"
                    }
                },
                "tags": {}
            }
            src_tags = d_obj.get("tags") or {}
            if isinstance(src_tags, list):
                src_tags = {t.get("id") or f"t_{i}": t for i, t in enumerate(src_tags) if isinstance(t, dict)}
            for st_id, st_info in src_tags.items():
                if isinstance(st_info, dict):
                    st_name = st_info.get("name", st_id)
                    clean_t = dict(st_info)
                    clean_t["address"] = f"ns=2;s=Plant_{plant_id}.{clean_dev_name}.{st_name}"
                    clean_t["daq"] = {"enabled": False, "changed": False, "interval": 0, "restored": False}
                    opcua_dev["tags"][st_id] = clean_t

            tag_count = len(opcua_dev["tags"])
            devices_to_inject.append((opcua_dev, "opc-ua"))
            report["missing_in_storage"].append(dev_name)
            print(f"    ✓ Interlock Enforced: '{dev_name}' ({dev_type}) direct PLC connection stripped -> Auto-converted to OPC-UA Client device ({tag_count} tags)")

    if not dry_run and devices_to_inject:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA busy_timeout = 5000;")
        cur.execute("CREATE TABLE IF NOT EXISTS devices (name TEXT PRIMARY KEY, value TEXT, connection TEXT, cntid TEXT, cntpwd TEXT);")
        for b_dev, dev_conn in devices_to_inject:
            cur.execute(
                "INSERT OR REPLACE INTO devices (name, value, connection, cntid, cntpwd) VALUES (?, ?, ?, ?, ?);",
                (b_dev["id"], json.dumps(b_dev), dev_conn, "", "")
            )
        conn.commit()
        try:
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass
        conn.close()
        print(f"[+] Successfully injected {len(devices_to_inject)} matched Storage device(s) into View Server database.")

    return report


def load_target_tags(db_path: str) -> tuple[dict, dict, dict]:
    """
    Loads all tags currently present in the target View Server database.
    Returns:
    - by_name:  { normalized_name: { id, name, dev_name, dev_id } }
    - by_alpha: { alphanumeric_clean_name: { id, name, dev_name, dev_id } }
    - by_id:    { tag_id: { id, name, dev_name, dev_id } }
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()
    conn.close()

    by_name = {}
    by_alpha = {}
    by_id = {}

    for dev_id, dev_val in rows:
        try:
            dev_data = json.loads(dev_val)
            dev_name = dev_data.get("name", dev_id)
            tags = dev_data.get("tags", {})
            for t_id, t_info in tags.items():
                t_name = t_info.get("name", t_id)
                tag_entry = {
                    "id": t_id,
                    "name": t_name,
                    "dev_name": dev_name,
                    "dev_id": dev_id
                }
                by_id[t_id] = tag_entry
                
                # Standard normalized (lowercase with underscores)
                norm_name = t_name.strip().lower().replace(" ", "_")
                by_name[norm_name] = tag_entry
                
                # Pure alphanumeric key for robust cross-project tolerance
                alpha_key = normalize_string(t_name)
                if alpha_key:
                    by_alpha[alpha_key] = tag_entry
        except Exception:
            pass

    return by_name, by_alpha, by_id


def resolve_tag_match(var_identifier: str, by_id: dict, by_name: dict, by_alpha: dict) -> dict | None:
    """Finds a matching target tag by ID, normalized name, or alphanumeric signature"""
    if not var_identifier:
        return None
    val_str = str(var_identifier).strip()
    if val_str in by_id:
        return by_id[val_str]
    norm_name = val_str.lower().replace(" ", "_")
    if norm_name in by_name:
        return by_name[norm_name]
    alpha_key = normalize_string(val_str)
    if alpha_key in by_alpha:
        return by_alpha[alpha_key]
    return None


def remap_view_bindings(view_obj: dict, target_tags_by_name: dict, target_tags_by_alpha: dict, target_tags_by_id: dict) -> tuple[dict, dict]:
    """
    Inspects all widget items in the view and remaps their tag bindings
    (primary telemetry, gauges min/max, colors, status) to the target server's tags.
    """
    stats = {
        "total_items": 0,
        "bound_items": 0,
        "exact_matches": 0,
        "remapped": 0,
        "unmatched": []
    }

    items = view_obj.get("items", {})
    stats["total_items"] = len(items)

    for item_id, item in items.items():
        prop = item.get("property")
        if not prop or not isinstance(prop, dict):
            continue

        var_id = prop.get("variableId")
        var_name = prop.get("variable")

        if not var_id and not var_name:
            continue

        stats["bound_items"] += 1

        # Resolve primary variable
        matched = resolve_tag_match(var_id, target_tags_by_id, target_tags_by_name, target_tags_by_alpha)
        if not matched and var_name:
            matched = resolve_tag_match(var_name, target_tags_by_id, target_tags_by_name, target_tags_by_alpha)

        if matched:
            if var_id == matched["id"]:
                stats["exact_matches"] += 1
            else:
                stats["remapped"] += 1
            prop["variableId"] = matched["id"]
            prop["variable"] = matched["name"]
            prop["variableSrc"] = matched["dev_name"]
        else:
            stats["unmatched"].append({
                "item_id": item_id,
                "item_type": item.get("type"),
                "variable": var_name or var_id
            })

        # Remap secondary gauge properties if present
        for sec_key in ("minVariableId", "maxVariableId", "variableColorId"):
            if sec_key in prop and prop[sec_key]:
                sec_match = resolve_tag_match(prop[sec_key], target_tags_by_id, target_tags_by_name, target_tags_by_alpha)
                if sec_match:
                    prop[sec_key] = sec_match["id"]

    return view_obj, stats


def migrate(source: str, target: str, dry_run: bool = False, keep_existing: bool = True):
    print("=" * 70)
    print(" FUXA Enterprise SCADA - 1-Click Dashboard Migration")
    print("=" * 70)

    # 1. Load source project
    src_project = load_source_project(source)

    # Functional Interlock 1: If target is a Storage Server, redirect to device-only importer!
    # Storage servers are strictly for connecting devices & enabling historical tags.
    target_clean = str(target).strip().lower()
    is_storage = "storage" in target_clean or (target_clean.isdigit() and 5000 <= int(target_clean) < 6000 and (int(target_clean) % 100 == 0 or target_clean == "5900"))
    if is_storage:
        print("[!] Functional Interlock 1 Active: Storage Servers are exclusively for device connectivity & DAQ.")
        print("    Stripping all HMI views and routing physical devices into Central Storage...")
        from import_devices_to_storage import import_devices
        p_id = 9
        if target_clean.isdigit() and 5000 <= int(target_clean) < 6000:
            p_val = int(target_clean)
            p_id = 9 if p_val == 5900 else (p_val - 5000) // 100
        else:
            import re
            m = re.search(r"p(?:lant)?_?(\d+)", target_clean)
            if m:
                p_id = int(m.group(1))
        rep = import_devices(
            source_files=[src_project],
            plant_id=p_id,
            dry_run=dry_run,
            create_backup=True,
            restart_storage=not dry_run,
            enable_history=True
        )
        return {
            "success": True,
            "interlock_enforced": True,
            "interlock": "STORAGE_SERVER_ONLY_DEVICES",
            "message": f"Storage Server Functional Interlock: Plant {p_id} Central Storage Server is strictly dedicated to connecting field devices and enabling historical InfluxDB tags. All views, HMI screens, and layouts were automatically and safely stripped, and physical devices and tags were imported into Central Storage.",
            "report": rep
        }

    src_hmi = src_project.get("hmi", {})
    src_views = src_hmi.get("views", [])

    if not src_views and "views" in src_project:
        # Handle project where views is top-level
        src_views = src_project.get("views", [])

    if not src_views:
        print("[-] Error: No views found in the source project.")
        return False

    print(f"[+] Found {len(src_views)} view(s) in source project:")
    for v in src_views:
        v_name = v.get("name", "Unnamed")
        v_id = v.get("id", "Unknown")
        item_cnt = len(v.get("items", {}))
        print(f"    • [{v_id}] {v_name} ({item_cnt} widgets)")

    # 2. Resolve target DB, plant & sync matched devices from Storage Server
    db_path, inst_id, port, plant_id = get_target_db_path(target)
    work_dir = os.path.dirname(os.path.abspath(db_path))
    print(f"[+] Target View Server: {inst_id} (Port {port}, Plant {plant_id})")
    print(f"[+] Target Database:    {db_path}")

    # Synchronize matching devices from Central Storage Server FIRST (ignore direct PLC connections)
    storage_sync_report = sync_matching_storage_devices_to_view(src_project, db_path, plant_id, dry_run=dry_run)

    tags_by_name, tags_by_alpha, tags_by_id = load_target_tags(db_path)
    print(f"[+] Loaded {len(tags_by_id)} target tag(s) across connected storage devices.")

    # 3. Remap all views
    remapped_views = []
    total_stats = {
        "views": len(src_views),
        "total_items": 0,
        "bound_items": 0,
        "exact_matches": 0,
        "remapped": 0,
        "unmatched": []
    }

    for v in src_views:
        rem_view, s = remap_view_bindings(v, tags_by_name, tags_by_alpha, tags_by_id)
        remapped_views.append(rem_view)
        total_stats["total_items"] += s["total_items"]
        total_stats["bound_items"] += s["bound_items"]
        total_stats["exact_matches"] += s["exact_matches"]
        total_stats["remapped"] += s["remapped"]
        total_stats["unmatched"].extend(s["unmatched"])

    print("-" * 70)
    print(" Tag Binding Analysis:")
    print(f" • Total Widgets Analyzed:   {total_stats['total_items']}")
    print(f" • Bound Telemetry Widgets:  {total_stats['bound_items']}")
    print(f" • Exact Tag ID Matches:     {total_stats['exact_matches']}")
    print(f" • Auto-Remapped by Name:    {total_stats['remapped']}")
    print(f" • Unmatched Field Tags:     {len(total_stats['unmatched'])}")

    if total_stats["unmatched"]:
        print("   Notice - Unmatched tags in source widgets:")
        for u in total_stats["unmatched"][:10]:
            print(f"     - [{u['item_type']}] Variable: '{u['variable']}'")
        if len(total_stats["unmatched"]) > 10:
            print(f"     ... and {len(total_stats['unmatched']) - 10} more.")

    if dry_run:
        print("\n[!] Dry run mode active: No changes written to database.")
        return {
            "success": True,
            "views_count": len(remapped_views),
            "views": [{"id": v.get("id"), "name": v.get("name", "Unnamed"), "widgets": len(v.get("items", {}))} for v in remapped_views],
            "stats": total_stats,
            "target_instance": inst_id,
            "target_port": port,
            "dry_run": True,
            "message": f"[Dry Run] Successfully simulated migration of {len(remapped_views)} view(s) to Port {port}."
        }

    # 4. Write views and layout into target SQLite DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    if not keep_existing:
        print("[*] Clearing existing views in target database...")
        cur.execute("DELETE FROM views;")
    else:
        # If target has dummy auto-generated 'view_overview' with 0 items, clean it so real imported views take precedence
        cur.execute("SELECT name, value FROM views WHERE name = 'view_overview';")
        vo_row = cur.fetchone()
        if vo_row:
            try:
                vo_data = json.loads(vo_row[1])
                if not vo_data.get("items") or len(vo_data.get("items", {})) == 0:
                    cur.execute("DELETE FROM views WHERE name = 'view_overview';")
                    print("    ✓ Replaced empty placeholder 'view_overview' with real imported views")
            except Exception:
                pass

    # Functional Interlock 4: Avoid duplicate views in View Server
    cur.execute("SELECT name, value FROM views;")
    existing_views = {}
    existing_name_to_id = {}
    for r_name, r_val in cur.fetchall():
        try:
            v_data = json.loads(r_val)
            existing_views[r_name] = v_data
            norm_vname = normalize_string(v_data.get("name") or "")
            if norm_vname:
                existing_name_to_id[norm_vname] = r_name
        except Exception:
            pass

    for v in remapped_views:
        v_id = v.get("id") or f"view_{normalize_string(v.get('name') or 'page')}"
        v_name = v.get("name", "Unnamed")
        norm_vname = normalize_string(v_name)

        target_v_id = v_id
        if v_id in existing_views:
            target_v_id = v_id
            print(f"    ✓ Replaced existing view by ID: {v_name} ({target_v_id})")
        elif norm_vname and norm_vname in existing_name_to_id:
            target_v_id = existing_name_to_id[norm_vname]
            v["id"] = target_v_id
            print(f"    ✓ Reconciled duplicate view name: '{v_name}' mapped to existing view ID ({target_v_id})")
        else:
            target_v_id = v_id
            print(f"    ✓ Imported new unique view: {v_name} ({target_v_id})")

        v["id"] = target_v_id
        cur.execute("INSERT OR REPLACE INTO views (name, value) VALUES (?, ?);", (target_v_id, json.dumps(v)))
        existing_views[target_v_id] = v
        if norm_vname:
            existing_name_to_id[norm_vname] = target_v_id

    # 5. Import non-device resources (texts, charts)
    if "texts" in src_project and isinstance(src_project["texts"], dict):
        cur.execute("CREATE TABLE IF NOT EXISTS texts (name TEXT PRIMARY KEY, value TEXT);")
        for t_k, t_v in src_project["texts"].items():
            t_json = json.dumps(t_v) if not isinstance(t_v, str) else t_v
            cur.execute("INSERT OR REPLACE INTO texts (name, value) VALUES (?, ?);", (t_k, t_json))
        print(f"    ✓ Imported {len(src_project['texts'])} text resource(s)")

    if "charts" in src_project and isinstance(src_project["charts"], (dict, list)):
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES (?, ?);", ("charts", json.dumps(src_project["charts"])))
        print("    ✓ Imported chart configuration")

    # 6. Extract source layout & preserve user's start view and navigation
    src_layout = src_hmi.get("layout") or src_project.get("layout") or {}

    cur.execute("SELECT value FROM general WHERE name='layout';")
    row = cur.fetchone()
    layout = {}
    if row and row[0]:
        try:
            layout = json.loads(row[0])
        except Exception:
            pass

    # Merge source layout settings (theme, header, zoom, inputdialog) into layout
    for k in ("theme", "zoom", "header", "inputdialog", "showdev"):
        if k in src_layout and src_layout[k] is not None:
            layout[k] = src_layout[k]

    # Determine start view - ALWAYS point to real imported view, never a dummy view
    imported_view_ids = [v.get("id") for v in remapped_views if v.get("id")]
    src_start = src_layout.get("start")
    if src_start and src_start in imported_view_ids:
        start_view = src_start
    elif imported_view_ids:
        start_view = imported_view_ids[0]
    else:
        start_view = "view_overview"

    layout["start"] = start_view

    # Configure Navigation
    nav = layout.get("navigation") or {}
    if "mode" not in nav or nav.get("mode") == "fix":
        nav["mode"] = src_layout.get("navigation", {}).get("mode", "over")
    if "type" not in nav:
        nav["type"] = src_layout.get("navigation", {}).get("type", "inline")

    # Merge navigation items - strictly avoid duplicate views or duplicate labels
    src_nav_items = src_layout.get("navigation", {}).get("items", [])
    merged_items = []
    seen_nav_ids = set()
    seen_nav_labels = set()

    for it in src_nav_items:
        if isinstance(it, dict) and it.get("view") in imported_view_ids:
            vid = it.get("view")
            vlabel = normalize_string(it.get("text") or "")
            if vid not in seen_nav_ids and (not vlabel or vlabel not in seen_nav_labels):
                merged_items.append(it)
                seen_nav_ids.add(vid)
                if vlabel:
                    seen_nav_labels.add(vlabel)

    colors = ["#1e293b", "#0f172a", "#1e1b4b", "#172554", "#064e3b"]
    for idx, v in enumerate(remapped_views):
        v_id = v.get("id")
        v_label = v.get("name", f"Page {idx+1}")
        norm_label = normalize_string(v_label)
        if v_id and v_id not in seen_nav_ids and (not norm_label or norm_label not in seen_nav_labels):
            merged_items.append({
                "view": v_id,
                "text": v_label,
                "icon": "dashboard",
                "bkcolor": colors[idx % len(colors)],
                "fgcolor": "#ffffff"
            })
            seen_nav_ids.add(v_id)
            if norm_label:
                seen_nav_labels.add(norm_label)

    nav["items"] = merged_items
    layout["navigation"] = nav

    cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES (?, ?);", ("layout", json.dumps(layout)))

    # 7. Strictly enforce NO historical DAQ on any device or tag on this View Server
    cur.execute("SELECT name, value FROM devices;")
    for d_name, d_val in cur.fetchall():
        if d_name in ("server", "0"):
            continue
        try:
            d_obj = json.loads(d_val)
            d_obj["influxdb_logging"] = False
            tags = d_obj.get("tags") or {}
            changed = False
            for t_id, t_info in tags.items():
                if isinstance(t_info, dict):
                    t_info["daq"] = {
                        "enabled": False,
                        "changed": False,
                        "interval": 0,
                        "restored": False
                    }
                    changed = True
            if changed:
                cur.execute("UPDATE devices SET value = ? WHERE name = ?;", (json.dumps(d_obj), d_name))
        except Exception:
            pass
    print("[+] Verified and strictly disabled historical DAQ across all View Server tags.")

    try:
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass

    conn.commit()
    conn.close()

    print("[+] Database committed successfully.")

    # Mirror to runtime _appdata/ where FUXA server reads it
    appdata_dir = os.path.join(work_dir, "_appdata")
    os.makedirs(appdata_dir, exist_ok=True)
    dest_db = os.path.join(appdata_dir, "project.fuxap.db")
    try:
        if os.path.abspath(db_path) != os.path.abspath(dest_db):
            import shutil
            shutil.copy2(db_path, dest_db)
            print(f"[+] Mirrored database to FUXA runtime path: {dest_db}")
    except Exception as e:
        print(f"[*] Note: Could not mirror to _appdata: {e}")

    # Remove all stale WAL lock / journal files so FUXA restarts cleanly with updated database
    for p in [db_path, dest_db]:
        for sfx in ["-wal", "-shm", "-journal"]:
            f = p + sfx
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    # Ensure mysettings.json is provisioned with hideEditorOnboarding: true so onboarding wizard never pops up
    settings_file = os.path.join(appdata_dir, "mysettings.json")
    cur_settings = {}
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                cur_settings = json.load(f)
        except Exception:
            pass
    cur_settings["hideEditorOnboarding"] = True
    if "language" not in cur_settings:
        cur_settings["language"] = "en"
    if "secureEnabled" not in cur_settings:
        cur_settings["secureEnabled"] = False
    try:
        with open(settings_file, "w") as f:
            json.dump(cur_settings, f, indent=2)
    except Exception:
        pass

    # 7. Request View Server reload via Fleet Manager
    try:
        reload_url = f"{FLEET_MANAGER_URL.rstrip('/')}/api/instances/{inst_id}/sync-tags"
        req = urllib.request.Request(reload_url, data=b"", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[+] Hot-reloaded View Server via Fleet Manager: {resp.read().decode('utf-8')[:80]}...")
    except Exception as e:
        print(f"[*] Note: Manual reload may be required if Fleet Manager is not listening at {FLEET_MANAGER_URL} ({e})")

    print("\n" + "=" * 70)
    print(f" ✓ MIGRATION COMPLETE! Migrated {len(remapped_views)} dashboard(s) to Port {port}!")
    print(f"   View live at: http://localhost:{port}/ or via Gateway subpath.")
    print("=" * 70)
    return {
        "success": True,
        "views_count": len(remapped_views),
        "views": [{"id": v.get("id"), "name": v.get("name", "Unnamed"), "widgets": len(v.get("items", {}))} for v in remapped_views],
        "storage_devices_matched": storage_sync_report.get("matched_from_storage", []),
        "missing_in_storage": storage_sync_report.get("missing_in_storage", []),
        "stats": total_stats,
        "target_instance": inst_id,
        "target_port": port,
        "dry_run": False,
        "message": f"Successfully migrated {len(remapped_views)} dashboard(s) to {inst_id} (Port {port})"
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FUXA Enterprise SCADA Dashboard Migrator")
    parser.add_argument("--source", "-s", required=True, help="Path to .fuxap / .json file or old server URL (e.g. http://192.168.1.50:1881)")
    parser.add_argument("--target", "-t", default="9610", help="Target View Server port, instance ID, or subpath (default: 9610)")
    parser.add_argument("--dry-run", action="store_true", help="Preview tag matches and remappings without writing to DB")
    parser.add_argument("--replace", action="store_true", help="Replace existing views instead of appending")

    args = parser.parse_args()
    try:
        migrate(args.source, args.target, dry_run=args.dry_run, keep_existing=not args.replace)
    except Exception as ex:
        print(f"\n[-] Migration failed: {ex}")
        sys.exit(1)
