#!/usr/bin/env python3
"""
FUXA Device Manager Utility
Inspect, deduplicate, rename, or remove devices directly from SQLite project database.

Usage:
  python3 scripts/manage_devices.py --list
  python3 scripts/manage_devices.py --dedup
  python3 scripts/manage_devices.py --plant 9 --dedup
  python3 scripts/manage_devices.py --remove <device_id>
  python3 scripts/manage_devices.py --remove-name <device_name>
  python3 scripts/manage_devices.py --rename <device_id> <new_name>
"""

import os
import sys
import glob
import json
import shutil
import sqlite3
import datetime
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUPS_DIR = os.path.join(ROOT_DIR, "locations", "backups")

def is_valid_project_db(file_path):
    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return False
    try:
        conn = sqlite3.connect(file_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='devices';")
        has_table = cur.fetchone() is not None
        conn.close()
        return has_table
    except Exception:
        return False

def count_devices_in_db(file_path):
    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return 0
    try:
        conn = sqlite3.connect(file_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM devices;")
        row = cur.fetchone()
        count = row[0] if row else 0
        conn.close()
        return count
    except Exception:
        return 0

def scan_all_databases():
    """Scans all .db files across the repo and returns list of (path, device_count, size_kb)."""
    candidates = [
        os.path.join(ROOT_DIR, "_appdata", "project.fuxap.db"),
        os.path.join(ROOT_DIR, "_appdata", "_app.db"),
        os.path.join(ROOT_DIR, "server", "_appdata", "project.fuxap.db"),
        os.path.join(ROOT_DIR, "server", "_appdata", "_app.db"),
    ]
    candidates.extend(glob.glob(os.path.join(ROOT_DIR, "locations", "**", "*.db"), recursive=True))

    unique_paths = set()
    results = []
    for p in candidates:
        abs_p = os.path.abspath(p)
        if abs_p not in unique_paths and is_valid_project_db(abs_p):
            unique_paths.add(abs_p)
            cnt = count_devices_in_db(abs_p)
            size_kb = round(os.path.getsize(abs_p) / 1024, 1)
            results.append((abs_p, cnt, size_kb))
    return results

def find_database(custom_path=None, plant=None, port=None):
    if custom_path:
        if is_valid_project_db(custom_path):
            return os.path.abspath(custom_path)
        if os.path.exists(custom_path):
            return os.path.abspath(custom_path)

    # 1. Target by Plant
    if plant is not None:
        p_candidates = [
            os.path.join(ROOT_DIR, "locations", "storage", f"plant_{plant}", "_appdata", "project.fuxap.db"),
            os.path.join(ROOT_DIR, "locations", "storage", f"plant_{plant}", "_appdata", "_app.db"),
            os.path.join(ROOT_DIR, "locations", "storage", f"plant_{plant}", "project.fuxap.db"),
        ]
        # First check if any plant candidate already has devices
        for p in p_candidates:
            if is_valid_project_db(p) and count_devices_in_db(p) > 0:
                return os.path.abspath(p)

        # If plant candidate exists but has 0 devices, look if another db has devices
        all_dbs = scan_all_databases()
        populated = [d for d in all_dbs if d[1] > 0]
        if populated:
            best_db = populated[0][0]
            best_cnt = populated[0][1]
            print(f"[i] Notice: Plant {plant} storage database is empty (0 devices).")
            print(f"    Found active database with {best_cnt} devices at: {best_db}")
            target_plant_db = p_candidates[0]
            os.makedirs(os.path.dirname(target_plant_db), exist_ok=True)
            print(f"    Restoring/copying {best_db} -> {target_plant_db} ...")
            backup_database(target_plant_db)
            shutil.copy2(best_db, target_plant_db)
            print(f"[✓] Restored project database into Plant {plant} storage.")
            return os.path.abspath(target_plant_db)

        # Fallback to empty plant candidate
        for p in p_candidates:
            if is_valid_project_db(p):
                return os.path.abspath(p)

    # 2. Target by Port
    if port is not None:
        for p in glob.glob(os.path.join(ROOT_DIR, "locations", "**", f"*{port}*", "**", "*.db"), recursive=True):
            if is_valid_project_db(p) and count_devices_in_db(p) > 0:
                return os.path.abspath(p)
        for p in glob.glob(os.path.join(ROOT_DIR, "locations", "**", f"*{port}*", "**", "*.db"), recursive=True):
            if is_valid_project_db(p):
                return os.path.abspath(p)

    # 3. Standard locations - prioritize databases with devices > 0
    all_dbs = scan_all_databases()
    populated = [d for d in all_dbs if d[1] > 0]
    if populated:
        return populated[0][0]

    if all_dbs:
        return all_dbs[0][0]

    return None

def backup_database(db_path):
    if not db_path or not os.path.exists(db_path):
        return
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUPS_DIR, f"project_devices_backup_{ts}.fuxap.db")
    shutil.copy2(db_path, dest)
    print(f"[🛡️] Created pre-modification backup: {dest}")

def safe_delete_device(cur, did):
    """Safely deletes device from devices and optional devicesSecurity tables."""
    cur.execute("DELETE FROM devices WHERE name = ?;", (did,))
    try:
        cur.execute("DELETE FROM devicesSecurity WHERE name = ?;", (did,))
    except Exception:
        pass

def disable_device(conn, name_or_id, enable=False):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()

    found = False
    for r in rows:
        did = r[0]
        try:
            val = json.loads(r[1])
            dname = val.get("name", did)
        except Exception:
            continue

        if did == name_or_id or dname.lower() == name_or_id.lower():
            val["enabled"] = enable
            cur.execute("UPDATE devices SET value = ? WHERE name = ?;", (json.dumps(val), did))
            conn.commit()
            action = "Enabled" if enable else "Disabled"
            print(f"[✓] Successfully {action} device '{dname}' (ID: {did}).")
            found = True

    if not found:
        print(f"[X] Device '{name_or_id}' not found.")
    return found

def remove_device_by_name(conn, device_name):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()

    matching = []
    for r in rows:
        did = r[0]
        try:
            val = json.loads(r[1])
            dname = val.get("name", did)
            tags_count = len(val.get("tags", {}))
        except Exception:
            dname = did
            tags_count = 0
        if dname.lower() == device_name.lower():
            matching.append({"id": did, "name": dname, "tags_count": tags_count})

    if not matching:
        print(f"[X] No device found with name: '{device_name}'.")
        return False

    print(f"[i] Found {len(matching)} device(s) matching '{device_name}':")
    for m in matching:
        print(f"    - ID: {m['id']} | Tags: {m['tags_count']}")

    # If duplicate copies, keep one with tags if requested, or delete empty duplicate
    if len(matching) > 1:
        matching.sort(key=lambda d: d["tags_count"], reverse=True)
        to_delete = matching[1:] # delete duplicates
        for d in to_delete:
            safe_delete_device(cur, d["id"])
        conn.commit()
        print(f"[✓] Deleted {len(to_delete)} duplicate copy(ies). Kept primary ID: {matching[0]['id']} with {matching[0]['tags_count']} tags.")
        return True
    else:
        did = matching[0]["id"]
        safe_delete_device(cur, did)
        conn.commit()
        print(f"[✓] Successfully removed device '{matching[0]['name']}' (ID: {did}).")
        return True

def list_devices(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()

    devices = []
    print("\n--- Current FUXA Devices ---")
    if not rows:
        print("  (No devices found in database)")
        return devices

    for r in rows:
        did = r[0]
        try:
            val = json.loads(r[1])
            dname = val.get("name", "<unnamed>")
            dtype = val.get("type", "Unknown")
            tags_count = len(val.get("tags", {}))
            endpoint = val.get("property", {}).get("address", "-")
        except Exception:
            dname = "<corrupt>"
            dtype = "unknown"
            tags_count = 0
            endpoint = "-"

        print(f"  • ID: {did} | Name: '{dname}' | Type: {dtype} | Tags: {tags_count} | Endpoint: {endpoint}")
        devices.append({"id": did, "name": dname, "tags_count": tags_count, "value": r[1]})

    print(f"Total Devices: {len(devices)}\n")
    return devices

def repair_hmi_layout(conn, plant_id=None):
    """
    Ensures table 'general' contains a complete, valid 'layout' object
    and table 'views' contains at least 1 valid view with SVG content.
    This prevents the FUXA Angular web UI from crashing on:
    - this.hmi.layout.navigation.mode (undefined navigation)
    - this.hmi.layout.loginonstart (undefined layout)
    which causes the page to keep loading forever.
    """
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS general (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS views (name TEXT PRIMARY KEY, value TEXT);")

    # 1. Check existing views & ensure valid SVG content and profile
    cur.execute("SELECT name, value FROM views;")
    views_rows = cur.fetchall()

    pid_str = str(plant_id) if plant_id else "9"
    default_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">'
        '<rect width="1920" height="1080" fill="#12171f"/>'
        '<rect x="260" y="240" width="1400" height="600" rx="16" fill="#1e222d" stroke="#30363d" stroke-width="2"/>'
        f'<text x="960" y="380" fill="#58a6ff" font-size="40" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle" font-weight="bold">Plant {pid_str} Master Storage Server</text>'
        '<text x="960" y="440" fill="#7ee787" font-size="24" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle" font-weight="600">&#9679; Central PLC Driver Gateway &amp; Tag Cache Active</text>'
        '<text x="960" y="540" fill="#8b949e" font-size="18" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" text-anchor="middle">HMI Screens are hosted on dedicated View Servers via OPC-UA Bridge (Port 4840)</text>'
        '</svg>'
    )

    if views_rows:
        view_id = views_rows[0][0]
        # Inspect and repair any view missing svgcontent or profile (fixes editor infinite loading freeze)
        for vname, vval in views_rows:
            try:
                vobj = json.loads(vval)
                v_modified = False
                if not isinstance(vobj, dict):
                    vobj = {}
                    v_modified = True
                if not vobj.get("profile") or not isinstance(vobj.get("profile"), dict):
                    vobj["profile"] = {"width": 1920, "height": 1080, "bkcolor": "#12171f", "margin": 10}
                    v_modified = True
                if "width" not in vobj["profile"]:
                    vobj["profile"]["width"] = 1920
                    v_modified = True
                if "height" not in vobj["profile"]:
                    vobj["profile"]["height"] = 1080
                    v_modified = True
                if "bkcolor" not in vobj["profile"]:
                    vobj["profile"]["bkcolor"] = "#12171f"
                    v_modified = True
                if not vobj.get("type"):
                    vobj["type"] = "svg"
                    v_modified = True
                if not isinstance(vobj.get("items"), dict):
                    vobj["items"] = {}
                    v_modified = True
                if not isinstance(vobj.get("variables"), list):
                    vobj["variables"] = []
                    v_modified = True
                if not vobj.get("svgcontent") or not isinstance(vobj.get("svgcontent"), str) or len(vobj.get("svgcontent", "").strip()) == 0:
                    vobj["svgcontent"] = default_svg
                    v_modified = True
                if v_modified:
                    cur.execute("UPDATE views SET value = ? WHERE name = ?;", (json.dumps(vobj), vname))
                    print(f"[✓] Repaired missing SVG canvas content for view '{vname}' (fixed editor loading freeze).")
            except Exception:
                pass
    else:
        view_id = f"view_storage_plant_{pid_str}"
        default_view = {
            "id": view_id,
            "name": f"Plant_{pid_str}_Storage_Overview",
            "type": "svg",
            "profile": {
                "width": 1920,
                "height": 1080,
                "bkcolor": "#12171f",
                "margin": 10
            },
            "items": {},
            "variables": [],
            "svgcontent": default_svg
        }
        cur.execute("INSERT OR REPLACE INTO views (name, value) VALUES (?, ?);", (view_id, json.dumps(default_view)))

    # 2. Check layout in general table
    cur.execute("SELECT value FROM general WHERE name = 'layout';")
    row = cur.fetchone()
    layout = {}
    needs_update = False

    if row and row[0]:
        try:
            layout = json.loads(row[0])
        except Exception:
            layout = {}
            needs_update = True
    else:
        needs_update = True

    if not isinstance(layout, dict):
        layout = {}
        needs_update = True

    if not layout.get("start"):
        layout["start"] = view_id
        needs_update = True

    if not isinstance(layout.get("navigation"), dict) or not layout["navigation"].get("mode"):
        layout["navigation"] = {
            "mode": "fix",
            "type": "inline",
            "bkcolor": "#161b22",
            "fgcolor": "#c9d1d9",
            "items": [
                {
                    "icon": "home",
                    "view": view_id,
                    "link": "",
                    "text": f"Plant {pid_str} Storage"
                }
            ]
        }
        needs_update = True

    if not isinstance(layout.get("header"), dict):
        layout["header"] = {
            "title": f"Plant {pid_str} Master Storage (PLC Gateway)",
            "alarms": False,
            "login": True,
            "items": []
        }
        needs_update = True

    if "loginonstart" not in layout:
        layout["loginonstart"] = False
        needs_update = True

    if "showdev" not in layout:
        layout["showdev"] = True
        needs_update = True

    if "zoom" not in layout:
        layout["zoom"] = "autoresize"
        needs_update = True

    if "hidenavigation" not in layout:
        layout["hidenavigation"] = False
        needs_update = True

    if needs_update:
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('layout', ?);", (json.dumps(layout),))
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('version', '1.02');")
        cur.execute("INSERT OR REPLACE INTO general (name, value) VALUES ('name', ?);", (json.dumps(f"Plant {pid_str} Master Storage Server"),))
        conn.commit()
        print(f"[✓] Repaired HMI Layout & View settings (fixed web loading spinner freeze).")


def dedup_devices(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()

    devices_by_norm_name = {}
    for r in rows:
        did = r[0]
        try:
            val = json.loads(r[1])
            dname = val.get("name", did).strip()
            tags = val.get("tags", {})
            tags_count = len(tags) if isinstance(tags, (dict, list)) else 0
        except Exception:
            dname = did
            tags_count = 0

        norm = dname.lower()
        devices_by_norm_name.setdefault(norm, []).append({
            "id": did,
            "name": dname,
            "tags_count": tags_count,
            "data": val if 'val' in locals() else {}
        })

    to_delete = []
    for norm, dev_list in devices_by_norm_name.items():
        if len(dev_list) > 1:
            # Sort by tags count descending so we keep the device with the most tags configured
            dev_list.sort(key=lambda d: d["tags_count"], reverse=True)
            keeper = dev_list[0]
            duplicates = dev_list[1:]
            print(f"[!] Duplicate device name found: '{keeper['name']}' ({len(dev_list)} copies)")
            print(f"    - Keeping ID: '{keeper['id']}' ({keeper['tags_count']} tags)")
            for dup in duplicates:
                print(f"    - Marking for deletion: ID: '{dup['id']}' ({dup['tags_count']} tags)")
                to_delete.append(dup["id"])

    if not to_delete:
        print("[✓] No duplicate devices found.")
    else:
        for did in to_delete:
            safe_delete_device(cur, did)
        conn.commit()
        print(f"[✓] Successfully deleted {len(to_delete)} duplicate device(s).")

def remove_device(conn, device_id):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices WHERE name = ?;", (device_id,))
    row = cur.fetchone()
    if not row:
        print(f"[X] Device ID '{device_id}' not found in database.")
        return False

    val = json.loads(row[1]) if row[1] else {}
    dname = val.get("name", device_id)
    safe_delete_device(cur, device_id)
    conn.commit()
    print(f"[✓] Successfully removed device '{dname}' (ID: {device_id}).")
    return True

def rename_device(conn, device_id, new_name):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices WHERE name = ?;", (device_id,))
    row = cur.fetchone()
    if not row:
        print(f"[X] Device ID '{device_id}' not found in database.")
        return False

    val = json.loads(row[1]) if row[1] else {}
    old_name = val.get("name", device_id)
    val["name"] = new_name
    cur.execute("UPDATE devices SET value = ? WHERE name = ?;", (json.dumps(val), device_id))
    conn.commit()
    print(f"[✓] Successfully renamed device from '{old_name}' to '{new_name}' (ID: {device_id}).")
    return True

def main():
    parser = argparse.ArgumentParser(description="FUXA Device Manager Utility")
    parser.add_argument("--db", type=str, help="Path to project.fuxap.db (optional, auto-detected if omitted)")
    parser.add_argument("--plant", type=int, help="Target plant storage server (e.g. 9 for Plant 9)")
    parser.add_argument("--port", type=int, help="Target server port (e.g. 5801, 9610)")
    parser.add_argument("--scan", action="store_true", help="Scan and list all FUXA project databases and device counts")
    parser.add_argument("--list", action="store_true", help="List all devices in the database")
    parser.add_argument("--dedup", action="store_true", help="Automatically remove duplicate devices (keeps device with tags)")
    parser.add_argument("--repair", action="store_true", help="Repair HMI layout and views to fix web loading spinner freeze")
    parser.add_argument("--remove", type=str, help="Remove device by ID")
    parser.add_argument("--remove-name", type=str, help="Remove or dedup device by its displayed Name (e.g. 'Gas_Flow_Modbus')")
    parser.add_argument("--disable", type=str, help="Disable a device by Name or ID so FUXA does not poll it")
    parser.add_argument("--enable", type=str, help="Enable a previously disabled device by Name or ID")
    parser.add_argument("--rename", nargs=2, metavar=("DEVICE_ID", "NEW_NAME"), help="Rename device by ID to NEW_NAME")

    args = parser.parse_args()

    if args.scan:
        dbs = scan_all_databases()
        print("\n=== All Discovered FUXA Project Databases ===")
        if not dbs:
            print("  (No project databases found)")
        for path, count, size_kb in dbs:
            star = " ⭐ [ACTIVE]" if count > 0 else ""
            print(f"  • {path} ({size_kb} KB, {count} devices){star}")
        print("")
        return

    db_path = find_database(custom_path=args.db, plant=args.plant, port=args.port)
    if not db_path:
        print("[!] No project.fuxap.db found. Please specify path with --db <path_to_db> or target with --plant <id>")
        sys.exit(1)

    print(f"[i] Using database: {db_path}")

    # Create backup before any destructive operation
    if args.dedup or args.remove or args.remove_name or args.rename or args.repair:
        backup_database(db_path)

    conn = sqlite3.connect(db_path)

    try:
        if args.repair:
            repair_hmi_layout(conn, plant_id=args.plant)
            list_devices(conn)
        elif args.dedup:
            dedup_devices(conn)
            repair_hmi_layout(conn, plant_id=args.plant)
            list_devices(conn)
        elif args.remove:
            remove_device(conn, args.remove)
            list_devices(conn)
        elif args.remove_name:
            remove_device_by_name(conn, args.remove_name)
            list_devices(conn)
        elif args.disable:
            disable_device(conn, args.disable, enable=False)
            list_devices(conn)
        elif args.enable:
            disable_device(conn, args.enable, enable=True)
            list_devices(conn)
        elif args.rename:
            rename_device(conn, args.rename[0], args.rename[1])
            list_devices(conn)
        else:
            list_devices(conn)
    finally:
        conn.close()

    if args.dedup or args.remove or args.remove_name or args.rename or args.repair:
        print("\n[📢] Database updated. If FUXA is running, reload or restart PM2 to apply changes:")
        if args.plant:
            print(f"     pm2 restart P{args.plant}_Storage_Server")
        else:
            print("     pm2 restart P9_Storage_Server  # (or your target instance)")

if __name__ == "__main__":
    main()
