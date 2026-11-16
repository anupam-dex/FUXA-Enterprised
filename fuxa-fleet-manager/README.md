# 🦅 FUXA Enterprise Fleet Manager

Autonomous SCADA Fleet Orchestrator built to host, provision, and control all **Plant Storage Servers** and **Line View Servers** on its own via PM2, with zero manual interventions.

---

## 🎯 Architecture

```text
                      [ FUXA Enterprise Fleet Manager (:9000) ]
                      - Autonomous Orchestrator & Port Engine
                      - Programmatic PM2 Lifecycle Management
                      - Automated Nginx WebSocket & Reverse Proxy Reloader
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 ▼                                           ▼
   [ Plant Storage Servers ]                   [ Deployed View Servers ]
   - Plant 9 Paintshop (:5801)                 - Line 1 Oven (:9610)
   - Plant 1 Foundry (:5100)                   - Line 2 Booth (:9620)
   - Master PLC Poller & InfluxDB              - Managed directly in PM2
   - Hosts OPC-UA Bridge (:4840)               - Pure OPC-UA Storage Consumers
```

---

## 🚀 How to Run the Fleet Manager

You only need to run the **Enterprise Fleet Manager**:

```bash
cd /home/aiml/FUXA-Enterprised/fuxa-fleet-manager
chmod +x start_manager.sh
./start_manager.sh
```

Or run the Manager in the background via PM2:
```bash
pm2 start ecosystem.manager.json
pm2 save
```

Open your browser at:
👉 **`http://<SERVER_IP>:9000`**

---

## ⚡ What it Automates

1. **Autonomous View Server Creation**:
   - In the Manager UI, choose Plant, Division, Line, and Title.
   - Click **"Launch View Server in PM2"**.
   - The Manager automatically calculates the deterministic port (e.g. Plant 9, Div 6, Line 1 $\rightarrow$ `9610`), generates a clean SQLite project database with OPC-UA connection to the Storage Server, registers it in PM2 (`pm2 save`), and generates the Nginx reverse-proxy configuration.

2. **Auto-Discovery of Manually Created View Servers**:
   - If you ever launch an instance manually or create a new port folder, click **"Auto-Sync PM2"** or reload the page.
   - The Manager automatically discovers active PM2 processes and incorporates them into the live topology.

3. **Storage Server Lifecycle Control**:
   - Master Plant Storage Servers (e.g., `P9_Storage_Server` on port `5810`) can be monitored, started, stopped, or restarted directly from the UI.

4. **Nginx Automation**:
   - Every provisioned View Server generates an isolated Nginx configuration in `nginx/conf.d/`.
   - The Manager automatically validates configuration (`nginx -t`) and reloads Nginx (`nginx -s reload` / `systemctl reload nginx`).
