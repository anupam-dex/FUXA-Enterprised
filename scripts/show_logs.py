#!/usr/bin/env python3
"""
FUXA Process & Port Log Inspector
Inspect real-time logs for any FUXA port, PM2 process, or application log file.

Usage:
  python3 scripts/show_logs.py --port 5801
  python3 scripts/show_logs.py --name P9_FUXA_Enterprise
  python3 scripts/show_logs.py --all
  python3 scripts/show_logs.py --port 5801 --lines 50 --errors-only
"""

import os
import sys
import glob
import json
import shutil
import argparse
import subprocess

def get_pm2_processes():
    pm2_bin = shutil.which("pm2")
    if not pm2_bin:
        return []
    try:
        res = subprocess.run([pm2_bin, "jlist"], capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception as e:
        print(f"[!] Warning: error querying PM2: {e}")
    return []

def tail_file(file_path, max_lines):
    if not file_path or not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return lines[-max_lines:]
    except Exception as e:
        return [f"Error reading {file_path}: {e}\n"]

def show_process_log(proc, lines=50, errors_only=False):
    name = proc.get("name", "unnamed")
    pm_id = proc.get("pm_id", "-")
    pm2_env = proc.get("pm2_env", {})
    status = pm2_env.get("status", "unknown").upper()
    monit = proc.get("monit", {})
    cpu = monit.get("cpu", 0)
    ram = round(monit.get("memory", 0) / (1024 * 1024), 1)

    args = pm2_env.get("args", [])
    port = "-"
    for idx, a in enumerate(args):
        if a == "-p" and idx + 1 < len(args):
            port = args[idx + 1]
            break

    status_icon = "🟢" if status == "ONLINE" else ("🔴" if status in ["ERRORED", "STOPPED"] else "⚪")

    print("=" * 70)
    print(f"{status_icon} Process: {name} (PM2 ID: {pm_id}) | Port: {port} | Status: {status}")
    print(f"   CPU: {cpu}% | RAM: {ram} MB | Restarts: {pm2_env.get('restart_time', 0)}")
    print("=" * 70)

    err_path = pm2_env.get("pm_err_log_path")
    out_path = pm2_env.get("pm_out_log_path")

    # Show stderr
    err_lines = tail_file(err_path, lines)
    if err_lines:
        print(f"\n[!] Errors Log (stderr: {err_path}):")
        print("-" * 70)
        print("".join(err_lines).rstrip())
    else:
        print(f"\n[✓] Errors Log: (No errors recorded in {err_path})")

    # Show stdout if not errors_only
    if not errors_only:
        out_lines = tail_file(out_path, lines)
        print(f"\n[*] Standard Output Log (stdout: {out_path}):")
        print("-" * 70)
        if out_lines:
            print("".join(out_lines).rstrip())
        else:
            print("(No stdout output recorded yet)")

    print("\n")

def check_local_fuxa_logs(lines=50):
    candidates = [
        os.path.join(os.getcwd(), "_logs", "fuxa.log"),
        os.path.join(os.getcwd(), "server", "_logs", "fuxa.log"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "_logs", "fuxa.log"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "server", "_logs", "fuxa.log"),
    ]
    candidates.extend(glob.glob(os.path.join(os.getcwd(), "locations", "**", "fuxa.log"), recursive=True))

    found_any = False
    for p in set(candidates):
        if os.path.exists(p):
            found_any = True
            print("=" * 70)
            print(f"📁 FUXA Internal Application Log: {p}")
            print("=" * 70)
            content = tail_file(p, lines)
            if content:
                print("".join(content).rstrip())
            else:
                print("(File is empty)")
            print("\n")

    if not found_any:
        print("[i] No local _logs/fuxa.log files found on disk.")

def main():
    parser = argparse.ArgumentParser(description="FUXA Process & Port Log Inspector")
    parser.add_argument("--port", type=str, help="Target port number (e.g. 5801, 9610)")
    parser.add_argument("--name", type=str, help="Target PM2 process name (e.g. P9_FUXA_Enterprise)")
    parser.add_argument("--all", action="store_true", help="Display logs for all running PM2 processes")
    parser.add_argument("--lines", type=int, default=50, help="Number of lines to tail (default: 50)")
    parser.add_argument("--errors-only", action="store_true", help="Only show stderr error output")
    parser.add_argument("--file", action="store_true", help="Read internal _logs/fuxa.log files directly")

    args = parser.parse_args()

    if args.file:
        check_local_fuxa_logs(lines=args.lines)
        return

    processes = get_pm2_processes()

    if not processes:
        print("[!] No processes found in PM2 (or PM2 is not active). Checking local log files instead...")
        check_local_fuxa_logs(lines=args.lines)
        return

    if args.all:
        print(f"\n[i] Found {len(processes)} PM2 processes:\n")
        for p in processes:
            show_process_log(p, lines=args.lines, errors_only=args.errors_only)
        return

    target = args.port or args.name

    if not target:
        print("\nAvailable PM2 Processes:")
        for p in processes:
            pm2_env = p.get("pm2_env", {})
            status = pm2_env.get("status", "unknown")
            args_list = pm2_env.get("args", [])
            port = "-"
            for idx, a in enumerate(args_list):
                if a == "-p" and idx + 1 < len(args_list):
                    port = args_list[idx + 1]
                    break
            print(f"  • PM2 Name: {p.get('name')} | ID: {p.get('pm_id')} | Port: {port} | Status: {status}")
        print("\nUsage:")
        print("  python3 scripts/show_logs.py --port <port_number>")
        print("  python3 scripts/show_logs.py --name <process_name>")
        print("  python3 scripts/show_logs.py --all\n")
        return

    matched = []
    for p in processes:
        p_name = str(p.get("name", ""))
        p_id = str(p.get("pm_id", ""))
        pm2_env = p.get("pm2_env", {})
        args_list = pm2_env.get("args", [])
        port = ""
        for idx, a in enumerate(args_list):
            if a == "-p" and idx + 1 < len(args_list):
                port = str(args_list[idx + 1])
                break

        if target == port or target.lower() == p_name.lower() or target == p_id:
            matched.append(p)

    if not matched:
        print(f"[X] No process found matching target '{target}'.")
        print(f"    Available names: {[p.get('name') for p in processes]}")
        return

    for p in matched:
        show_process_log(p, lines=args.lines, errors_only=args.errors_only)

if __name__ == "__main__":
    main()
