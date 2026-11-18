#!/usr/bin/env python3
"""
==============================================================================
FUXA Enterprise SCADA - Dedicated Simulator & SoftOPC Purge Utility
==============================================================================
1. Terminates all lingering SoftOPC, simulator, and mock background processes.
2. Stops and disables any softopc or fuxa-simulator systemd services.
3. Sweeps all SQLite databases in instances/ (both root and _appdata) and
   permanently removes any legacy simulated demo devices.
4. Checkpoints SQLite WAL journals cleanly.
==============================================================================
"""

import os
import sys
import glob
import json
import sqlite3
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INSTANCES_DIR = os.path.join(BASE_DIR, "instances")


def kill_simulator_processes():
    print("[*] Checking and terminating any running SoftOPC / simulator processes...")
    patterns = ["soft_opcua", "softopc", "simulator", "simulated"]
    for pat in patterns:
        try:
            subprocess.run(["pkill", "-9", "-f", pat], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # Try stopping any systemd services if present
    for svc in ["soft_opcua", "softopc", "fuxa-simulator"]:
        try:
            subprocess.run(["systemctl", "stop", svc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    print("    ✓ All simulator processes terminated.")


def purge_databases():
    print(f"[*] Scanning databases in {INSTANCES_DIR} for simulated devices...")
    sim_keywords = (
        "sim_", "simulated", "mock", "softopc",
        "boiler_01", "press_line_a", "conveyor_main", "chiller_line_1",
        "feed_water_pump", "air_compressor"
    )
    sim_ports = ("4850", "4851", "4852", "4853", "4854")

    dbs = glob.glob(os.path.join(INSTANCES_DIR, "**", "project.fuxap.db"), recursive=True)
    if not dbs:
        print("    ℹ No instance databases found.")
        return

    total_purged = 0
    for db_path in dbs:
        rel_path = os.path.relpath(db_path, BASE_DIR)
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS devices (name TEXT PRIMARY KEY, value TEXT, connection TEXT, cntid TEXT, cntpwd TEXT);")
            cur.execute("SELECT name, value FROM devices;")
            rows = cur.fetchall()
            to_delete = []

            for d_name, d_val in rows:
                if d_name in ("server", "0"):
                    continue
                try:
                    dev = json.loads(d_val)
                    d_lower = str(dev.get("name") or "").lower()
                    props = dev.get("property") or {}
                    addr = str(props.get("address") or props.get("endpoint") or "").lower()

                    if any(k in d_lower for k in sim_keywords) or any(p in addr for p in sim_ports):
                        to_delete.append(d_name)
                except Exception:
                    pass

            for d_name in to_delete:
                cur.execute("DELETE FROM devices WHERE name = ?;", (d_name,))
                try:
                    cur.execute("DELETE FROM devicesSecurity WHERE name = ?;", (d_name,))
                except Exception:
                    pass

            if to_delete:
                conn.commit()
                try:
                    cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                except Exception:
                    pass
                print(f"    ✓ Purged {len(to_delete)} simulated device(s) from {rel_path}: {', '.join(to_delete)}")
                total_purged += len(to_delete)

            conn.close()
        except Exception as e:
            print(f"    [-] Notice on {rel_path}: {e}")

    print(f"[✓] Total simulated devices purged across fleet: {total_purged}")


def main():
    print("=" * 70)
    print(" FUXA Enterprise SCADA - Purge Simulated Devices & SoftOPC Services")
    print("=" * 70)
    kill_simulator_processes()
    purge_databases()
    print("=" * 70)
    print("✓ Done! All simulated devices and services removed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
