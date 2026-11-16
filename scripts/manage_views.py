#!/usr/bin/env python3
"""
FUXA View Manager Utility
Inspect, deduplicate, rename, or remove HMI views directly from SQLite project database.

Usage:
  python3 scripts/manage_views.py --list
  python3 scripts/manage_views.py --dedup
  python3 scripts/manage_views.py --remove <view_id>
  python3 scripts/manage_views.py --rename <view_id> <new_name>
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
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='views';")
        has_table = cur.fetchone() is not None
        conn.close()
        return has_table
    except Exception:
        return False

def count_views_in_db(file_path):
    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return 0
    try:
        conn = sqlite3.connect(file_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM views;")
        row = cur.fetchone()
        count = row[0] if row else 0
        conn.close()
        return count
    except Exception:
        return 0

def backup_database(db_path):
    if not db_path or not os.path.exists(db_path):
        return
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUPS_DIR, f"project_views_backup_{ts}.fuxap.db")
    shutil.copy2(db_path, dest)
    print(f"[🛡️] Created pre-modification backup: {dest}")

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
        for p in p_candidates:
            if is_valid_project_db(p) and count_views_in_db(p) > 0:
                return os.path.abspath(p)
        for p in p_candidates:
            if is_valid_project_db(p):
                return os.path.abspath(p)

    # 2. Target by Port
    if port is not None:
        for p in glob.glob(os.path.join(ROOT_DIR, "locations", "**", f"*{port}*", "**", "*.db"), recursive=True):
            if is_valid_project_db(p) and count_views_in_db(p) > 0:
                return os.path.abspath(p)

    # 3. Standard locations
    candidates = [
        os.path.join(ROOT_DIR, "locations", "storage", "plant_9", "_appdata", "project.fuxap.db"),
        os.path.join(ROOT_DIR, "_appdata", "project.fuxap.db"),
        os.path.join(ROOT_DIR, "server", "_appdata", "project.fuxap.db"),
    ]
    candidates.extend(glob.glob(os.path.join(ROOT_DIR, "locations", "**", "*.db"), recursive=True))

    for p in candidates:
        if is_valid_project_db(p) and count_views_in_db(p) > 0:
            return os.path.abspath(p)

    for p in candidates:
        if is_valid_project_db(p):
            return os.path.abspath(p)

    return None

def list_views(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM views;")
    rows = cur.fetchall()

    cur.execute("SELECT value FROM general WHERE name = 'layout';")
    layout_row = cur.fetchone()
    start_view_id = None
    if layout_row:
        try:
            start_view_id = json.loads(layout_row[0]).get("start")
        except Exception:
            pass

    views = []
    print("\n--- Current FUXA HMI Views ---")
    if not rows:
        print("  (No views found in database)")
        return views

    for r in rows:
        vid = r[0]
        try:
            val = json.loads(r[1])
            vname = val.get("name", "<unnamed>")
            vtype = val.get("type", "svg")
        except Exception:
            vname = "<corrupt>"
            vtype = "unknown"

        is_start = " [HOME / START VIEW]" if vid == start_view_id else ""
        print(f"  • ID: {vid} | Name: '{vname}' | Type: {vtype}{is_start}")
        views.append({"id": vid, "name": vname, "value": r[1]})

    print(f"Total Views: {len(views)}\n")
    return views

def dedup_views(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM views;")
    rows = cur.fetchall()

    seen_names = {}
    to_delete = []

    for r in rows:
        vid = r[0]
        try:
            val = json.loads(r[1])
            vname = val.get("name", vid)
        except Exception:
            vname = vid

        if vname in seen_names:
            to_delete.append((vid, vname))
        else:
            seen_names[vname] = vid

    if not to_delete:
        print("[✓] No duplicate view names found.")
        return

    print(f"[!] Found {len(to_delete)} duplicate view(s) to remove:")
    for vid, vname in to_delete:
        print(f"    - Deleting duplicate ID: '{vid}' (Name: '{vname}')")
        cur.execute("DELETE FROM views WHERE name = ?;", (vid,))

    # Ensure layout.start points to an existing view
    fix_layout_start(conn)
    conn.commit()
    print("[✓] Duplicates successfully removed and layout updated.")

def remove_view(conn, view_id):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM views WHERE name = ?;", (view_id,))
    row = cur.fetchone()
    if not row:
        print(f"[X] View ID '{view_id}' not found in database.")
        return False

    val = json.loads(row[1]) if row[1] else {}
    vname = val.get("name", view_id)
    cur.execute("DELETE FROM views WHERE name = ?;", (view_id,))
    fix_layout_start(conn)
    conn.commit()
    print(f"[✓] Successfully removed view '{vname}' (ID: {view_id}).")
    return True

def rename_view(conn, view_id, new_name):
    cur = conn.cursor()
    cur.execute("SELECT name, value FROM views WHERE name = ?;", (view_id,))
    row = cur.fetchone()
    if not row:
        print(f"[X] View ID '{view_id}' not found in database.")
        return False

    val = json.loads(row[1]) if row[1] else {}
    old_name = val.get("name", view_id)
    val["name"] = new_name
    cur.execute("UPDATE views SET value = ? WHERE name = ?;", (json.dumps(val), view_id))
    conn.commit()
    print(f"[✓] Successfully renamed view from '{old_name}' to '{new_name}' (ID: {view_id}).")
    return True

def fix_layout_start(conn):
    cur = conn.cursor()
    cur.execute("SELECT value FROM general WHERE name = 'layout';")
    layout_row = cur.fetchone()
    if not layout_row:
        return

    try:
        layout_data = json.loads(layout_row[0])
    except Exception:
        return

    cur.execute("SELECT name FROM views;")
    remaining_ids = [r[0] for r in cur.fetchall()]

    if layout_data.get("start") not in remaining_ids and remaining_ids:
        layout_data["start"] = remaining_ids[0]
        cur.execute("UPDATE general SET value = ? WHERE name = 'layout';", (json.dumps(layout_data),))
        print(f"[i] Updated project Start View to: '{remaining_ids[0]}'")

def main():
    parser = argparse.ArgumentParser(description="FUXA View Manager Utility")
    parser.add_argument("--db", type=str, help="Path to project.fuxap.db (optional, auto-detected if omitted)")
    parser.add_argument("--plant", type=int, help="Target plant storage server (e.g. 9 for Plant 9)")
    parser.add_argument("--port", type=int, help="Target server port (e.g. 5801, 9610)")
    parser.add_argument("--list", action="store_true", help="List all views in the database")
    parser.add_argument("--dedup", action="store_true", help="Automatically remove views that have duplicate names")
    parser.add_argument("--remove", type=str, help="Remove view by ID")
    parser.add_argument("--rename", nargs=2, metavar=("VIEW_ID", "NEW_NAME"), help="Rename view by ID to NEW_NAME")

    args = parser.parse_args()

    db_path = find_database(custom_path=args.db, plant=args.plant, port=args.port)
    if not db_path:
        print("[!] No project.fuxap.db found. Please specify path with --db <path_to_db> or target with --plant <id>")
        sys.exit(1)

    print(f"[i] Using database: {db_path}")

    # Create backup before any destructive operation
    if args.dedup or args.remove or args.rename:
        backup_database(db_path)

    conn = sqlite3.connect(db_path)

    try:
        if args.dedup:
            dedup_views(conn)
            list_views(conn)
        elif args.remove:
            remove_view(conn, args.remove)
            list_views(conn)
        elif args.rename:
            rename_view(conn, args.rename[0], args.rename[1])
            list_views(conn)
        else:
            list_views(conn)
    finally:
        conn.close()

    if args.dedup or args.remove or args.rename:
        print("\n[📢] Views updated. If FUXA is running, reload or restart PM2 to apply changes:")
        if args.plant:
            print(f"     pm2 restart P{args.plant}_Storage_Server")
        else:
            print("     pm2 restart P9_Storage_Server  # (or your target instance)")

if __name__ == "__main__":
    main()
