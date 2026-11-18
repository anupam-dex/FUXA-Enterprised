#!/usr/bin/env python3
"""
==============================================================================
FUXA Enterprise SCADA - Bulk Historical Tagging (DAQ) Tool
==============================================================================
Enables or disables historical data acquisition (DAQ) in bulk across all
tags of a target Central Storage Server or View Server.

Key Features:
1. Bulk Enable/Disable: Toggle DAQ for all tags across all devices or a single PLC.
2. Smart Modes:
   - "change" (Default & SCADA Recommended): Logs only when tag values change.
     Saves up to 90% disk space and network bandwidth.
   - "interval": Logs at a fixed periodic interval (e.g. 5s, 10s, 60s).
   - "both": Logs on change AND at periodic intervals.
3. Safe & Atomic: Uses SQLite WAL transactions, 5-second busy timeout, and creates
   an automatic timestamped backup (.bak_<timestamp>) before modifying.
4. Non-Blocking: Does not freeze the server event loop.
==============================================================================
"""

import sys
import os
import re
import json
import time
import shutil
import sqlite3
import argparse
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INSTANCES_DIR = os.path.join(BASE_DIR, "instances")
FLEET_MANAGER_URL = os.environ.get("FLEET_MANAGER_URL", "http://localhost:9000")


def resolve_db_path(plant_id: int = 9, instance_id: str = None) -> tuple[str, str, int]:
    """Resolves target database path and port from plant or instance ID"""
    storage_port = 5000 + plant_id * 100 if plant_id != 9 else 5900
    canonical_dir = os.path.join(INSTANCES_DIR, f"storage_plant_{plant_id}_{storage_port}")

    if instance_id:
        target_dir = os.path.join(INSTANCES_DIR, instance_id)
        db_path = os.path.join(target_dir, "project.fuxap.db")
        if os.path.exists(db_path):
            return db_path, target_dir, storage_port

    # 1. Check canonical directory first
    if os.path.exists(canonical_dir):
        db_path = os.path.join(canonical_dir, "project.fuxap.db")
        appdata_db = os.path.join(canonical_dir, "_appdata", "project.fuxap.db")
        if os.path.exists(appdata_db) or os.path.exists(db_path):
            return db_path, canonical_dir, storage_port

    # 2. Check registry.json
    reg_paths = [
        os.path.join(INSTANCES_DIR, "registry.json"),
        os.path.join(BASE_DIR, "manager", "registry.json")
    ]
    for reg_path in reg_paths:
        if os.path.exists(reg_path):
            try:
                with open(reg_path, "r") as f:
                    data = json.load(f)
                    for iid, inst in data.get("instances", {}).items():
                        if inst.get("role") == "storage" and int(inst.get("plant_id", 0)) == plant_id:
                            target_dir = os.path.join(INSTANCES_DIR, iid)
                            db_path = os.path.join(target_dir, "project.fuxap.db")
                            return db_path, target_dir, int(inst.get("port", storage_port))
            except Exception:
                pass

    # 3. Heuristic scan of instances/ directory
    if os.path.exists(INSTANCES_DIR):
        for entry in os.listdir(INSTANCES_DIR):
            if f"storage_plant_{plant_id}" in entry or f"storage_{plant_id}" in entry or f"p{plant_id}" in entry:
                cand_dir = os.path.join(INSTANCES_DIR, entry)
                cand_db = os.path.join(cand_dir, "project.fuxap.db")
                cand_appdata = os.path.join(cand_dir, "_appdata", "project.fuxap.db")
                if os.path.exists(cand_db) or os.path.exists(cand_appdata):
                    return cand_db, cand_dir, storage_port

    # 4. Default fallback
    return os.path.join(canonical_dir, "project.fuxap.db"), canonical_dir, storage_port


def configure_bulk_history(
    plant_id: int = 9,
    instance_id: str = None,
    enabled: bool = True,
    mode: str = "change",
    interval: int = 60,
    device_filter: str = None,
    dry_run: bool = False,
    create_backup: bool = True,
    restart_instance: bool = False
) -> dict:
    """
    Applies bulk historical DAQ settings to tags in both root and _appdata SQLite databases.
    """
    primary_db, work_dir, port = resolve_db_path(plant_id, instance_id)

    appdata_dir = os.path.join(work_dir, "_appdata")
    os.makedirs(appdata_dir, exist_ok=True)
    root_db = os.path.join(work_dir, "project.fuxap.db")
    appdata_db = os.path.join(appdata_dir, "project.fuxap.db")

    # Reconcile if one exists and the other doesn't
    if not os.path.exists(root_db) and os.path.exists(appdata_db):
        shutil.copy2(appdata_db, root_db)
    elif os.path.exists(root_db) and not os.path.exists(appdata_db):
        shutil.copy2(root_db, appdata_db)

    target_dbs = [p for p in [root_db, appdata_db] if os.path.exists(p)]

    if not target_dbs:
        return {
            "success": False,
            "error": f"Database not found at '{root_db}'. Ensure the storage instance exists.",
            "plant_id": plant_id
        }

    # Backup before write
    backup_path = None
    if create_backup and not dry_run:
        for p in target_dbs:
            bak = f"{p}.bak_{int(time.time())}"
            shutil.copy2(p, bak)
            if not backup_path:
                backup_path = bak

    mode_norm = (mode or "change").lower()
    on_change = mode_norm in ("change", "both")
    fix_interval = interval if mode_norm in ("interval", "both") else 0

    updated_devices = []
    total_tags_updated = 0
    total_devices_affected = 0

    for db_path in target_dbs:
        conn = sqlite3.connect(db_path, timeout=10.0)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA busy_timeout = 5000;")

        cur.execute("SELECT name, value FROM devices;")
        rows = cur.fetchall()

        curr_tags_updated = 0
        curr_devs_affected = 0

        for d_name, d_val in rows:
            if d_name in ("server", "0"):
                continue

            try:
                dev = json.loads(d_val)
            except Exception:
                continue

            dev_name = dev.get("name") or d_name
            dev_id = dev.get("id") or d_name

            # Apply device filter if specified
            if device_filter:
                filt_norm = device_filter.lower().strip()
                if filt_norm not in dev_name.lower() and filt_norm != dev_id.lower():
                    continue

            tags = dev.get("tags") or {}
            if not tags or not isinstance(tags, dict):
                continue

            dev_tag_count = 0
            for t_id, tag in tags.items():
                if not isinstance(tag, dict):
                    continue

                tag["daq"] = {
                    "enabled": bool(enabled),
                    "changed": bool(on_change),
                    "interval": int(fix_interval),
                    "restored": False
                }
                dev_tag_count += 1

            if dev_tag_count > 0:
                curr_devs_affected += 1
                curr_tags_updated += dev_tag_count
                if not updated_devices or not any(d["device_id"] == dev_id for d in updated_devices):
                    updated_devices.append({
                        "device_id": dev_id,
                        "device_name": dev_name,
                        "tags_configured": dev_tag_count
                    })

                if not dry_run:
                    new_json = json.dumps(dev)
                    cur.execute("UPDATE devices SET value = ? WHERE name = ?;", (new_json, d_name))

        if not dry_run:
            conn.commit()
            try:
                cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass

        conn.close()

        # Clean lock files
        if not dry_run:
            for suf in ["-wal", "-shm"]:
                lf = db_path + suf
                if os.path.exists(lf):
                    try:
                        os.remove(lf)
                    except Exception:
                        pass

        total_tags_updated = max(total_tags_updated, curr_tags_updated)
        total_devices_affected = max(total_devices_affected, curr_devs_affected)

    result = {
        "success": True,
        "dry_run": dry_run,
        "plant_id": plant_id,
        "instance_id": instance_id or os.path.basename(work_dir),
        "db_path": root_db,
        "backup_path": backup_path,
        "enabled": enabled,
        "mode": mode_norm,
        "interval_seconds": fix_interval,
        "total_devices_affected": total_devices_affected,
        "total_tags_updated": total_tags_updated,
        "devices": updated_devices
    }

    if restart_instance and not dry_run:
        _trigger_restart(plant_id, instance_id)

    return result


def _trigger_restart(plant_id: int, instance_id: str = None):
    """Signals Fleet Manager to restart the target storage instance cleanly"""
    try:
        url = f"{FLEET_MANAGER_URL.rstrip('/')}/api/storage/{plant_id}/restart"
        req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            pass
    except Exception:
        try:
            import sys
            mgr_dir = os.path.join(BASE_DIR, "manager")
            if mgr_dir not in sys.path:
                sys.path.insert(0, mgr_dir)
            from server import restart_storage_master
            restart_storage_master(plant_id)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="FUXA Bulk Historical Tagging (DAQ) Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--plant", type=int, default=9, help="Target Plant ID (default: 9)")
    parser.add_argument("--instance", type=str, default=None, help="Specific instance ID (e.g. storage_plant_9)")
    parser.add_argument("--enable", dest="enabled", action="store_true", default=True, help="Enable historical logging (default)")
    parser.add_argument("--disable", dest="enabled", action="store_false", help="Disable historical logging")
    parser.add_argument("--mode", choices=["change", "interval", "both"], default="change",
                        help="Logging mode: 'change' (value changes only), 'interval' (periodic), or 'both'")
    parser.add_argument("--interval", type=int, default=60, help="Periodic interval in seconds (default: 60)")
    parser.add_argument("--device", type=str, default=None, help="Filter to a specific device by name or ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate changes without saving to disk")
    parser.add_argument("--no-backup", action="store_true", help="Skip creating automatic backup")
    parser.add_argument("--restart", action="store_true", help="Restart storage instance to apply immediately")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print(" 📈 FUXA Bulk Historical Tagging (DAQ)")
    print("=" * 70)
    print(f" Plant ID         : {args.plant}")
    print(f" Historical State : {'ENABLED' if args.enabled else 'DISABLED'}")
    print(f" Logging Mode     : {args.mode.upper()}")
    if args.mode in ("interval", "both"):
        print(f" Periodic Interval: {args.interval} seconds")
    if args.device:
        print(f" Device Filter    : {args.device}")
    print(f" Dry Run          : {args.dry_run}")
    print("=" * 70)

    res = configure_bulk_history(
        plant_id=args.plant,
        instance_id=args.instance,
        enabled=args.enabled,
        mode=args.mode,
        interval=args.interval,
        device_filter=args.device,
        dry_run=args.dry_run,
        create_backup=not args.no_backup,
        restart_instance=args.restart
    )

    if not res.get("success"):
        print(f"\n❌ Error: {res.get('error')}")
        sys.exit(1)

    print(f"\n✅ Historical DAQ configured successfully!")
    print(f"   Devices Affected : {res['total_devices_affected']}")
    print(f"   Total Tags Saved : {res['total_tags_updated']}")
    if res.get("backup_path"):
        print(f"   Backup Created   : {res['backup_path']}")

    print("\nDevice Breakdown:")
    for dev in res.get("devices", []):
        print(f"  • {dev['device_name']} ({dev['device_id']}): {dev['tags_configured']} tags updated")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
