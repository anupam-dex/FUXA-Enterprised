#!/usr/bin/env python3
"""
PM2 Adapter for FUXA Fleet Manager
Integrates directly with the PM2 CLI on the server for autonomous process orchestration.
"""

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("PM2Adapter")

class PM2Adapter:
    def __init__(self):
        self.pm2_bin = shutil.which("pm2")

    def is_available(self) -> bool:
        return self.pm2_bin is not None

    def list_processes(self):
        """Returns parsed JSON from 'pm2 jlist' or empty list if unavailable"""
        if not self.pm2_bin:
            return []
        try:
            res = subprocess.run([self.pm2_bin, "jlist"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout)
        except Exception as e:
            logger.warning(f"Error fetching PM2 process list: {e}")
        return []

    def get_process_status(self, name_or_id: str):
        """Finds a process by name or pm_id in pm2 jlist"""
        processes = self.list_processes()
        for p in processes:
            if p.get("name") == name_or_id or str(p.get("pm_id")) == str(name_or_id):
                monit = p.get("monit", {})
                pm2_env = p.get("pm2_env", {})
                return {
                    "exists": True,
                    "name": p.get("name"),
                    "pm_id": p.get("pm_id"),
                    "pid": p.get("pid"),
                    "status": pm2_env.get("status", "unknown"),  # 'online', 'stopped', 'errored'
                    "cpu": monit.get("cpu", 0),
                    "memory_mb": round(monit.get("memory", 0) / (1024 * 1024), 1),
                    "restart_time": pm2_env.get("restart_time", 0),
                    "uptime": pm2_env.get("pm_uptime", 0)
                }
        return {"exists": False, "status": "NOT_REGISTERED"}

    def start_instance(self, name: str, script_path: str, port: int, user_dir: str, subpath: str = "", role: str = "view") -> dict:
        """
        Registers and starts a FUXA instance in PM2 with its dedicated port and userDir.
        Sets role ('storage' or 'view') and restricts plugins accordingly.
        Then persists with 'pm2 save'.
        """
        if not self.pm2_bin:
            return {"success": False, "error": "pm2 binary not found on PATH"}

        cmd = [
            self.pm2_bin, "start", script_path,
            "--name", name,
            "--restart-delay", "1000",
            "--", "-p", str(port), "-u", user_dir, "--role", role
        ]
        if role == "view":
            cmd.append("--disablePlugins")

        env = os.environ.copy()
        if subpath:
            env["BASE_PATH"] = subpath
        env["FUXA_ROLE"] = role
        if role == "view":
            env["FUXA_DISABLE_PLUGINS"] = "true"
        env["NODE_OPTIONS"] = "--max-old-space-size=4096"

        try:
            logger.info(f"Running PM2 command: {' '.join(cmd)}")
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                self.save()
                return {"success": True, "message": f"Started {name} in PM2 on port {port} (role: {role})"}
            return {"success": False, "error": res.stderr or res.stdout}
        except Exception as e:
            logger.error(f"Failed to start PM2 process {name}: {e}")
            return {"success": False, "error": str(e)}

    def stop_instance(self, name: str) -> dict:
        if not self.pm2_bin:
            return {"success": False, "error": "pm2 not found"}
        try:
            res = subprocess.run([self.pm2_bin, "stop", name], capture_output=True, text=True, timeout=10)
            return {"success": res.returncode == 0, "output": res.stdout}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restart_instance(self, name: str) -> dict:
        if not self.pm2_bin:
            return {"success": False, "error": "pm2 not found"}
        try:
            res = subprocess.run([self.pm2_bin, "restart", name], capture_output=True, text=True, timeout=10)
            return {"success": res.returncode == 0, "output": res.stdout}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_instance(self, name: str) -> dict:
        if not self.pm2_bin:
            return {"success": False, "error": "pm2 not found"}
        try:
            res = subprocess.run([self.pm2_bin, "delete", name], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                self.save()
                return {"success": True}
            return {"success": False, "error": res.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save(self):
        """Persists active PM2 list across server reboots"""
        if self.pm2_bin:
            try:
                subprocess.run([self.pm2_bin, "save"], capture_output=True, text=True, timeout=10)
            except Exception:
                pass

    def get_process_logs(self, target: str, lines: int = 100) -> dict:
        """
        Retrieves recent stdout and stderr logs for a PM2 process,
        matched by process name, pm_id, or port number.
        """
        processes = self.list_processes()
        matched = None
        target_str = str(target).strip()

        for p in processes:
            p_name = str(p.get("name", ""))
            p_id = str(p.get("pm_id", ""))
            pm2_env = p.get("pm2_env", {})
            raw_args = pm2_env.get("args", [])
            args_str = " ".join(raw_args) if isinstance(raw_args, list) else str(raw_args)

            # Match criteria:
            # 1. Exact name match (case-insensitive)
            # 2. Exact pm_id match
            # 3. Port number in args (e.g. -p 5801)
            # 4. Port number in process name (e.g. fuxa_p9_d6_l1_9610)
            # 5. Target 5801 matches Plant 9 storage name
            port_match = False
            if target_str.isdigit():
                if f"-p {target_str}" in args_str or f"-p={target_str}" in args_str:
                    port_match = True
                elif f"_{target_str}" in p_name or f"-{target_str}" in p_name:
                    port_match = True
                elif target_str in ["5801", "5810"] and ("P9" in p_name.upper() or "STORAGE" in p_name.upper()):
                    port_match = True

            if p_name.lower() == target_str.lower() or p_id == target_str or port_match:
                matched = p
                break

        if not matched:
            # Check local fuxa.log files as fallback
            fuxa_log = os.path.join(os.getcwd(), "_logs", "fuxa.log")
            if os.path.exists(fuxa_log):
                return {
                    "found": True,
                    "name": "Local FUXA Log",
                    "pm_id": "-",
                    "status": "active",
                    "out_log_path": fuxa_log,
                    "err_log_path": "",
                    "stdout": self._tail_file(fuxa_log, lines),
                    "stderr": []
                }
            return {
                "found": False,
                "error": f"No PM2 process found matching target '{target}'. Available: {[p.get('name') for p in processes]}"
            }

        pm2_env = matched.get("pm2_env", {})
        out_path = pm2_env.get("pm_out_log_path")
        err_path = pm2_env.get("pm_err_log_path")

        # Fallback to standard ~/.pm2/logs path if env paths missing
        if not out_path or not os.path.exists(out_path):
            home = os.path.expanduser("~")
            candidate = os.path.join(home, ".pm2", "logs", f"{matched.get('name')}-out.log")
            if os.path.exists(candidate):
                out_path = candidate
        if not err_path or not os.path.exists(err_path):
            home = os.path.expanduser("~")
            candidate = os.path.join(home, ".pm2", "logs", f"{matched.get('name')}-error.log")
            if os.path.exists(candidate):
                err_path = candidate

        return {
            "found": True,
            "name": matched.get("name"),
            "pm_id": matched.get("pm_id"),
            "status": pm2_env.get("status", "unknown"),
            "out_log_path": out_path or "N/A",
            "err_log_path": err_path or "N/A",
            "stdout": self._tail_file(out_path, lines),
            "stderr": self._tail_file(err_path, lines)
        }

    def _tail_file(self, file_path: str, max_lines: int) -> list:
        if not file_path or not os.path.exists(file_path):
            return [f"Log file not found at: {file_path}\n"]
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                return all_lines[-max_lines:]
        except Exception as e:
            return [f"Error reading {file_path}: {e}\n"]
