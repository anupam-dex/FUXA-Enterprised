#!/usr/bin/env python3
"""
FUXA Enterprise Fleet Registry & Project Database Keeper
Maintains a persistent record of all server names, port numbers, PM2 processes,
live statuses, and automatically protects/backs up project files (_app.db) and settings.

Usage:
  python3 scripts/sync_registry.py
  python3 scripts/sync_registry.py --backup
  python3 scripts/sync_registry.py --restore-plant9
"""

import os
import sys
import glob
import json
import shutil
import datetime
import argparse
import subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_ROOT_PATH = os.path.join(ROOT_DIR, "fuxa-fleet-registry.json")
REGISTRY_MANAGER_PATH = os.path.join(ROOT_DIR, "fuxa-fleet-manager", "manager", "registry.json")
BACKUP_DIR = os.path.join(ROOT_DIR, "locations", "backups")
STORAGE_DIR = os.path.join(ROOT_DIR, "locations", "storage")
VIEWS_DIR = os.path.join(ROOT_DIR, "locations", "views")

DEFAULT_PLANTS = {
    "1": {"name": "Plant 1 - Foundry & Powerhouse", "storage_port": 5100, "storage_pm2_name": "P1_Storage_Server"},
    "2": {"name": "Plant 2 - Stamping & Press", "storage_port": 5200, "storage_pm2_name": "P2_Storage_Server"},
    "3": {"name": "Plant 3 - Body & Assembly", "storage_port": 5300, "storage_pm2_name": "P3_Storage_Server"},
    "4": {"name": "Plant 4 - Powertrain & Engine", "storage_port": 5400, "storage_pm2_name": "P4_Storage_Server"},
    "9": {"name": "Plant 9 - Paintshop Complex", "storage_port": 5810, "storage_pm2_name": "P9_Storage_Server"}
}

def get_pm2_processes():
    pm2_bin = shutil.which("pm2")
    if not pm2_bin:
        return {}
    try:
        res = subprocess.run([pm2_bin, "jlist"], capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            procs = json.loads(res.stdout)
            result = {}
            for p in procs:
                name = p.get("name")
                if name:
                    result[name] = p
            return result
    except Exception as e:
        print(f"[!] Warning: error querying PM2: {e}")
    return {}

def extract_port_from_pm2(proc):
    pm2_env = proc.get("pm2_env", {})
    args = pm2_env.get("args", [])
    if isinstance(args, str):
        args = args.split()
    for idx, a in enumerate(args):
        if a in ["-p", "--port"] and idx + 1 < len(args):
            return int(args[idx + 1])
        if str(a).startswith("-p="):
            return int(str(a).split("=")[1])
        if str(a).startswith("--port="):
            return int(str(a).split("=")[1])
    return None

def backup_file(src_path, label=""):
    if not os.path.exists(src_path) or os.path.getsize(src_path) == 0:
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_label = label.replace(" ", "_").replace("/", "_") if label else "db"
    dest_name = f"{clean_label}_{ts}.db"
    dest_path = os.path.join(BACKUP_DIR, dest_name)
    shutil.copy2(src_path, dest_path)
    return dest_path

def find_legacy_database():
    """Look for any existing _app.db from previous runs."""
    candidates = [
        os.path.join(ROOT_DIR, "_appdata", "_app.db"),
        os.path.join(ROOT_DIR, "server", "_appdata", "_app.db"),
        os.path.join(STORAGE_DIR, "_appdata", "_app.db"),
        os.path.join(STORAGE_DIR, "plant_9", "_appdata", "_app.db"),
    ]
    # Check backups as well
    if os.path.exists(BACKUP_DIR):
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.db")), key=os.path.getmtime, reverse=True)
        candidates.extend(backups)

    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 0:
            return c
    return None

def ensure_plant9_database():
    """Ensures Plant 9 has its project database restored if missing."""
    p9_dir = os.path.join(STORAGE_DIR, "plant_9", "_appdata")
    p9_db = os.path.join(p9_dir, "_app.db")
    os.makedirs(p9_dir, exist_ok=True)

    if not os.path.exists(p9_db) or os.path.getsize(p9_db) == 0:
        legacy = find_legacy_database()
        if legacy and legacy != p9_db:
            print(f"[i] Restoring existing project database from: {legacy} -> {p9_db}")
            shutil.copy2(legacy, p9_db)
            return True
    return False

def sync():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(STORAGE_DIR, exist_ok=True)
    os.makedirs(VIEWS_DIR, exist_ok=True)

    # Ensure Plant 9 database exists
    ensure_plant9_database()

    # Load existing registry if available
    registry_data = {}
    if os.path.exists(REGISTRY_ROOT_PATH):
        try:
            with open(REGISTRY_ROOT_PATH, "r", encoding="utf-8") as f:
                registry_data = json.load(f)
        except Exception:
            registry_data = {}

    manager_data = {}
    if os.path.exists(REGISTRY_MANAGER_PATH):
        try:
            with open(REGISTRY_MANAGER_PATH, "r", encoding="utf-8") as f:
                manager_data = json.load(f)
        except Exception:
            manager_data = {}

    pm2_procs = get_pm2_processes()

    # Build Storage Servers section
    plants = manager_data.get("plants", DEFAULT_PLANTS)
    storage_servers = {}
    for p_id, p_info in plants.items():
        pm2_name = p_info.get("storage_pm2_name", f"P{p_id}_Storage_Server")
        port = p_info.get("storage_port", 5000 + int(p_id) * 100)
        work_dir = f"locations/storage/plant_{p_id}"
        abs_work_dir = os.path.join(ROOT_DIR, "locations", "storage", f"plant_{p_id}")
        os.makedirs(abs_work_dir, exist_ok=True)
        db_path = f"{work_dir}/_appdata/_app.db"
        abs_db_path = os.path.join(ROOT_DIR, "locations", "storage", f"plant_{p_id}", "_appdata", "_app.db")

        proc = pm2_procs.get(pm2_name) or pm2_procs.get(f"P{p_id}_FUXA_Enterprise")
        status = "NOT_REGISTERED"
        uptime = 0
        memory_mb = 0.0

        if proc:
            pm2_env = proc.get("pm2_env", {})
            status = pm2_env.get("status", "unknown").upper()
            uptime = pm2_env.get("pm_uptime", 0)
            monit = proc.get("monit", {})
            memory_mb = round(monit.get("memory", 0) / (1024 * 1024), 1)

            # Auto backup active db
            if os.path.exists(abs_db_path) and os.path.getsize(abs_db_path) > 0:
                backup_file(abs_db_path, f"plant_{p_id}_storage")

        storage_servers[str(p_id)] = {
            "plant_id": int(p_id),
            "name": p_info.get("name", f"Plant {p_id}"),
            "port": port,
            "pm2_name": pm2_name,
            "role": "storage",
            "work_dir": work_dir,
            "database_path": db_path,
            "database_exists": os.path.exists(abs_db_path),
            "status": status,
            "uptime": uptime,
            "memory_mb": memory_mb
        }

    # Build View Servers section
    view_servers = {}
    manager_instances = manager_data.get("instances", {})

    # Also scan PM2 for any fuxa view server instances
    for p_name, proc in pm2_procs.items():
        if p_name.startswith("fuxa_") or "line" in p_name.lower():
            port = extract_port_from_pm2(proc)
            if port and str(port) not in [str(inst.get("port")) for inst in manager_instances.values()]:
                # Discovered from PM2
                inst_id = p_name
                manager_instances[inst_id] = {
                    "instance_id": inst_id,
                    "title": p_name.replace("_", " ").title(),
                    "port": port,
                    "pm2_name": p_name,
                    "work_dir": os.path.join("locations", "views", p_name),
                    "status": proc.get("pm2_env", {}).get("status", "unknown").upper()
                }

    # Scan views folder
    if os.path.exists(VIEWS_DIR):
        for entry in os.listdir(VIEWS_DIR):
            full = os.path.join(VIEWS_DIR, entry)
            if os.path.isdir(full) and entry not in manager_instances:
                db_candidate = os.path.join(full, "_appdata", "_app.db")
                if os.path.exists(db_candidate):
                    # extract port from folder name if possible
                    parts = entry.split("_")
                    port = int(parts[-1]) if parts and parts[-1].isdigit() else 9000
                    manager_instances[entry] = {
                        "instance_id": entry,
                        "title": entry.replace("_", " ").title(),
                        "port": port,
                        "pm2_name": entry,
                        "work_dir": os.path.join("locations", "views", entry),
                        "status": "STOPPED"
                    }

    for inst_id, inst in manager_instances.items():
        pm2_name = inst.get("pm2_name", inst_id)
        proc = pm2_procs.get(pm2_name)
        status = inst.get("status", "STOPPED")
        uptime = 0
        memory_mb = 0.0

        if proc:
            pm2_env = proc.get("pm2_env", {})
            status = pm2_env.get("status", "unknown").upper()
            uptime = pm2_env.get("pm_uptime", 0)
            monit = proc.get("monit", {})
            memory_mb = round(monit.get("memory", 0) / (1024 * 1024), 1)

        work_dir = f"locations/views/{inst_id}"
        abs_work_dir = os.path.join(ROOT_DIR, "locations", "views", inst_id)
        db_path = f"{work_dir}/_appdata/_app.db"
        abs_db_path = os.path.join(ROOT_DIR, "locations", "views", inst_id, "_appdata", "_app.db")

        # Auto backup active db
        if os.path.exists(abs_db_path) and os.path.getsize(abs_db_path) > 0:
            backup_file(abs_db_path, f"view_{inst.get('port', 'port')}")

        view_servers[inst_id] = {
            "instance_id": inst_id,
            "title": inst.get("title", inst_id),
            "plant_id": inst.get("plant_id", 9),
            "division": inst.get("division", 6),
            "line": inst.get("line", 1),
            "port": inst.get("port"),
            "pm2_name": pm2_name,
            "role": "view",
            "work_dir": work_dir,
            "database_path": db_path,
            "database_exists": os.path.exists(abs_db_path),
            "status": status,
            "uptime": uptime,
            "memory_mb": memory_mb
        }

    # Fleet Manager Status
    mgr_proc = pm2_procs.get("FUXA_Enterprise_Manager")
    mgr_status = mgr_proc.get("pm2_env", {}).get("status", "ONLINE").upper() if mgr_proc else "STANDALONE"

    # Assemble master JSON
    master_registry = {
        "title": "FUXA Enterprise Fleet Master Registry",
        "last_updated": datetime.datetime.now().isoformat(),
        "fleet_manager": {
            "name": "FUXA_Enterprise_Manager",
            "port": 9000,
            "status": mgr_status,
            "url": "http://localhost:9000"
        },
        "storage_servers": storage_servers,
        "view_servers": view_servers,
        "backups": {
            "backup_dir": "locations/backups",
            "total_backups": len(glob.glob(os.path.join(BACKUP_DIR, "*.db"))),
            "latest_backups": sorted([os.path.basename(f) for f in glob.glob(os.path.join(BACKUP_DIR, "*.db"))], reverse=True)[:5]
        }
    }

    # Write root registry
    with open(REGISTRY_ROOT_PATH, "w", encoding="utf-8") as f:
        json.dump(master_registry, f, indent=2)

    # Sync back to manager registry
    manager_data["plants"] = plants
    manager_data["instances"] = manager_instances
    with open(REGISTRY_MANAGER_PATH, "w", encoding="utf-8") as f:
        json.dump(manager_data, f, indent=2)

    print("=" * 80)
    print(" 🚀 FUXA Enterprise Fleet Master Registry (fuxa-fleet-registry.json)")
    print(f"    Updated: {master_registry['last_updated']}")
    print("=" * 80)
    print("\n📦 STORAGE SERVERS:")
    print("-" * 80)
    print(f"{'Plant':<8} {'Port':<8} {'PM2 Name':<22} {'Status':<12} {'Database File'}")
    print("-" * 80)
    for p_id, s in storage_servers.items():
        icon = "🟢" if s["status"] == "ONLINE" else ("🔴" if s["status"] in ["ERRORED", "STOPPED"] else "⚪")
        db_icon = "💾" if s["database_exists"] else "⚠️ MISSING"
        print(f"Plant {p_id:<2} :{s['port']:<6} {s['pm2_name']:<22} {icon} {s['status']:<9} {db_icon} {s['database_path']}")

    print("\n🖥️ VIEW SERVERS:")
    print("-" * 80)
    if not view_servers:
        print("  (No view servers provisioned yet)")
    else:
        print(f"{'Instance':<24} {'Port':<8} {'PM2 Name':<22} {'Status':<12} {'Database File'}")
        print("-" * 80)
        for i_id, v in view_servers.items():
            icon = "🟢" if v["status"] == "ONLINE" else ("🔴" if v["status"] in ["ERRORED", "STOPPED"] else "⚪")
            db_icon = "💾" if v["database_exists"] else "⚠️ MISSING"
            print(f"{i_id:<24} :{v['port']:<6} {v['pm2_name']:<22} {icon} {v['status']:<9} {db_icon} {v['database_path']}")

    print("\n" + "=" * 80)
    print(f"🛡️ Backups directory: {BACKUP_DIR} ({master_registry['backups']['total_backups']} total backups saved)")
    print(f"📄 Persistent Registry: {REGISTRY_ROOT_PATH}")
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(description="FUXA Registry & Project Keeper")
    parser.add_argument("--backup", action="store_true", help="Force create backups of all existing databases")
    parser.add_argument("--restore-plant9", action="store_true", help="Force restore Plant 9 database from legacy location")
    args = parser.parse_args()

    if args.restore_plant9:
        legacy = find_legacy_database()
        if legacy:
            dest = os.path.join(STORAGE_DIR, "plant_9", "_appdata", "_app.db")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(legacy, dest)
            print(f"[✓] Restored Plant 9 database from {legacy} -> {dest}")
        else:
            print("[X] No legacy database found to restore.")

    sync()

if __name__ == "__main__":
    main()
