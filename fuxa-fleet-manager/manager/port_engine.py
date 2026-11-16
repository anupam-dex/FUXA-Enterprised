#!/usr/bin/env python3
"""
Port Engine & Registry
Calculates deterministic ports, manages allocations across plants,
and auto-discovers manually created PM2 and directory instances.
"""

import socket
import json
import os
import re
import logging

logger = logging.getLogger("PortEngine")

REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "registry.json")

class PortEngine:
    def __init__(self, registry_path=REGISTRY_FILE, pm2_adapter=None):
        self.registry_path = registry_path
        self.pm2_adapter = pm2_adapter
        self.registry = self._load_registry()

    def _load_registry(self):
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading registry: {e}")
        return {
            "plants": {
                "1": {"name": "Plant 1 - Foundry & Powerhouse", "storage_port": 5100, "storage_pm2_name": "P1_Storage_Server"},
                "2": {"name": "Plant 2 - Stamping & Press", "storage_port": 5200, "storage_pm2_name": "P2_Storage_Server"},
                "3": {"name": "Plant 3 - Body & Assembly", "storage_port": 5300, "storage_pm2_name": "P3_Storage_Server"},
                "4": {"name": "Plant 4 - Powertrain & Engine", "storage_port": 5400, "storage_pm2_name": "P4_Storage_Server"},
                "9": {"name": "Plant 9 - Paintshop Complex", "storage_port": 5801, "storage_pm2_name": "P9_FUXA_Enterprise"}
            },
            "divisions": {
                "1": "Body Shop",
                "2": "Stamping",
                "3": "Assembly",
                "4": "Quality & Inspection",
                "5": "Utility & Boiler",
                "6": "Paintshop",
                "7": "Robotics & Automation",
                "8": "Material Handling"
            },
            "instances": {}
        }

    def _save_registry(self):
        try:
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(self.registry, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving registry: {e}")

    def is_port_in_use(self, port: int) -> bool:
        """Checks if a port is listening on the host network"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            result = s.connect_ex(('127.0.0.1', port))
            return result == 0

    def calculate_port(self, plant: int, division: int, line: int) -> int:
        """
        Calculates base port: plant(D1) + division(D2) + line(D3) + 0(D4)
        e.g. Plant 9, Division 6 (Paintshop), Line 1 -> 9610
        Auto-resolves collisions by incrementing to 9611, 9612...
        """
        base = int(f"{plant}{division}{line}0")
        candidate = base

        allocated_ports = {inst["port"] for inst in self.registry.get("instances", {}).values()}

        while candidate in allocated_ports or self.is_port_in_use(candidate):
            candidate += 1
            if candidate > base + 9:
                # Range overflow protection: move to 9700 block
                candidate = 9700
                while candidate in allocated_ports or self.is_port_in_use(candidate):
                    candidate += 1
                break

        return candidate

    def register_instance(self, instance_id, data):
        if "instances" not in self.registry:
            self.registry["instances"] = {}
        self.registry["instances"][instance_id] = data
        self._save_registry()

    def unregister_instance(self, instance_id):
        if "instances" in self.registry and instance_id in self.registry["instances"]:
            del self.registry["instances"][instance_id]
            self._save_registry()

    def get_all_instances(self):
        return self.registry.get("instances", {})

    def auto_sync_instances(self, instances_dir: str):
        """
        Scans PM2 processes and instances directory for any manually added View/Storage servers
        and automatically incorporates them into the active registry.
        """
        changed = False

        # 1. Sync from local directory
        if os.path.exists(instances_dir):
            for d in os.listdir(instances_dir):
                m = re.match(r"port_(\d+)", d)
                if m:
                    port = int(m.group(1))
                    inst_id = f"fuxa_port_{port}"
                    work_dir = os.path.join(instances_dir, d)
                    if inst_id not in self.registry.get("instances", {}):
                        # Infer plant/division/line from port if follows convention
                        port_str = str(port)
                        plant = int(port_str[0]) if len(port_str) >= 4 else 9
                        div = int(port_str[1]) if len(port_str) >= 4 else 6
                        line = int(port_str[2]) if len(port_str) >= 4 else 1

                        self.registry.setdefault("instances", {})[inst_id] = {
                            "id": inst_id,
                            "name": f"Discovered Instance (Port {port})",
                            "plant": plant,
                            "division": div,
                            "line": line,
                            "port": port,
                            "subpath": f"/p{plant}/div{div}/l{line}",
                            "work_dir": work_dir,
                            "status": "STOPPED",
                            "editor_url": f"/p{plant}/div{div}/l{line}/editor",
                            "home_url": f"/p{plant}/div{div}/l{line}/home",
                            "pm2_managed": False
                        }
                        changed = True

        # 2. Sync from PM2 active processes
        if self.pm2_adapter and self.pm2_adapter.is_available():
            pm2_procs = self.pm2_adapter.list_processes()
            for p in pm2_procs:
                p_name = p.get("name", "")
                p_status = p.get("pm2_env", {}).get("status", "unknown")
                args = p.get("pm2_env", {}).get("args", [])
                
                # Check if this PM2 process is an instance of FUXA
                port = None
                if isinstance(args, list):
                    for i, a in enumerate(args):
                        if a in ("-p", "--port") and i + 1 < len(args):
                            try:
                                port = int(args[i + 1])
                            except ValueError:
                                pass
                elif isinstance(args, str):
                    m = re.search(r"(-p|--port)\s+(\d+)", args)
                    if m:
                        port = int(m.group(2))

                if port:
                    # Match or create registry entry
                    matched = False
                    for inst in self.registry.get("instances", {}).values():
                        if inst.get("port") == port:
                            inst["pm2_name"] = p_name
                            inst["status"] = "RUNNING" if p_status == "online" else "STOPPED"
                            inst["pm2_managed"] = True
                            matched = True
                            changed = True
                            break

                    if not matched:
                        # Auto-register this PM2 process as an active View or Storage instance
                        port_str = str(port)
                        plant = int(port_str[0]) if len(port_str) >= 4 else 9
                        div = int(port_str[1]) if len(port_str) >= 4 else 6
                        line = int(port_str[2]) if len(port_str) >= 4 else 1

                        self.registry.setdefault("instances", {})[p_name] = {
                            "id": p_name,
                            "name": p_name,
                            "plant": plant,
                            "division": div,
                            "line": line,
                            "port": port,
                            "subpath": f"/p{plant}/div{div}/l{line}",
                            "work_dir": p.get("pm2_env", {}).get("pm_cwd", ""),
                            "status": "RUNNING" if p_status == "online" else "STOPPED",
                            "editor_url": f"http://127.0.0.1:{port}/editor",
                            "home_url": f"http://127.0.0.1:{port}/home",
                            "pm2_managed": True
                        }
                        changed = True

        if changed:
            self._save_registry()

    def get_port_matrix(self):
        """Returns visual port map & live PM2 resource status for all plants"""
        matrix = []
        plants = self.registry.get("plants", {})
        instances = self.registry.get("instances", {})

        # Query PM2 for real-time stats
        pm2_status_map = {}
        if self.pm2_adapter and self.pm2_adapter.is_available():
            for p in self.pm2_adapter.list_processes():
                p_name = p.get("name")
                monit = p.get("monit", {})
                pm2_env = p.get("pm2_env", {})
                pm2_status_map[p_name] = {
                    "status": pm2_env.get("status", "unknown"),
                    "cpu": monit.get("cpu", 0),
                    "memory_mb": round(monit.get("memory", 0) / (1024 * 1024), 1)
                }

        for p_id, p_info in plants.items():
            storage_port = p_info["storage_port"]
            storage_pm2_name = p_info.get("storage_pm2_name", "")
            
            is_socket_online = self.is_port_in_use(storage_port)
            pm2_info = pm2_status_map.get(storage_pm2_name, {})
            is_pm2_online = pm2_info.get("status") == "online"

            plant_data = {
                "plant_id": p_id,
                "name": p_info["name"],
                "storage_port": storage_port,
                "storage_pm2_name": storage_pm2_name,
                "storage_online": is_socket_online or is_pm2_online,
                "storage_cpu": pm2_info.get("cpu", 0),
                "storage_memory": pm2_info.get("memory_mb", 0),
                "instances": []
            }

            for inst_id, inst in instances.items():
                if str(inst.get("plant")) == str(p_id):
                    inst_copy = dict(inst)
                    inst_pm2_name = inst.get("pm2_name") or inst_id
                    inst_pm2_data = pm2_status_map.get(inst_pm2_name, {})

                    is_live = self.is_port_in_use(inst["port"]) or (inst_pm2_data.get("status") == "online")
                    inst_copy["is_live"] = is_live
                    inst_copy["cpu"] = inst_pm2_data.get("cpu", 0)
                    inst_copy["memory_mb"] = inst_pm2_data.get("memory_mb", 0)
                    inst_copy["pm2_status"] = inst_pm2_data.get("status", "untracked")
                    plant_data["instances"].append(inst_copy)

            matrix.append(plant_data)

        return matrix
