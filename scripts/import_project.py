#!/usr/bin/env python3
"""
FUXA Enterprise Project Import CLI
Imports a FUXA project.json / .fuxap export file into a Storage Server or View Server database.
Features:
- Automated pre-import backup to locations/backups/
- Zero-driver OPC-UA bridge preservation for View Servers
- Instant live reload via PM2
- Support for UTF-8 and UTF-8-BOM encoded project files

Usage:
  # 1. Inspect project file structure (devices, tags, views)
  python3 scripts/import_project.py --file project.json --inspect

  # 2. Import into Plant 9 Master Storage Server (with PM2 restart)
  python3 scripts/import_project.py --file project.json --plant 9

  # 3. Import into View Server on Port 9610 (preserves OPC-UA storage bridge)
  python3 scripts/import_project.py --file project.json --view 9610

  # 4. List all target servers in the fleet
  python3 scripts/import_project.py --list
"""

import os
import sys
import json
import shutil
import sqlite3
import argparse
import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT_DIR, "fuxa-fleet-manager", "manager"))

try:
    from project_builder import inspect_project_data, import_project_to_database
    from pm2_adapter import PM2Adapter
    from port_engine import PortEngine
except ImportError:
    print("[!] Warning: Could not import fleet manager modules directly. Using local fallback.")
    inspect_project_data = None
    import_project_to_database = None

REGISTRY_PATH = os.path.join(ROOT_DIR, "fuxa-fleet-manager", "manager", "registry.json")
BACKUPS_DIR = os.path.join(ROOT_DIR, "locations", "backups")

def load_project_file(file_path):
    """Loads JSON / .fuxap file with UTF-8 / UTF-8-BOM support."""
    if not os.path.exists(file_path):
        print(f"[X] Error: File '{file_path}' does not exist.")
        sys.exit(1)

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        print(f"[X] Error reading '{file_path}': {e}")
        sys.exit(1)

def list_targets():
    """Prints all configured Storage and View servers."""
    print("\n=== Available FUXA Fleet Targets ===")
    
    # 1. Plants (Storage)
    print("\n🏭 Master Storage Servers:")
    storage_dir = os.path.join(ROOT_DIR, "locations", "storage")
    if os.path.exists(storage_dir):
        for item in sorted(os.listdir(storage_dir)):
            if item.startswith("plant_"):
                p_id = item.replace("plant_", "")
                p_dir = os.path.join(storage_dir, item)
                db_p = os.path.join(p_dir, "_appdata", "project.fuxap.db")
                exists = " [DB EXISTS]" if os.path.exists(db_p) else " [NO DB]"
                print(f"  • Plant {p_id} (--plant {p_id}) -> {p_dir}{exists}")

    # 2. View Servers
    print("\n🖥️ HMI View Servers:")
    views_dir = os.path.join(ROOT_DIR, "locations", "views")
    if os.path.exists(views_dir):
        for item in sorted(os.listdir(views_dir)):
            v_dir = os.path.join(views_dir, item)
            if os.path.isdir(v_dir):
                db_v = os.path.join(v_dir, "_appdata", "project.fuxap.db")
                exists = " [DB EXISTS]" if os.path.exists(db_v) else " [NO DB]"
                print(f"  • Instance {item} (--view {item}) -> {v_dir}{exists}")
    print("")

def main():
    parser = argparse.ArgumentParser(description="FUXA Enterprise Project Import Utility")
    parser.add_argument("--file", type=str, help="Path to project.json or project.fuxap export")
    parser.add_argument("--plant", type=int, help="Target Plant Storage Server (e.g. 9 for Plant 9)")
    parser.add_argument("--view", type=str, help="Target View Server instance ID or port (e.g. 9610 or fuxa_port_9610)")
    parser.add_argument("--db", type=str, help="Direct path to target SQLite project.fuxap.db file")
    parser.add_argument("--preserve-bridge", dest="preserve_bridge", action="store_true", default=True,
                        help="Preserve zero-driver OPC-UA bridge for view servers (default: True)")
    parser.add_argument("--no-preserve-bridge", dest="preserve_bridge", action="store_false",
                        help="Import all PLC devices directly into view server")
    parser.add_argument("--no-restart", action="store_true", help="Skip PM2 instance restart after import")
    parser.add_argument("--inspect", action="store_true", help="Inspect and display project file details without importing")
    parser.add_argument("--list", action="store_true", help="List all available storage and view server targets")

    args = parser.parse_args()

    if args.list:
        list_targets()
        return

    if not args.file:
        print("[!] Error: Please specify a project file with --file <path_to_file> (or use --list)")
        sys.exit(1)

    project_data = load_project_file(args.file)

    # Inspect mode
    if args.inspect:
        print(f"\n=== Project File Inspection: {args.file} ===")
        if inspect_project_data:
            summary = inspect_project_data(project_data)
            print(f"  • Project Name: {summary.get('title')}")
            print(f"  • Schema Version: {summary.get('version')}")
            print(f"  • Devices: {summary.get('devices_count')} {summary.get('device_names')[:6]}")
            print(f"  • Total Tags: {summary.get('tags_count')}")
            print(f"  • HMI Views: {summary.get('views_count')} {summary.get('view_names')[:6]}")
            print(f"  • Alarms: {summary.get('alarms_count')} | Scripts: {summary.get('scripts_count')}")
        else:
            dev_cnt = len(project_data.get("devices", {}))
            views_cnt = len(project_data.get("hmi", {}).get("views", []))
            print(f"  • Devices: {dev_cnt} | Views: {views_cnt}")
        print("")
        return

    # Determine Target Directory & Role
    target_work_dir = None
    role = "storage"
    plant_id = 9
    pm2_name = None

    if args.db:
        # User specified direct db path
        target_work_dir = os.path.dirname(os.path.dirname(os.path.abspath(args.db)))
        role = "storage"
    elif args.plant is not None:
        role = "storage"
        plant_id = args.plant
        target_work_dir = os.path.join(ROOT_DIR, "locations", "storage", f"plant_{plant_id}")
        pm2_name = f"P{plant_id}_Storage_Server"
    elif args.view is not None:
        role = "view"
        v_str = str(args.view)
        # Check if v_str is port or instance name
        if v_str.isdigit():
            v_id = f"fuxa_port_{v_str}"
            plant_id = int(v_str[0]) if len(v_str) >= 4 else 9
        else:
            v_id = v_str
            # Extract port if fuxa_port_XXXX
            if "port_" in v_id:
                try:
                    p_num = v_id.split("port_")[1]
                    plant_id = int(p_num[0]) if len(p_num) >= 4 else 9
                except Exception:
                    plant_id = 9
            else:
                plant_id = 9
        target_work_dir = os.path.join(ROOT_DIR, "locations", "views", v_id)
        pm2_name = v_id
    else:
        print("[!] Error: Please specify a target with --plant <id> or --view <port/id> (or use --list)")
        sys.exit(1)

    print(f"\n[i] Target Role: {role.upper()}")
    print(f"[i] Target Directory: {target_work_dir}")
    if role == "storage":
        print(f"[i] Policy: DEVICES ONLY (All HMI views, screens & graphics are strictly skipped)")
        print(f"[i] Deduplication: STRICT (Resolves duplicate names & IDs automatically)")
    elif role == "view":
        print(f"[i] Policy: HMI VIEWS & SCREENS")
        print(f"[i] Bridge Mode: {'YES (opc.tcp://127.0.0.1:4840)' if args.preserve_bridge else 'NO (Direct PLCs)'}")

    # Perform Import
    os.makedirs(target_work_dir, exist_ok=True)
    res = import_project_to_database(
        target_work_dir=target_work_dir,
        project_data=project_data,
        role=role,
        plant_id=plant_id,
        preserve_bridge=args.preserve_bridge,
        backup_dir=BACKUPS_DIR
    )

    if res.get("backup_path"):
        print(f"[🛡️] Created pre-import backup: {res['backup_path']}")

    print(f"[✓] Successfully imported project into {role.upper()} database:")
    print(f"    • Database: {res['db_path']}")
    print(f"    • Unique Devices: {res['devices_count']} {res.get('device_names', [])[:6]}")
    if res.get("skipped_duplicates"):
        print(f"    • 🛡️ Skipped Duplicate Devices ({len(res['skipped_duplicates'])}):")
        for dup in res["skipped_duplicates"]:
            print(f"        - {dup}")
    if role == "storage":
        print(f"    • HMI Screens: SKIPPED ({res.get('skipped_views_count', 0)} screens omitted from Storage Server)")
    else:
        print(f"    • Views Imported: {res['views_count']} {res.get('view_names', [])[:6]}")
    if res.get("tags_count"):
        print(f"    • Total Tags: {res['tags_count']}")

    # PM2 Reload
    if not args.no_restart and pm2_name:
        try:
            pm2 = PM2Adapter()
            if pm2.is_available():
                status = pm2.get_process_status(pm2_name)
                if status.get("exists") and status.get("status") == "online":
                    re_res = pm2.restart_instance(pm2_name)
                    if re_res.get("success"):
                        print(f"[📢] PM2 process '{pm2_name}' reloaded live successfully!")
                    else:
                        print(f"[!] Warning: PM2 restart returned: {re_res}")
                else:
                    print(f"[i] PM2 process '{pm2_name}' is not currently online. Start it via Fleet Manager or PM2.")
        except Exception as e:
            print(f"[!] PM2 reload check skipped: {e}")

    print("\n[🎉] Done!\n")

if __name__ == "__main__":
    main()
