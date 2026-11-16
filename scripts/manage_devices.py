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
            cur.execute("DELETE FROM devices WHERE name = ?;", (d["id"],))
            cur.execute("DELETE FROM devicesSecurity WHERE name = ?;", (d["id"],))
        conn.commit()
        print(f"[✓] Deleted {len(to_delete)} duplicate copy(ies). Kept primary ID: {matching[0]['id']} with {matching[0]['tags_count']} tags.")
        return True
    else:
        did = matching[0]["id"]
        cur.execute("DELETE FROM devices WHERE name = ?;", (did,))
        cur.execute("DELETE FROM devicesSecurity WHERE name = ?;", (did,))
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

def dedup_devices(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()

    devices_by_name = {}
    for r in rows:
        did = r[0]
        try:
            val = json.loads(r[1])
            dname = val.get("name", did)
            tags_count = len(val.get("tags", {}))
        except Exception:
            dname = did
            tags_count = 0
        
        devices_by_name.setdefault(dname, []).append({
            "id": did,
            "name": dname,
            "tags_count": tags_count,
            "data": val if 'val' in locals() else {}
        })

    to_delete = []
    for dname, dev_list in devices_by_name.items():
        if len(dev_list) > 1:
            # Sort by tags count descending so we keep the device with the most tags configured
            dev_list.sort(key=lambda d: d["tags_count"], reverse=True)
            keeper = dev_list[0]
            duplicates = dev_list[1:]
            print(f"[!] Duplicate device name found: '{dname}' ({len(dev_list)} copies)")
            print(f"    - Keeping ID: '{keeper['id']}' ({keeper['tags_count']} tags)")
            for dup in duplicates:
                print(f"    - Marking for deletion: ID: '{dup['id']}' ({dup['tags_count']} tags)")
                to_delete.append(dup["id"])

    if not to_delete:
        print("[✓] No duplicate devices found.")
        return

    for did in to_delete:
        cur.execute("DELETE FROM devices WHERE name = ?;", (did,))
        cur.execute("DELETE FROM devicesSecurity WHERE name = ?;", (did,))

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
    cur.execute("DELETE FROM devices WHERE name = ?;", (device_id,))
    cur.execute("DELETE FROM devicesSecurity WHERE name = ?;", (device_id,))
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
    parser.add_argument("--remove", type=str, help="Remove device by ID")
    parser.add_argument("--remove-name", type=str, help="Remove or dedup device by its displayed Name (e.g. 'Gas_Flow_Modbus')")
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
    if args.dedup or args.remove or args.remove_name or args.rename:
        backup_database(db_path)

    conn = sqlite3.connect(db_path)

    try:
        if args.dedup:
            dedup_devices(conn)
            list_devices(conn)
        elif args.remove:
            remove_device(conn, args.remove)
            list_devices(conn)
        elif args.remove_name:
            remove_device_by_name(conn, args.remove_name)
            list_devices(conn)
        elif args.rename:
            rename_device(conn, args.rename[0], args.rename[1])
            list_devices(conn)
        else:
            list_devices(conn)
    finally:
        conn.close()

    if args.dedup or args.remove or args.remove_name or args.rename:
        print("\n[📢] Database updated. If FUXA is running, reload or restart PM2 to apply changes:")
        if args.plant:
            print(f"     pm2 restart P{args.plant}_Storage_Server")
        else:
            print("     pm2 restart P9_Storage_Server  # (or your target instance)")

if __name__ == "__main__":
    main()
