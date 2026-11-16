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
import sqlite3
import argparse

def find_database(custom_path=None):
    if custom_path and os.path.exists(custom_path):
        return custom_path

    # Candidate locations in order of priority
    candidates = [
        os.path.join(os.getcwd(), "_appdata", "project.fuxap.db"),
        os.path.join(os.getcwd(), "server", "_appdata", "project.fuxap.db"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "_appdata", "project.fuxap.db"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "server", "_appdata", "project.fuxap.db"),
    ]
    # Check locations/ storage or views
    loc_pattern = os.path.join(os.getcwd(), "locations", "**", "project.fuxap.db")
    candidates.extend(glob.glob(loc_pattern, recursive=True))

    for p in candidates:
        if os.path.exists(p):
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
    parser.add_argument("--list", action="store_true", help="List all views in the database")
    parser.add_argument("--dedup", action="store_true", help="Automatically remove views that have duplicate names")
    parser.add_argument("--remove", type=str, help="Remove view by ID")
    parser.add_argument("--rename", nargs=2, metavar=("VIEW_ID", "NEW_NAME"), help="Rename view by ID to NEW_NAME")

    args = parser.parse_args()

    db_path = find_database(args.db)
    if not db_path:
        print("[!] No project.fuxap.db found. Please specify path with --db <path_to_db>")
        sys.exit(1)

    print(f"[i] Using database: {db_path}")
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

if __name__ == "__main__":
    main()
