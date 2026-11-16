#!/usr/bin/env python3
"""
==============================================================================
FUXA Enterprise SCADA - Instance Diagnostics & Fault Isolation Engine
==============================================================================
Analyzes why a FUXA instance (Storage Master or View Server) failed to boot,
crashed, or became unreachable.

Produces structured, human-readable fault reports with:
- Exact Root Cause
- Port occupancy / rogue PID detection
- Stderr / fuxa.log trace analysis
- Actionable automated remedy
==============================================================================
"""

import os
import re
import sys
import psutil
import sqlite3
import subprocess

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTANCES_DIR = os.path.join(BASE_DIR, "instances")


def find_process_on_port(port: int) -> dict | None:
    """Finds which PID and command is occupying a given TCP port"""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                if pid:
                    try:
                        p = psutil.Process(pid)
                        return {
                            "pid": pid,
                            "name": p.name(),
                            "cmdline": " ".join(p.cmdline()[:4]),
                            "username": p.username()
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return {"pid": pid, "name": "unknown", "cmdline": "", "username": ""}
    except Exception:
        pass

    # Fallback to lsof / fuser
    try:
        out = subprocess.check_output(["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"], stderr=subprocess.DEVNULL)
        pids = out.decode().strip().split()
        if pids:
            pid = int(pids[0])
            try:
                p = psutil.Process(pid)
                return {"pid": pid, "name": p.name(), "cmdline": " ".join(p.cmdline()[:4]), "username": ""}
            except Exception:
                return {"pid": pid, "name": "unknown", "cmdline": "", "username": ""}
    except Exception:
        pass
    return None


def read_log_tail(log_path: str, max_lines: int = 40) -> list[str]:
    """Safely reads the last N lines from an instance log file"""
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return [l.rstrip() for l in lines[-max_lines:]]
    except Exception:
        return []


def analyze_log_errors(lines: list[str]) -> tuple[str, str, str] | None:
    """
    Parses recent log lines to detect known failure patterns.
    Returns: (fault_summary, fault_details, remedy) or None
    """
    joined = "\n".join(lines)

    # 1. Outdated Node version / SyntaxError
    if "SyntaxError: Unexpected token '.'" in joined or "SyntaxError: Unexpected token '?'" in joined:
        return (
            "Outdated Node.js Version",
            "Node.js syntax error: Modern JavaScript syntax (?. or ??) failed to parse on legacy Node.js runtime.",
            "Upgrade system Node.js to Node 20 LTS: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"
        )

    # 2. Port already in use
    if "EADDRINUSE" in joined:
        m = re.search(r"listen EADDRINUSE.*?(\d+)", joined)
        port_num = m.group(1) if m else "target"
        return (
            f"Port Conflict (Port {port_num} already in use)",
            f"FUXA server could not bind to TCP Port {port_num} because another process is already listening on it.",
            f"Free the port automatically or kill the zombie process using: fuser -k {port_num}/tcp"
        )

    # 3. Database locked (SQLITE_BUSY)
    if "SQLITE_BUSY" in joined or "database is locked" in joined.lower():
        return (
            "Database Locked (SQLITE_BUSY)",
            "The SQLite project database (project.fuxap.db) is locked by an unclosed transaction or stale process.",
            "Remove stale lock files (.db-wal / .db-journal) and restart instance."
        )

    # 4. Missing Node.js module
    if "MODULE_NOT_FOUND" in joined or "Cannot find module" in joined:
        m = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", joined)
        mod_name = m.group(1) if m else "dependency"
        return (
            f"Missing Node.js Dependency ({mod_name})",
            f"Required module '{mod_name}' is missing from fuxa/server/node_modules.",
            f"Run 'cd fuxa/server && npm install' to install missing dependencies."
        )

    # 5. Permission denied
    if "EACCES" in joined or "permission denied" in joined.lower():
        return (
            "Filesystem Permission Denied (EACCES)",
            "The SCADA server process lacks write permissions to its instance directory or project database.",
            "Grant write permissions: chmod -R 777 instances/ && chown -R $USER instances/"
        )

    # 6. OPC-UA connection refused
    if "ECONNREFUSED" in joined and "4845" in joined:
        return (
            "Central Storage OPC-UA Bridge Unreachable",
            "View server cannot connect to the Central Storage OPC-UA Bridge at opc.tcp://127.0.0.1:4845.",
            "Ensure the OPC-UA bridge is running: check opcua_bridge.log or restart via Fleet Manager."
        )

    # 7. JavaScript heap out of memory
    if "JavaScript heap out of memory" in joined:
        return (
            "Node.js Out of Memory",
            "The V8 JavaScript runtime exhausted allocated heap memory during execution.",
            "Increase NODE_OPTIONS memory limit: NODE_OPTIONS='--max-old-space-size=4096'"
        )

    # 8. Generic uncaught exception
    for line in reversed(lines):
        if "uncaughtException" in line or "Error:" in line or "FATAL" in line or "Exception" in line:
            return (
                "Uncaught Server Exception",
                line.strip(),
                "Inspect the log tail below to diagnose the runtime crash."
            )

    return None


def diagnose_instance_fault(
    instance_id: str,
    port: int,
    work_dir: str,
    expected_running: bool = True
) -> dict:
    """
    Performs full diagnostic audit of an instance and returns a structured report:
    {
        "status": "HEALTHY" | "FAULTED" | "STOPPED",
        "fault_summary": str,
        "fault_details": str,
        "remedy": str,
        "port": int,
        "port_occupant": dict | None,
        "db_status": str,
        "log_tail": list[str],
        "log_path": str
    }
    """
    log_path = os.path.join(work_dir, "fuxa.log")
    log_lines = read_log_tail(log_path, max_lines=35)
    db_path = os.path.join(work_dir, "project.fuxap.db")

    report = {
        "instance_id": instance_id,
        "port": port,
        "work_dir": work_dir,
        "log_path": log_path,
        "status": "HEALTHY",
        "fault_summary": "",
        "fault_details": "",
        "remedy": "",
        "port_occupant": None,
        "db_status": "OK",
        "log_tail": log_lines
    }

    # 1. Audit Port & Process
    occupant = find_process_on_port(port)
    report["port_occupant"] = occupant

    # 2. Audit Database
    if not os.path.exists(db_path):
        report["db_status"] = "MISSING"
    else:
        # Check for stale lock files
        wal_file = f"{db_path}-wal"
        journal_file = f"{db_path}-journal"
        if os.path.exists(journal_file) or os.path.exists(wal_file):
            report["db_status"] = "LOCK_FILES_PRESENT"

        try:
            conn = sqlite3.connect(db_path, timeout=1.0)
            cur = conn.cursor()
            cur.execute("SELECT name FROM general LIMIT 1;")
            conn.close()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                report["db_status"] = "LOCKED"
            else:
                report["db_status"] = f"CORRUPT ({e})"
        except Exception as e:
            report["db_status"] = f"ERROR ({e})"

    # 3. If port is in use by FUXA, verify if it's healthy
    if occupant:
        # Port is listening
        if "node" in occupant.get("name", "").lower() or "fuxa" in occupant.get("cmdline", "").lower():
            report["status"] = "HEALTHY"
            return report
        else:
            # Port is occupied by a foreign/rogue process!
            report["status"] = "FAULTED"
            report["fault_summary"] = f"Port {port} blocked by rogue process '{occupant.get('name')}' (PID {occupant.get('pid')})"
            report["fault_details"] = f"Command: {occupant.get('cmdline')}"
            report["remedy"] = f"Force-free port {port} by terminating PID {occupant.get('pid')} (fuser -k {port}/tcp)"
            return report

    # 4. Port is NOT listening. If it was supposed to be running, why did it stop/fail?
    if expected_running:
        report["status"] = "FAULTED"

        # Check DB locks first
        if report["db_status"] == "LOCKED" or report["db_status"] == "LOCK_FILES_PRESENT":
            report["fault_summary"] = "Database Lock Conflict (project.fuxap.db)"
            report["fault_details"] = "A stale SQLite lock or journal file is preventing the FUXA instance from opening its project database."
            report["remedy"] = "Clean stale lock files (.db-journal / .db-wal) and relaunch instance."
            return report

        # Analyze log lines for crashes
        analyzed = analyze_log_errors(log_lines)
        if analyzed:
            report["fault_summary"], report["fault_details"], report["remedy"] = analyzed
            return report

        # Check if node binary is missing
        try:
            subprocess.check_output(["node", "-v"], stderr=subprocess.DEVNULL)
        except Exception:
            report["fault_summary"] = "Node.js Binary Not Found in PATH"
            report["fault_details"] = "The 'node' executable could not be located in system PATH."
            report["remedy"] = "Install Node 20 LTS: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"
            return report

        # Fallback generic fault
        report["fault_summary"] = f"Process Exited Unexpectedly on Port {port}"
        report["fault_details"] = "FUXA process exited or failed to bind to its assigned port within the startup grace period."
        report["remedy"] = "Inspect the log tail below or click 'Auto-Fix & Relaunch' to reset ports and start afresh."

    else:
        report["status"] = "STOPPED"
        report["fault_summary"] = "Instance stopped by user"

    return report


def auto_heal_instance(port: int, work_dir: str) -> dict:
    """
    Performs automated self-healing for an instance:
    1. Kills any lingering process on the port.
    2. Cleans up stale SQLite lock files.
    3. Normalizes file permissions.
    """
    actions_taken = []

    # 1. Force kill rogue processes on port
    occupant = find_process_on_port(port)
    if occupant and occupant.get("pid"):
        pid = occupant["pid"]
        try:
            os.kill(pid, 9)
            actions_taken.append(f"Killed conflicting PID {pid} on port {port}")
        except Exception:
            pass

    try:
        subprocess.run(["fuser", "-k", f"{port}/tcp"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        actions_taken.append(f"Cleared port {port} via fuser")
    except Exception:
        pass

    # 2. Clean stale DB journal / wal files
    db_path = os.path.join(work_dir, "project.fuxap.db")
    for lock_suffix in ["-journal", "-wal", "-shm"]:
        lf = db_path + lock_suffix
        if os.path.exists(lf):
            try:
                os.remove(lf)
                actions_taken.append(f"Removed stale lock file: {os.path.basename(lf)}")
            except Exception:
                pass

    # 3. Ensure work_dir permissions
    try:
        os.chmod(work_dir, 0o777)
    except Exception:
        pass

    return {
        "success": True,
        "actions": actions_taken,
        "message": "; ".join(actions_taken) if actions_taken else "Environment already clean"
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("[*] Running diagnostics test on Port 9610...")
        test_dir = os.path.join(INSTANCES_DIR, "port_9610")
        os.makedirs(test_dir, exist_ok=True)
        res = diagnose_instance_fault("test_9610", 9610, test_dir, expected_running=True)
        import json
        print(json.dumps(res, indent=2))
