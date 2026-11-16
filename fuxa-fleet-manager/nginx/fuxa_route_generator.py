#!/usr/bin/env python3
"""
Nginx Route Generator for FUXA Fleet
Generates isolated reverse proxy location blocks with WebSockets and BASE_PATH support.
Attempts automatic test and reload of system Nginx.
"""

import os
import shutil
import subprocess
import logging

logger = logging.getLogger("NginxGenerator")

NGINX_TEMPLATE = """# Auto-generated route for {{ project_name }}
# Plant {{ plant }}, Division {{ division }}, Line {{ line }} -> Port {{ port }}

location {{ subpath }}/socket.io/ {
    proxy_pass http://127.0.0.1:{{ port }}/socket.io/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}

location {{ subpath }}/ {
    proxy_pass http://127.0.0.1:{{ port }}/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
}
"""

def generate_nginx_conf(plant: int, division: int, line: int, port: int, project_name: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    subpath = f"/p{plant}/div{division}/l{line}"
    conf_content = NGINX_TEMPLATE \
        .replace("{{ plant }}", str(plant)) \
        .replace("{{ division }}", str(division)) \
        .replace("{{ line }}", str(line)) \
        .replace("{{ port }}", str(port)) \
        .replace("{{ project_name }}", project_name) \
        .replace("{{ subpath }}", subpath)

    filename = f"fuxa_p{plant}_d{division}_l{line}_{port}.conf"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(conf_content)

    # Optional: If running on a Linux host with writable /etc/nginx/conf.d/, copy it over
    system_conf_d = "/etc/nginx/conf.d"
    if os.path.isdir(system_conf_d) and os.access(system_conf_d, os.W_OK):
        try:
            shutil.copy2(filepath, os.path.join(system_conf_d, filename))
            logger.info(f"Copied Nginx configuration to {system_conf_d}/{filename}")
        except Exception as e:
            logger.warning(f"Could not copy to {system_conf_d}: {e}")

    return filepath, subpath

def reload_nginx():
    """
    Attempts to test and reload system Nginx safely.
    Returns (success: bool, message: str)
    """
    nginx_bin = shutil.which("nginx")
    if not nginx_bin:
        return False, "Nginx binary not found on host"

    try:
        # Test configuration first
        res = subprocess.run([nginx_bin, "-t"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            # Try with sudo if non-root
            res = subprocess.run(["sudo", "-n", "nginx", "-t"], capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                return False, f"Nginx test failed: {res.stderr.strip()}"

        # Reload
        reload_res = subprocess.run(["sudo", "-n", "systemctl", "reload", "nginx"], capture_output=True, text=True, timeout=5)
        if reload_res.returncode == 0:
            return True, "Nginx reloaded successfully via systemctl"

        reload_res = subprocess.run([nginx_bin, "-s", "reload"], capture_output=True, text=True, timeout=5)
        if reload_res.returncode == 0:
            return True, "Nginx reloaded successfully via signal"

        return False, "Nginx reload requires manual sudo or systemctl permissions"
    except Exception as e:
        return False, f"Nginx reload error: {str(e)}"
