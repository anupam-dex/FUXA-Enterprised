#!/usr/bin/env python3
"""
==============================================================================
FUXA Enterprise SCADA - Dedicated Device Importer & Deduplication Engine
==============================================================================
Imports ONLY physical devices and tags from one or multiple legacy FUXA
project.json / .fuxap files into the Central Storage Server database.

Key Principles:
1. Devices & Tags ONLY: Ignores views, SVGs, widgets, scripts, reports, layouts.
2. Hardware-level Deduplication: Detects duplicate devices across multiple files
   by matching connection signatures (IP + Port + SlaveId/Rack/Slot/Endpoint)
   and normalized device names.
3. Smart Tag Union: When duplicate devices are detected across files, merges their
   tags into a single canonical device without duplicating tag entries.
4. Non-Destructive: Preserves existing Storage Server devices and creates a
   timestamped SQLite backup (.bak_<timestamp>) before applying any changes.
5. Dry-Run & Audit: Allows full simulation and prints an audit report of all
   duplicates and newly imported tags before committing.
==============================================================================
"""

import sys
import os
import re
import json
import time
import glob
import shutil
import sqlite3
import argparse
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INSTANCES_DIR = os.path.join(BASE_DIR, "instances")
FLEET_MANAGER_URL = os.environ.get("FLEET_MANAGER_URL", "http://localhost:9000")


def normalize_string(val: str) -> str:
    """Normalizes a string for robust matching (lowercase, alphanumeric only)"""
    if not val:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(val).lower().strip())


def compute_device_signature(dev: dict) -> str:
    """
    Computes a deterministic physical hardware signature for a device.
    Two devices with the same signature correspond to the same physical hardware.
    """
    dev_type = (dev.get("type") or "unknown").lower()
    props = dev.get("property") or {}

    if dev_type == "modbus":
        host = (props.get("address") or props.get("host") or "").strip().lower()
        port = str(props.get("port") or 502)
        slave = str(props.get("slaveId") or props.get("unitId") or props.get("slaveid") or 1)
        return f"modbus://{host}:{port}?slave={slave}"

    elif dev_type in ("siemenss7", "s7"):
        host = (props.get("address") or props.get("host") or "").strip().lower()
        port = str(props.get("port") or 102)
        rack = str(props.get("rack") or 0)
        slot = str(props.get("slot") or 1)
        return f"s7://{host}:{port}?rack={rack}&slot={slot}"

    elif dev_type in ("opcua", "opc-ua"):
        url = (props.get("address") or props.get("endpoint") or props.get("url") or "").strip().lower()
        url = re.sub(r"/+$", "", url)
        return f"opcua://{url}"

    elif dev_type in ("ethernetip", "enip"):
        host = (props.get("address") or props.get("host") or "").strip().lower()
        port = str(props.get("port") or 44818)
        slot = str(props.get("slot") or 0)
        return f"enip://{host}:{port}?slot={slot}"

    elif dev_type in ("mqtt"):
        host = (props.get("address") or props.get("broker") or "").strip().lower()
        port = str(props.get("port") or 1883)
        topic = (props.get("topic") or "").strip().lower()
        return f"mqtt://{host}:{port}?topic={topic}"

    elif dev_type in ("bacnet"):
        host = (props.get("address") or props.get("host") or "").strip().lower()
        port = str(props.get("port") or 47808)
        dev_id = str(props.get("deviceId") or "")
        return f"bacnet://{host}:{port}?devid={dev_id}"

    # Fallback to normalized name for internal or proprietary protocols
    name_norm = normalize_string(dev.get("name") or "")
    return f"{dev_type}://name/{name_norm}"


def is_ignored_device(dev: dict) -> bool:
    """Filters out internal FUXA Server device, loopback, or central storage bridges"""
    dev_id = str(dev.get("id") or "").lower()
    dev_type = str(dev.get("type") or "").lower()
    dev_name = str(dev.get("name") or "").lower()

    if dev_id in ("0", "server", "fuxa_server"):
        return True
    if dev_type in ("fuxaserver",):
        return True
    if "fuxa server" in dev_name:
        return True
    if "central_storage" in dev_name or "storage_opcua" in dev_name:
        return True
    return False


def load_project_file(source) -> tuple[dict, str]:
    """Safely loads a project JSON, bytes, or file path. Returns (dict, display_name)."""
    if isinstance(source, dict):
        return source, source.get("name") or "In-Memory Project"
    if isinstance(source, (bytes, bytearray)):
        data = json.loads(source.decode("utf-8"))
        return data, data.get("name") or "Uploaded Project"
    if not os.path.isfile(str(source)):
        raise FileNotFoundError(f"File not found: {source}")
    with open(source, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data, os.path.basename(source)


def resolve_storage_db_path(plant_id: int) -> tuple[str, str, int]:
    """Finds the project.fuxap.db path for the target Plant Storage Server"""
    plant_id = int(plant_id)
    storage_port = 5000 + plant_id * 100 if plant_id != 9 else 5900
    folder_name = f"storage_plant_{plant_id}_{storage_port}"
    work_dir = os.path.join(INSTANCES_DIR, folder_name)
    os.makedirs(work_dir, exist_ok=True)
    db_path = os.path.join(work_dir, "project.fuxap.db")
    return db_path, work_dir, storage_port


def load_existing_storage_devices(db_path: str) -> dict:
    """
    Loads existing devices from the target Storage Server's SQLite DB.
    Returns: dict keyed by device id.
    """
    if not os.path.exists(db_path):
        return {}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS devices (name TEXT PRIMARY KEY, value TEXT, connection TEXT, cntid TEXT, cntpwd TEXT);")
    cur.execute("SELECT name, value FROM devices;")
    rows = cur.fetchall()
    conn.close()

    devices = {}
    for d_name, d_val in rows:
        if d_name in ("server", "0"):
            continue
        try:
            dev = json.loads(d_val)
            dev_id = dev.get("id") or d_name
            dev["id"] = dev_id
            devices[dev_id] = dev
        except Exception:
            continue
    return devices


def merge_device_tags(canonical_dev: dict, incoming_dev: dict) -> tuple[int, int]:
    """
    Merges tags from incoming_dev into canonical_dev.
    Deduplicates tags by:
    1. Tag address / identifier (hardware register)
    2. Tag name (case-insensitive)
    3. Tag ID

    Returns: (added_count, duplicate_count)
    """
    if "tags" not in canonical_dev or not isinstance(canonical_dev["tags"], dict):
        canonical_dev["tags"] = {}

    existing_tags = canonical_dev["tags"]

    # Build lookup indices for existing tags
    existing_by_address = {}
    existing_by_name = {}
    existing_by_id = set(existing_tags.keys())

    for t_id, tag in existing_tags.items():
        if isinstance(tag, dict):
            # Sanitize local SQLite DAQ: Central Storage handles history centrally
            if "daq" in tag and isinstance(tag["daq"], dict):
                tag["daq"]["enabled"] = False
            addr = str(tag.get("address") or "").strip().lower()
            if addr:
                existing_by_address[addr] = t_id
            name_norm = normalize_string(tag.get("name") or "")
            if name_norm:
                existing_by_name[name_norm] = t_id

    added_count = 0
    duplicate_count = 0

    incoming_tags = incoming_dev.get("tags") or {}
    if isinstance(incoming_tags, list):
        # Handle cases where tags were exported as an array
        incoming_tags = {t.get("id") or f"t_{i}": t for i, t in enumerate(incoming_tags) if isinstance(t, dict)}

    for t_id, tag in incoming_tags.items():
        if not isinstance(tag, dict):
            continue

        addr = str(tag.get("address") or "").strip().lower()
        name_norm = normalize_string(tag.get("name") or "")

        # Check if already present by address, name, or id
        match_id = None
        if addr and addr in existing_by_address:
            match_id = existing_by_address[addr]
        elif name_norm and name_norm in existing_by_name:
            match_id = existing_by_name[name_norm]
        elif t_id in existing_by_id:
            match_id = t_id

        if match_id:
            duplicate_count += 1
            # Optionally enrich missing description or unit from incoming tag
            target_tag = existing_tags[match_id]
            for key in ("description", "label", "unit", "format", "scale"):
                if key in tag and not target_tag.get(key):
                    target_tag[key] = tag[key]
        else:
            # New tag: add to canonical device
            # Ensure tag ID does not collide with an existing unrelated tag ID
            new_id = t_id
            if new_id in existing_by_id:
                new_id = f"{canonical_dev['id']}_{normalize_string(tag.get('name') or 'tag')}_{int(time.time()*1000)%100000}"

            tag_copy = dict(tag)
            tag_copy["id"] = new_id
            if "daq" in tag_copy and isinstance(tag_copy["daq"], dict):
                tag_copy["daq"]["enabled"] = False
            existing_tags[new_id] = tag_copy
            existing_by_id.add(new_id)
            if addr:
                existing_by_address[addr] = new_id
            if name_norm:
                existing_by_name[name_norm] = new_id
            added_count += 1

    return added_count, duplicate_count


def import_devices(
    source_files: list[str],
    plant_id: int = 9,
    dry_run: bool = False,
    create_backup: bool = True,
    restart_storage: bool = False,
    enable_history: bool = True,
    daq_mode: str = "change",
    daq_interval: int = 60
) -> dict:
    """
    Main execution engine:
    Extracts, deduplicates, merges, and writes devices to the target Storage Server.
    """
    db_path, work_dir, storage_port = resolve_storage_db_path(plant_id)

    print("=" * 76)
    print(" FUXA ENTERPRISE - STORAGE SERVER DEVICE IMPORTER & DEDUPLICATOR")
    print("=" * 76)
    print(f"[*] Target Plant:          Plant {plant_id}")
    print(f"[*] Storage Port:          Port {storage_port}")
    print(f"[*] Target Database:      {db_path}")
    print(f"[*] Dry-run Mode:          {'ON (Preview Only)' if dry_run else 'OFF (Live Commit)'}")
    print(f"[*] Source Files:          {len(source_files)} file(s) provided")
    print("-" * 76)

    # 1. Load existing devices in the target Storage Server
    canonical_devices = load_existing_storage_devices(db_path)
    print(f"[*] Existing devices in Storage Server: {len(canonical_devices)}")

    # Index existing devices by signature, normalized name, and ID
    sig_to_id = {}
    name_to_id = {}
    for d_id, dev in canonical_devices.items():
        sig = compute_device_signature(dev)
        sig_to_id[sig] = d_id
        name_norm = normalize_string(dev.get("name") or "")
        if name_norm:
            name_to_id[name_norm] = d_id

    # 2. Process all incoming project files
    audit_report = {
        "files_scanned": len(source_files),
        "total_incoming_devices": 0,
        "new_devices_added": 0,
        "duplicate_devices_merged": 0,
        "new_tags_added": 0,
        "duplicate_tags_skipped": 0,
        "devices": []
    }

    for file_idx, fpath in enumerate(source_files, 1):
        try:
            proj, src_name = load_project_file(fpath)
            print(f"\n[{file_idx}/{len(source_files)}] Parsing: {src_name}...")
        except Exception as e:
            print(f"    [-] Failed to read source #{file_idx}: {e}")
            continue

        incoming_devs = proj.get("devices") or {}
        if isinstance(incoming_devs, list):
            incoming_devs = {d.get("id") or f"d_{i}": d for i, d in enumerate(incoming_devs) if isinstance(d, dict)}

        for dev_key, dev in incoming_devs.items():
            if not isinstance(dev, dict):
                continue
            if is_ignored_device(dev):
                continue

            audit_report["total_incoming_devices"] += 1
            dev_name = dev.get("name") or dev_key
            dev_type = dev.get("type") or "Unknown"
            sig = compute_device_signature(dev)
            name_norm = normalize_string(dev_name)

            # Check for match in canonical devices
            matched_id = None
            match_reason = None

            if sig in sig_to_id:
                matched_id = sig_to_id[sig]
                match_reason = f"Hardware Signature match ({sig})"
            elif name_norm and name_norm in name_to_id:
                matched_id = name_to_id[name_norm]
                match_reason = f"Normalized Name match ('{dev_name}')"
            elif dev.get("id") and dev["id"] in canonical_devices:
                matched_id = dev["id"]
                match_reason = f"Direct Device ID match ('{dev['id']}')"

            if matched_id:
                # Duplicate Device: Merge tags into the existing canonical device
                canonical_dev = canonical_devices[matched_id]
                tags_added, tags_dup = merge_device_tags(canonical_dev, dev)
                audit_report["duplicate_devices_merged"] += 1
                audit_report["new_tags_added"] += tags_added
                audit_report["duplicate_tags_skipped"] += tags_dup

                action_str = f"MERGED DUPLICATE into '{canonical_dev.get('name')}'"
                print(f"    ↳ [DUPLICATE] '{dev_name}' ({dev_type}) -> {action_str} [{match_reason}]")
                print(f"        Tags: +{tags_added} new added, {tags_dup} duplicates reconciled")

                audit_report["devices"].append({
                    "name": dev_name,
                    "type": dev_type,
                    "action": "MERGED",
                    "target_device": canonical_dev.get("name"),
                    "tags_added": tags_added,
                    "tags_duplicate": tags_dup,
                    "reason": match_reason
                })

            else:
                # Brand New Device
                new_dev = dict(dev)
                new_dev_id = dev.get("id") or f"dev_{normalize_string(dev_name)}_{int(time.time()*1000)%100000}"
                new_dev["id"] = new_dev_id
                if "tags" not in new_dev or not isinstance(new_dev["tags"], dict):
                    new_dev["tags"] = {}

                canonical_devices[new_dev_id] = new_dev
                sig_to_id[sig] = new_dev_id
                if name_norm:
                    name_to_id[name_norm] = new_dev_id

                tags_count = len(new_dev.get("tags", {}))
                audit_report["new_devices_added"] += 1
                audit_report["new_tags_added"] += tags_count

                print(f"    ↳ [NEW DEVICE] '{dev_name}' ({dev_type}, {tags_count} tags) -> Registered as '{new_dev_id}'")

                audit_report["devices"].append({
                    "name": dev_name,
                    "type": dev_type,
                    "action": "CREATED",
                    "target_device": dev_name,
                    "tags_added": tags_count,
                    "tags_duplicate": 0,
                    "reason": "Unique hardware connection"
                })

    # 3. Output Audit Summary
    print("\n" + "=" * 76)
    print(" DEDUPLICATION & MERGE AUDIT SUMMARY")
    print("=" * 76)
    print(f"  Total Incoming Devices Scanned:  {audit_report['total_incoming_devices']}")
    print(f"  New Unique Devices Added:        {audit_report['new_devices_added']}")
    print(f"  Duplicate Devices Merged:        {audit_report['duplicate_devices_merged']}")
    print(f"  New Tags Added to Devices:       {audit_report['new_tags_added']}")
    print(f"  Duplicate Tags Reconciled:       {audit_report['duplicate_tags_skipped']}")
    print(f"  Total Final Storage Devices:     {len(canonical_devices)}")
    print("=" * 76)

    if dry_run:
        print("\n[!] DRY RUN ACTIVE: Zero changes written to database.")
        return audit_report

    # 4. Commit changes to target Storage Server database safely
    if create_backup and os.path.exists(db_path):
        ts = time.strftime("%Y%m%d_%H%M%S")
        bak_path = f"{db_path}.bak_{ts}"
        shutil.copy2(db_path, bak_path)
        print(f"[+] Created safety backup of Storage DB: {os.path.basename(bak_path)}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Ensure required tables exist
    cur.execute("CREATE TABLE IF NOT EXISTS general (name TEXT PRIMARY KEY, value TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS devices (name TEXT PRIMARY KEY, value TEXT, connection TEXT, cntid TEXT, cntpwd TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS devicesSecurity (name TEXT PRIMARY KEY, value TEXT);")

    # Ensure internal FUXA Server device is preserved
    fuxa_server_dev = {"id": "0", "name": "FUXA Server", "type": "FuxaServer", "property": {}}
    cur.execute("INSERT OR REPLACE INTO devices (name, value, connection, cntid, cntpwd) VALUES (?, ?, ?, ?, ?);",
                ("server", json.dumps(fuxa_server_dev), "", "", ""))

    # Write each canonical device into the devices table
    for dev_id, dev in canonical_devices.items():
        dev_json = json.dumps(dev)
        cur.execute("INSERT OR REPLACE INTO devices (name, value, connection, cntid, cntpwd) VALUES (?, ?, ?, ?, ?);",
                    (dev_id, dev_json, "", "", ""))

    conn.commit()
    conn.close()
    print(f"[✓] Successfully committed {len(canonical_devices)} deduplicated devices to {db_path}!")

    # 4b. Optional Bulk Historical DAQ configuration
    if enable_history and not dry_run:
        from bulk_historical_tagging import configure_bulk_history
        print(f"[*] Applying bulk historical logging (DAQ: {daq_mode.upper()})...")
        daq_res = configure_bulk_history(
            plant_id=plant_id,
            enabled=True,
            mode=daq_mode,
            interval=daq_interval,
            create_backup=False,
            restart_instance=False
        )
        print(f"[✓] Historical DAQ enabled for {daq_res.get('total_tags_updated', 0)} tags across {daq_res.get('total_devices_affected', 0)} devices!")
        audit_report["bulk_daq"] = daq_res

    # 5. Optional Storage Server Restart
    if restart_storage:
        print(f"[*] Requesting Storage Server restart for Plant {plant_id}...")
        try:
            req_url = f"{FLEET_MANAGER_URL.rstrip('/')}/api/storage/{plant_id}/restart"
            req = urllib.request.Request(req_url, data=b"", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"[✓] Storage Server restarted: {resp.read().decode('utf-8')[:60]}...")
        except Exception as e:
            print(f"[*] Note: Could not auto-restart via Fleet Manager ({e}). You can restart via Fleet Manager UI or start_all.sh.")

    return audit_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FUXA Enterprise SCADA - Dedicated Device Importer & Deduplicator"
    )
    parser.add_argument(
        "--sources", "-s",
        nargs="+",
        required=True,
        help="One or more project.json / .fuxap files or glob patterns (e.g. -s file1.json file2.json)"
    )
    parser.add_argument(
        "--plant", "-p",
        type=int,
        default=9,
        help="Target Plant ID for Storage Server (default: 9)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview device deduplication and tag merging without modifying the database"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a safety backup of project.fuxap.db"
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Automatically trigger restart of the Storage Server after commit"
    )
    parser.add_argument(
        "--no-history",
        dest="enable_history",
        action="store_false",
        default=True,
        help="Skip automatically enabling historical logging (DAQ) for imported tags"
    )
    parser.add_argument(
        "--enable-history",
        dest="enable_history",
        action="store_true",
        default=True,
        help="Automatically enable bulk historical logging (DAQ) for all imported tags (enabled by default)"
    )
    parser.add_argument(
        "--daq-mode",
        choices=["change", "interval", "both"],
        default="change",
        help="Historical DAQ mode: 'change' (value changes only) or 'interval' (periodic)"
    )
    parser.add_argument(
        "--daq-interval",
        type=int,
        default=60,
        help="Periodic logging interval in seconds (default: 60)"
    )

    args = parser.parse_args()

    # Expand glob patterns if needed
    expanded_sources = []
    for s in args.sources:
        matches = glob.glob(s)
        if matches:
            expanded_sources.extend(matches)
        else:
            expanded_sources.append(s)

    if not expanded_sources:
        print("[-] Error: No matching source files found.")
        sys.exit(1)

    try:
        import_devices(
            source_files=expanded_sources,
            plant_id=args.plant,
            dry_run=args.dry_run,
            create_backup=not args.no_backup,
            restart_storage=args.restart,
            enable_history=args.enable_history,
            daq_mode=args.daq_mode,
            daq_interval=args.daq_interval
        )
    except Exception as ex:
        print(f"\n[-] Import failed: {ex}")
        sys.exit(1)
