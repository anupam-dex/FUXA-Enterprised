#!/usr/bin/env python3
"""
FUXA Industrial Driver Installer Utility
Installs node-opcua and modbus-serial directly into the server runtime,
activating OPCUA and Modbus in the FUXA "Add Device" dropdown.
"""

import os
import sys
import shutil
import subprocess

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_dir = os.path.join(base_dir, "server")

    if not os.path.exists(server_dir):
        print(f"[X] server directory not found at {server_dir}")
        sys.exit(1)

    npm_bin = shutil.which("npm")
    if not npm_bin:
        # Check adjacent to active node executable
        node_dir = os.path.dirname(sys.executable)
        for cand in ["/usr/bin/npm", "/usr/local/bin/npm", os.path.join(node_dir, "npm")]:
            if os.path.exists(cand):
                npm_bin = cand
                break

    if not npm_bin:
        print("[X] npm not found on PATH. Please install node/npm or check PATH.")
        sys.exit(1)

    print("=====================================================")
    print(" Installing FUXA Industrial Communication Drivers")
    print(" (node-opcua, modbus-serial, nodes7)")
    print("=====================================================")
    print(f"[1/3] Running npm install in {server_dir}...")

    cmd = [npm_bin, "install", "node-opcua@^2.149.0", "modbus-serial@^8.0.19", "--no-audit", "--no-fund", "--save"]
    res = subprocess.run(cmd, cwd=server_dir)
    if res.returncode != 0:
        print(f"[X] npm install exited with code {res.returncode}")
        sys.exit(res.returncode)

    print("[2/3] Drivers installed successfully.")

    pm2_bin = shutil.which("pm2")
    if pm2_bin:
        print("[3/3] Restarting PM2 process...")
        subprocess.run([pm2_bin, "restart", "P9_Storage_Server", "--update-env"])
        print("[✓] PM2 restarted.")
    else:
        print("[i] PM2 CLI not found. Restart your FUXA server to reload plugins.")

    print("\n[✓] Done! Refresh your browser and open FUXA -> Devices -> '+' Add Device.")
    print("    OPCUA and Modbus are now available in the Type dropdown.")

if __name__ == "__main__":
    main()
