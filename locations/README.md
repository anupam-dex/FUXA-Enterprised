# 🏭 FUXA Enterprise Multi-Location Directory

This directory categorizes and isolates all physical plant configurations, screen designs, and runtime databases across your manufacturing lines.

---

## 📁 Directory Structure

```text
locations/
│
├── 📁 storage/                               <-- [MASTER PLC COLLECTORS]
│   └── 📁 plant_9/                           • Plant 9 (Paintshop) Master Storage
│       ├── _appdata/project.fuxap.db         • Physical PLC drivers (S7, Modbus, OPC-UA)
│       └── _logs/                            • Tag ingestion logs
│
└── 📁 views/                                 <-- [SCREEN DESIGNS FOR EACH LOCATION]
    ├── 📁 p9_div6_l1_port9610/               • Line 1 Paintshop Oven (Port 9610)
    │   ├── _appdata/project.fuxap.db         • Isolated SQLite DB holding Line 1 screens & SVG drawings
    │   ├── _images/                          • Line 1 floorplans & custom icons
    │   └── _logs/                            • Line 1 runtime logs
    │
    ├── 📁 p9_div6_l2_port9620/               • Line 2 Paintshop Booth (Port 9620)
    │   ├── _appdata/project.fuxap.db         • Isolated SQLite DB holding Line 2 screens & SVG drawings
    │   ├── _images/                          • Line 2 floorplans & custom icons
    │   └── _logs/                            • Line 2 runtime logs
    │
    └── 📁 ...                                • Additional lines auto-provisioned by Fleet Manager
```

---

## 🔒 Isolation Benefits

1. **Independent Screen Projects**:
   Engineers drawing screens for Line 1 on Port 9610 edit ONLY `locations/views/p9_div6_l1_port9610/_appdata/project.fuxap.db`. They can never accidentally break Line 2's screens or the master PLC connections.

2. **Zero PLC Load**:
   View instances only communicate with the Master Storage Server via OPC-UA. They never connect directly to factory PLCs.

3. **Autonomous PM2 Synchronization**:
   Every folder in `locations/views/` is managed directly by PM2 and the **FUXA Enterprise Fleet Manager** (:9000).
