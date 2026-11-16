#!/usr/bin/env python3
"""
FUXA Device Manager Utility
Inspect, deduplicate, rename, or remove devices directly from SQLite project database.

Usage:
  python3 scripts/manage_devices.py --list
  python3 scripts/manage_devices.py --dedup
  python3 scripts/manage_devices.py --remove <device_id>
  python3 scripts/manage_devices.py --rename <device_id> <new_name>
"""

import os
import sys
import glob
import json
import sqlite3
import argparse

def find_database(custom_path=None):
    if custom_path and os.path.exists(custom_path):
        return custom_path

    candidates = [
        os.path.join(os.getcwd(), "_appdata", "project.fuxap.db"),
        os.path.join(os.getcwd(), "server", "_appdata", "project.fuxap.db"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "_appdata", "project.fuxap.db"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "server", "_appdata", "project.fuxap.db"),
    ]
    loc_pattern = os.path.join(os.getcwd(), "locations", "**", "project.fuxap.db")
    candidates.extend(glob.glob(loc_pattern, recursive=True))

    for p in candidates:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None

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
    parser.add_argument("--list", action="store_true", help="List all devices in the database")
    parser.add_argument("--dedup", action="store_true", help="Automatically remove duplicate devices (keeps device with tags)")
    parser.add_argument("--remove", type=str, help="Remove device by ID")
    parser.add_argument("--rename", nargs=2, metavar=("DEVICE_ID", "NEW_NAME"), help="Rename device by ID to NEW_NAME")

    args = parser.parse_args()

    db_path = find_database(args.db)
    if not db_path:
        print("[!] No project.fuxap.db found. Please specify path with --db <path_to_db>")
        sys.exit(1)

    print(f"[i] Using database: {db_path}")
    conn = sqlite3.connect(db_path)

    try:
        if args.dedup:
            dedup_devices(conn)
            list_devices(conn)
        elif args.remove:
            remove_device(conn, args.remove)
            list_devices(conn)
        elif args.rename:
            rename_device(conn, args.rename[0], args.rename[1])
            list_devices(conn)
        else:
            list_devices(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
