// FUXA Fleet Manager - Professional Topological SCADA Orchestrator

let currentMatrix = [];
let allInstancesMap = {};
let selectedPlantFilter = 'all';
let searchQuery = '';

async function loadMatrix() {
    try {
        const res = await fetch('/api/matrix');
        const data = await res.json();
        currentMatrix = data.matrix || [];
        if (data.watchdog) {
            updateWatchdogHeader(data.watchdog);
        }
        renderTopology(currentMatrix);
    } catch (err) {
        console.error("Failed to load matrix:", err);
    }
}

function renderTopology(matrix) {
    allInstancesMap = {};
    let totalInstances = 0;
    const plantStrip = document.getElementById('plant-strip');
    const filterPills = document.getElementById('filter-pills-bar');
    
    plantStrip.innerHTML = '';
    
    // Header Filter Pills setup
    let pillsHtml = `<button class="filter-pill ${selectedPlantFilter === 'all' ? 'active' : ''}" onclick="setPlantFilter('all')">All Plants</button>`;
    let totalFaults = 0;

    matrix.forEach(plant => {
        const pId = plant.plant_id;
        const pCount = (plant.instances || []).length;
        totalInstances += pCount;

        if (!plant.storage_online) totalFaults++;

        plant.instances.forEach(inst => {
            allInstancesMap[inst.id] = { ...inst, plant_name: plant.name, storage_port: plant.storage_port };
            if (!inst.is_live && !inst.user_stopped) totalFaults++;
        });

        // Add filter pill
        pillsHtml += `<button class="filter-pill ${selectedPlantFilter === String(pId) ? 'active' : ''}" onclick="setPlantFilter('${pId}')">${plant.name.split(' - ')[0]} (${pCount})</button>`;

        // Plant Strip Card
        const isSelected = selectedPlantFilter === String(pId);
        const card = document.createElement('div');
        card.className = `plant-strip-card ${isSelected ? 'active' : ''}`;
        card.onclick = () => setPlantFilter(isSelected ? 'all' : String(pId));

        const storageOnline = plant.storage_online;
        const storageChipHtml = storageOnline ? `
            <span class="storage-chip" onclick="event.stopPropagation(); window.open('http://' + (window.location.hostname || '127.0.0.1') + ':${plant.storage_port}/editor', '_blank')" title="Click to open Plant ${pId} Storage Server (Field Connections & InfluxDB)" style="cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#38bdf8'" onmouseout="this.style.borderColor=''">
                <span class="dot live"></span> Storage :${plant.storage_port} ↗
            </span>
        ` : `
            <span class="storage-chip" onclick="event.stopPropagation(); openStorageDiagnosticsModal('${pId}')" title="Storage Master Down! Click to inspect fault" style="cursor: pointer; border-color: #ef4444; background: rgba(239, 68, 68, 0.15); color: #fca5a5;">
                <span class="dot" style="background: #ef4444;"></span> Storage :${plant.storage_port} (DOWN) 🩺
            </span>
        `;

        card.innerHTML = `
            <div class="plant-strip-top">
                <div>
                    <div class="plant-strip-name">${plant.name}</div>
                    <div class="plant-strip-id">Plant ID: ${pId}</div>
                </div>
                <span class="views-count-pill ${pCount > 0 ? 'has-active' : ''}">${pCount} Active</span>
            </div>
            <div class="plant-strip-bottom" style="display: flex; gap: 6px; align-items: center;">
                ${storageChipHtml}
                <button onclick="event.stopPropagation(); openStorageImportModal('${pId}')" title="Import & Deduplicate Devices into Plant ${pId} Storage Server" style="background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.4); color: #fbbf24; border-radius: 4px; padding: 3px 8px; font-size: 0.72rem; font-weight: 700; cursor: pointer;">
                    📥 Import Devices
                </button>
                <button onclick="event.stopPropagation(); openBulkHistoryModal('${pId}')" title="Configure Bulk Historical DAQ for Plant ${pId}" style="background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.4); color: #60a5fa; border-radius: 4px; padding: 3px 8px; font-size: 0.72rem; font-weight: 700; cursor: pointer;">
                    📈 Bulk DAQ
                </button>
                <span style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono); margin-left: auto;">InfluxDB Master</span>
            </div>
        `;
        plantStrip.appendChild(card);
    });

    filterPills.innerHTML = pillsHtml;

    // Update global telemetry counters
    document.getElementById('stat-views-total').textContent = totalInstances;
    document.getElementById('pipe-active-count').textContent = `${totalInstances} Deployed Lines`;

    const faultPill = document.getElementById('pill-fleet-faults');
    const faultCountEl = document.getElementById('stat-faults-count');
    if (faultPill && faultCountEl) {
        faultCountEl.textContent = totalFaults;
        faultPill.style.display = totalFaults > 0 ? 'flex' : 'none';
    }

    renderInstancesList();
}

function setPlantFilter(plantId) {
    selectedPlantFilter = plantId;
    renderTopology(currentMatrix);
}

function handleSearchInput() {
    searchQuery = (document.getElementById('filter-search')?.value || '').toLowerCase().trim();
    renderInstancesList();
}

function renderInstancesList() {
    const list = document.getElementById('instances-list');
    list.innerHTML = '';

    const host = window.location.hostname || '127.0.0.1';
    const proto = window.location.protocol || 'http:';

    let instances = Object.values(allInstancesMap);

    // Apply plant filter
    if (selectedPlantFilter !== 'all') {
        instances = instances.filter(i => String(i.plant) === String(selectedPlantFilter));
    }

    // Apply search filter
    if (searchQuery) {
        instances = instances.filter(i => 
            (i.name && i.name.toLowerCase().includes(searchQuery)) ||
            (i.subpath && i.subpath.toLowerCase().includes(searchQuery)) ||
            (String(i.port).includes(searchQuery)) ||
            (i.plant_name && i.plant_name.toLowerCase().includes(searchQuery))
        );
    }

    if (instances.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 6px;">No view servers found matching this view</div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 14px;">
                    ${selectedPlantFilter !== 'all' ? `Plant ${selectedPlantFilter} currently has no active HMI view servers deployed.` : 'Get started by creating your first distributed view server.'}
                </div>
                <button class="btn btn-primary btn-sm" onclick="openCreateModal()">+ Create New Project</button>
            </div>
        `;
        return;
    }

    instances.forEach(inst => {
        const row = document.createElement('div');
        row.className = 'instance-card-row';
        const isLive = inst.is_live;
        const isFaulted = !isLive && !inst.user_stopped;

        if (isFaulted) {
            row.style.borderColor = '#ef4444';
            row.style.background = 'rgba(239, 68, 68, 0.04)';
        }

        // OT Clean URLs without port numbers (Port 80 Reverse Proxy)
        const otEditor = `${proto}//${host}${inst.subpath}/editor`;
        const otView = `${proto}//${host}${inst.subpath}/home`;

        const dotClass = isLive ? 'dot live' : (isFaulted ? 'dot' : 'dot');
        const dotStyle = isLive ? '' : (isFaulted ? 'background: #ef4444;' : 'background: #64748b;');

        const faultBarHtml = !isLive ? `
            <div style="grid-column: 1 / -1; background: ${isFaulted ? 'rgba(239, 68, 68, 0.12)' : 'rgba(30, 41, 59, 0.6)'}; border: 1px solid ${isFaulted ? '#ef4444' : '#334155'}; border-radius: 6px; padding: 7px 12px; margin-top: 10px; display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 0.8rem; color: ${isFaulted ? '#fca5a5' : '#94a3b8'};">
                    <strong>${isFaulted ? '⚠️ CRITICAL FAULT:' : '⏹️ STATUS:'}</strong> ${inst.fault_diagnostic?.fault_summary || (isFaulted ? 'Server down' : 'Stopped by user')}
                    <span style="color: #cbd5e1; font-size: 0.74rem; margin-left: 8px;">— ${inst.fault_diagnostic?.fault_details || ''}</span>
                </div>
                <div style="display: flex; gap: 6px;">
                    <button onclick="openDiagnosticsModal('${inst.id}')" class="btn btn-sm btn-secondary" style="font-size: 0.72rem; padding: 3px 8px; border-color: #38bdf8; color: #38bdf8;">🩺 Diagnostics & Logs</button>
                    <button onclick="triggerInstanceSelfHeal('${inst.id}')" class="btn btn-sm btn-primary" style="font-size: 0.72rem; padding: 3px 8px; background: #10b981; border-color: #059669;">⚡ 1-Click Heal</button>
                </div>
            </div>
        ` : '';

        row.innerHTML = `
            <!-- Col 1: Server Identity & Plant -->
            <div class="col-server">
                <div class="title-row">
                    <span class="${dotClass}" style="${dotStyle}" title="Instance Status"></span>
                    <span class="name">${inst.name}</span>
                </div>
                <div class="plant-tag">${inst.plant_name || `Plant ${inst.plant}`} &bull; Div ${inst.division || 6} (Line ${inst.line || 1})</div>
            </div>

            <!-- Col 2: Ports & Subpath -->
            <div class="col-routing">
                <div class="port-badge" title="Internal backend process port" style="${!isLive ? 'border-color: #ef4444; color: #fca5a5;' : ''}">Port: ${inst.port}</div>
                <div class="subpath-badge">${inst.subpath}</div>
                <button onclick="copyInstanceApiKey('${inst.id}')" class="subpath-badge" style="background: rgba(147, 51, 234, 0.15); border: 1px solid rgba(147, 51, 234, 0.4); color: #c084fc; cursor: pointer; display: flex; align-items: center; gap: 4px; margin-top: 4px;" title="Click to view & copy API Key / Secret">
                    <span>🔑</span> API Key
                </button>
            </div>

            <!-- Col 3: Data Source -->
            <div class="col-data-source">
                <div class="source-label">Source Bridge</div>
                <div class="source-val">Storage :${inst.storage_port || 5900}</div>
                <div class="tag-badge" title="Active Storage Tags Ingested">🏷️ ${inst.tag_count || 11} Tags</div>
            </div>

            <!-- Col 4: OT Port 80 Clean Reverse Proxy Link -->
            <div class="col-ot-link">
                <a href="${otView}" target="_blank" class="ot-link-pill" title="Open Clean OT View (Port 80 - No Port Number)">
                    <span>🌐</span> ${inst.subpath}/view
                </a>
            </div>

            <!-- Col 5: Actions -->
            <div class="col-actions">
                ${isLive ? `
                    <a href="${otEditor}" target="_blank" class="btn btn-primary btn-sm" title="Open Editor (Port 80 - No Port Number)">Editor</a>
                    <a href="${otView}" target="_blank" class="btn btn-secondary btn-sm" title="Open Operator View (Port 80 - No Port Number)">View</a>
                ` : `
                    <button onclick="triggerInstanceSelfHeal('${inst.id}')" class="btn btn-primary btn-sm" style="background: #10b981; border-color: #059669;" title="Auto-Heal & Launch Server">▶ Heal & Start</button>
                    <button onclick="openDiagnosticsModal('${inst.id}')" class="btn btn-secondary btn-sm" style="color: #38bdf8;" title="View Exact Fault Diagnostics">🩺 Diag</button>
                `}
                <button onclick="openMigrateModal('${inst.id}', 'view')" class="btn btn-secondary btn-sm" title="Import Dashboards (.json/.fuxap) into this View Server" style="color: #fbbf24; border-color: rgba(245, 158, 11, 0.4);">📥 Import</button>
                <button onclick="syncTags('${inst.id}')" class="btn btn-secondary btn-sm" title="Sync Plant Storage Tags into this View Server">🔄 Sync Tags</button>
                <button onclick="editInstance('${inst.id}')" class="btn btn-secondary btn-sm" title="Edit View Server">✏️ Edit</button>
                <button onclick="viewLogs('${inst.id}')" class="btn btn-secondary btn-sm" title="View Logs">Logs</button>
                <button onclick="deleteInstance('${inst.id}')" class="btn btn-danger btn-sm" title="Delete Instance">&#128465;</button>
            </div>
            ${faultBarHtml}
        `;
        list.appendChild(row);
    });
}

function openCreateModal() {
    document.getElementById('create-modal').classList.add('show');
    updatePortPreview();
}

function closeCreateModal() {
    document.getElementById('create-modal').classList.remove('show');
}

function updatePortPreview() {
    const plant = document.getElementById('sel-plant').value;
    const div = document.getElementById('sel-div').value;
    const line = document.getElementById('input-line').value || '1';

    document.getElementById('p-calc-plant').textContent = plant;
    document.getElementById('p-calc-div').textContent = div;
    document.getElementById('p-calc-line').textContent = line;

    const basePort = `${plant}${div}${line}0`;
    const portInput = document.getElementById('input-custom-port');
    if (portInput) {
        portInput.value = basePort;
    }

    const defaultSub = `/p${plant}/div${div}/l${line}`;
    const subInput = document.getElementById('input-subpath');
    if (subInput && (!subInput.value || subInput.value.startsWith('/p'))) {
        subInput.value = defaultSub;
    }
    document.getElementById('subpath-preview').textContent = subInput ? subInput.value : defaultSub;
}

async function submitCreateProject() {
    const plant = parseInt(document.getElementById('sel-plant').value);
    const div = parseInt(document.getElementById('sel-div').value);
    const line = parseInt(document.getElementById('input-line').value || '1');
    const name = document.getElementById('input-name').value || `Plant ${plant} Div ${div} Line ${line}`;
    const customSubpath = (document.getElementById('input-subpath')?.value || '').trim();
    const customPort = parseInt(document.getElementById('input-custom-port')?.value || '0', 10);

    const btn = document.getElementById('btn-submit');
    btn.disabled = true;
    btn.textContent = 'Provisioning...';

    try {
        const res = await fetch('/api/create-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plant: plant,
                division: div,
                line: line,
                project_name: name,
                custom_subpath: customSubpath,
                custom_port: customPort > 0 ? customPort : undefined
            })
        });

        const data = await res.json();
        if (data.success) {
            closeCreateModal();
            loadMatrix();
            alert(`Instance Created Successfully!\n\nPort: ${data.instance.port}\nSubpath: ${data.instance.subpath}\n\nPre-loaded with Central OPC-UA Bridge connection!`);
        } else {
            alert('Failed to create instance: ' + (data.detail || 'Unknown error'));
        }
    } catch (err) {
        alert('Error: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Launch View Server';
    }
}

async function deleteInstance(id) {
    if (confirm(`Are you sure you want to delete instance ${id}?`)) {
        await fetch(`/api/instances/${id}`, { method: 'DELETE' });
        loadMatrix();
    }
}

function editInstance(id) {
    const inst = allInstancesMap[id];
    if (!inst) return;
    document.getElementById('edit-instance-id').value = id;
    document.getElementById('edit-sel-plant').value = inst.plant !== undefined ? inst.plant : 9;
    document.getElementById('edit-sel-div').value = inst.division !== undefined ? inst.division : 6;
    document.getElementById('edit-input-line').value = inst.line !== undefined ? inst.line : 1;
    document.getElementById('edit-input-name').value = inst.name || '';
    document.getElementById('edit-input-subpath').value = inst.subpath || '';
    const port = inst.port || 9610;
    document.getElementById('edit-input-port').value = port;
    document.getElementById('edit-port-calc-result').textContent = port;
    document.getElementById('edit-modal').classList.add('show');
}

function closeEditModal() {
    document.getElementById('edit-modal').classList.remove('show');
}

async function submitEditInstance() {
    const id = document.getElementById('edit-instance-id').value;
    const plant = parseInt(document.getElementById('edit-sel-plant').value);
    const div = parseInt(document.getElementById('edit-sel-div').value);
    const line = parseInt(document.getElementById('edit-input-line').value || '1');
    const name = document.getElementById('edit-input-name').value.trim();
    const subpath = document.getElementById('edit-input-subpath').value.trim();
    const port = parseInt(document.getElementById('edit-input-port')?.value || '0', 10);
    const btn = document.getElementById('btn-save-edit');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const res = await fetch(`/api/instances/${id}/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                subpath: subpath,
                plant: plant,
                division: div,
                line: line,
                port: port > 0 ? port : undefined
            })
        });
        const data = await res.json();
        if (data.success) {
            closeEditModal();
            loadMatrix();
        } else {
            alert('Failed: ' + (data.detail || 'Unknown error'));
        }
    } catch (e) {
        alert('Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Save & Route';
    }
}

async function viewLogs(id) {
    const modal = document.getElementById('logs-modal');
    const content = document.getElementById('logs-content');
    const title = document.getElementById('logs-title');

    modal.classList.add('show');
    title.textContent = `Live Logs: ${id}`;
    content.textContent = 'Loading logs...';

    try {
        const res = await fetch(`/api/instances/${id}/logs`);
        const data = await res.json();
        content.textContent = data.logs || 'No logs available.';
        content.scrollTop = content.scrollHeight;
    } catch (e) {
        content.textContent = 'Error loading logs: ' + e.message;
    }
}

function closeLogsModal() {
    document.getElementById('logs-modal').classList.remove('show');
}

async function syncTags(id) {
    try {
        const res = await fetch(`/api/instances/${id}/sync-tags`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            alert(`✓ ${data.message}`);
            loadMatrix();
        } else {
            alert('Failed to sync tags: ' + (data.detail || 'Unknown error'));
        }
    } catch (e) {
        alert('Error syncing tags: ' + e.message);
    }
}

async function syncAllTags() {
    try {
        const res = await fetch('/api/sync-all-tags', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            alert(`✓ ${data.message}`);
            loadMatrix();
        } else {
            alert('Failed to sync all tags: ' + (data.detail || 'Unknown error'));
        }
    } catch (e) {
        alert('Error syncing all tags: ' + e.message);
    }
}

// =============================================================================
// OT Reliability: Process Watchdog Functions
// =============================================================================
let currentWatchdogData = null;

function updateWatchdogHeader(wd) {
    currentWatchdogData = wd;
    const textEl = document.getElementById('stat-watchdog-text');
    const dotEl = document.getElementById('dot-watchdog');
    if (!textEl) return;
    if (wd.enabled) {
        textEl.textContent = `Active (${wd.auto_recoveries || 0} Heals)`;
        textEl.style.color = '#10b981';
        if (dotEl) {
            dotEl.className = 'dot live';
        }
    } else {
        textEl.textContent = 'PAUSED';
        textEl.style.color = '#f59e0b';
        if (dotEl) {
            dotEl.className = 'dot';
            dotEl.style.background = '#f59e0b';
        }
    }
}

async function openWatchdogModal() {
    const modal = document.getElementById('watchdog-modal');
    modal.classList.add('show');
    await refreshWatchdogModal();
}

function closeWatchdogModal() {
    document.getElementById('watchdog-modal').classList.remove('show');
}

async function refreshWatchdogModal() {
    try {
        const res = await fetch('/api/watchdog/status');
        const data = await res.json();
        currentWatchdogData = data;
        
        const statusEl = document.getElementById('wd-stat-status');
        if (statusEl) {
            statusEl.textContent = data.enabled ? 'ACTIVE' : 'PAUSED';
            statusEl.style.color = data.enabled ? '#10b981' : '#f59e0b';
        }
        const scansEl = document.getElementById('wd-stat-scans');
        if (scansEl) scansEl.textContent = data.total_checks || 0;
        const recovEl = document.getElementById('wd-stat-recoveries');
        if (recovEl) recovEl.textContent = data.auto_recoveries || 0;
        
        const btnToggle = document.getElementById('btn-toggle-watchdog');
        if (btnToggle) {
            btnToggle.textContent = data.enabled ? 'Pause Watchdog' : 'Resume Watchdog';
        }

        const list = document.getElementById('wd-events-list');
        if (!list) return;
        const events = data.events || [];
        if (events.length === 0) {
            list.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 18px;">🛡️ All monitored processes healthy. No crash recovery events recorded.</div>';
            return;
        }

        let html = '';
        events.forEach(ev => {
            const isRecov = ev.type.includes('RECOVER') || ev.type === 'RECOVERY';
            const color = isRecov ? '#fbbf24' : (ev.type === 'RESTORE' ? '#38bdf8' : '#94a3b8');
            html += `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; padding: 6px 4px; border-bottom: 1px solid rgba(255,255,255,0.05); gap: 10px;">
                    <div>
                        <span style="color: ${color}; font-weight: 700;">[${ev.type}]</span>
                        <strong style="color: #f1f5f9; margin-left: 6px;">${ev.target}:</strong>
                        <span style="color: #cbd5e1; margin-left: 4px;">${ev.message}</span>
                    </div>
                    <span style="color: var(--text-muted); font-size: 0.72rem; white-space: nowrap; flex-shrink: 0;">${ev.timestamp}</span>
                </div>
            `;
        });
        list.innerHTML = html;
    } catch (e) {
        console.error("Watchdog modal error:", e);
    }
}

async function toggleWatchdog() {
    try {
        const res = await fetch('/api/watchdog/toggle', { method: 'POST' });
        const data = await res.json();
        await refreshWatchdogModal();
        loadMatrix();
    } catch (e) {
        alert("Could not toggle watchdog: " + e.message);
    }
}

// =============================================================================
// OT Reliability: 1-Click Disaster Recovery & Backup Snapshots
// =============================================================================
async function openBackupModal() {
    const modal = document.getElementById('backup-modal');
    modal.classList.add('show');
    await loadBackupsList();
}

function closeBackupModal() {
    document.getElementById('backup-modal').classList.remove('show');
}

async function loadBackupsList() {
    const container = document.getElementById('backup-list-container');
    if (!container) return;
    container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">Loading snapshots...</div>';
    
    try {
        const res = await fetch('/api/backup/list');
        const data = await res.json();
        const backups = data.backups || [];

        if (backups.length === 0) {
            container.innerHTML = `
                <div style="padding: 32px 20px; text-align: center; color: var(--text-muted);">
                    <div style="font-size: 1.8rem; margin-bottom: 6px;">📦</div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: #f1f5f9; margin-bottom: 4px;">No backup snapshots found</div>
                    <div style="font-size: 0.78rem;">Click "+ Snapshot Now" above to create your first full disaster recovery archive.</div>
                </div>
            `;
            return;
        }

        let html = `
            <table style="width: 100%; border-collapse: collapse; font-size: 0.82rem; text-align: left;">
                <thead>
                    <tr style="border-bottom: 1px solid #242e3f; color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase;">
                        <th style="padding: 10px 14px;">Snapshot Archive</th>
                        <th style="padding: 10px 14px;">Created</th>
                        <th style="padding: 10px 14px;">Size</th>
                        <th style="padding: 10px 14px;">Instances</th>
                        <th style="padding: 10px 14px; text-align: right;">Actions</th>
                    </tr>
                </thead>
                <tbody>
        `;

        backups.forEach(b => {
            html += `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.15s;" onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='transparent'">
                    <td style="padding: 10px 14px; font-family: monospace; color: #38bdf8; font-weight: 600;">
                        📄 ${b.filename}
                    </td>
                    <td style="padding: 10px 14px; color: #cbd5e1; font-family: monospace; font-size: 0.76rem;">
                        ${b.created_at}
                    </td>
                    <td style="padding: 10px 14px; color: #94a3b8; font-family: monospace;">
                        ${b.size_kb} KB
                    </td>
                    <td style="padding: 10px 14px;">
                        <span style="background: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.25); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 600;">
                            ${b.instances_count} Lines
                        </span>
                    </td>
                    <td style="padding: 10px 14px; text-align: right;">
                        <button onclick="downloadBackup('${b.filename}')" class="btn btn-secondary" style="font-size: 0.72rem; padding: 3px 8px; margin-right: 4px;" title="Download archive to local machine">
                            ⬇ Download
                        </button>
                        <button onclick="confirmRestoreBackup('${b.filename}')" class="btn btn-primary" style="font-size: 0.72rem; padding: 3px 10px; margin-right: 4px; background: linear-gradient(135deg, #10b981, #059669);" title="1-Click Safe Disaster Recovery">
                            🔄 Restore
                        </button>
                        <button onclick="deleteBackup('${b.filename}')" style="background: transparent; border: none; color: #ef4444; font-size: 0.85rem; cursor: pointer; padding: 2px 4px; opacity: 0.8;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.8'" title="Delete Snapshot">
                            🗑️
                        </button>
                    </td>
                </tr>
            `;
        });

        html += `</tbody></table>`;
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div style="padding: 20px; color: #ef4444; text-align: center;">Error loading snapshots: ${e.message}</div>`;
    }
}

async function createFleetBackup() {
    const btn = document.getElementById('btn-create-backup');
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = 'Archiving Fleet...';

    try {
        const res = await fetch('/api/backup/create', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            alert(`✓ Disaster Recovery Snapshot Created!\n\nFile: ${data.filename}\nSize: ${data.size_kb} KB\nLines Included: ${data.instances_count}`);
            await loadBackupsList();
        } else {
            alert("Backup failed: " + (data.detail || "Unknown error"));
        }
    } catch (e) {
        alert("Error creating snapshot: " + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = oldText;
    }
}

function downloadBackup(filename) {
    window.open(`/api/backup/download/${filename}`, '_blank');
}

async function handleBackupUpload(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch('/api/backup/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            alert(`✓ Backup archive "${data.filename}" uploaded successfully!`);
            await loadBackupsList();
        } else {
            alert("Upload failed: " + (data.detail || "Unknown error"));
        }
    } catch (e) {
        alert("Error uploading backup: " + e.message);
    } finally {
        event.target.value = '';
    }
}

async function confirmRestoreBackup(filename) {
    const confirmed = confirm(
        `⚠️ WARNING: 1-Click Disaster Recovery Restore\n\n` +
        `Restoring snapshot "${filename}" will safely stop all running lines, replace databases with this snapshot, and re-launch all restored servers.\n\n` +
        `Do you want to proceed with full fleet restore?`
    );

    if (!confirmed) return;

    try {
        const res = await fetch('/api/backup/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        });
        const data = await res.json();
        if (data.success) {
            alert(`✓ ${data.message}`);
            closeBackupModal();
            loadMatrix();
        } else {
            alert("Restore failed: " + (data.detail || "Unknown error"));
        }
    } catch (e) {
        alert("Error restoring snapshot: " + e.message);
    }
}

async function deleteBackup(filename) {
    if (!confirm(`Delete snapshot archive "${filename}"?`)) return;

    try {
        const res = await fetch(`/api/backup/${filename}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            await loadBackupsList();
        } else {
            alert("Delete failed: " + (data.detail || "Unknown error"));
        }
    } catch (e) {
        alert("Error deleting snapshot: " + e.message);
    }
}

// ==============================================================================
// 1-Click Dashboard & View Migration (project.json / .fuxap)
// ==============================================================================
let selectedMigrateFile = null;
let selectedMigrateFiles = [];
let migrateSourceMode = 'file'; // 'file' or 'url'
let migrateDestination = 'storage'; // 'storage' or 'view'

function setMigrateDestination(dest) {
    migrateDestination = dest;
    const tabStorage = document.getElementById('tab-dest-storage');
    const tabView = document.getElementById('tab-dest-view');
    const boxStorage = document.getElementById('dest-box-storage');
    const boxView = document.getElementById('dest-box-view');
    const optKeep = document.getElementById('opt-row-keep');
    const optClean = document.getElementById('opt-row-clean');
    const optRestart = document.getElementById('opt-row-restart');
    const btn = document.getElementById('btn-execute-migrate');
    const dropSubtext = document.getElementById('dropzone-subtext');

    if (dest === 'storage') {
        if (tabStorage) tabStorage.className = 'btn btn-sm btn-primary';
        if (tabView) tabView.className = 'btn btn-sm btn-secondary';
        if (boxStorage) boxStorage.style.display = 'block';
        if (boxView) boxView.style.display = 'none';
        if (optKeep) optKeep.style.display = 'none';
        if (optClean) optClean.style.display = 'flex';
        if (optRestart) optRestart.style.display = 'flex';
        if (btn) btn.innerHTML = '🚀 Import & Deduplicate Devices to Storage';
        if (dropSubtext) dropSubtext.textContent = 'Select one or multiple project files. Duplicate devices will be automatically merged.';
    } else {
        if (tabStorage) tabStorage.className = 'btn btn-sm btn-secondary';
        if (tabView) tabView.className = 'btn btn-sm btn-primary';
        if (boxStorage) boxStorage.style.display = 'none';
        if (boxView) boxView.style.display = 'block';
        if (optKeep) optKeep.style.display = 'flex';
        if (optClean) optClean.style.display = 'none';
        if (optRestart) optRestart.style.display = 'none';
        if (btn) btn.innerHTML = '🚀 Start 1-Click Dashboard Migration';
        if (dropSubtext) dropSubtext.textContent = 'Supported formats: FUXA project export (.json), FUXA package (.fuxap)';
    }
}

function openStorageImportModal(plantId) {
    openMigrateModal(null, 'storage');
    const plantSel = document.getElementById('migrate-storage-plant');
    if (plantSel) {
        plantSel.value = String(plantId);
    }
}

function openMigrateModal(preselectedInstanceId = null, defaultDestination = null) {
    const modal = document.getElementById('migrate-modal');
    if (!modal) return;

    // Populate target select dropdown
    const select = document.getElementById('migrate-target-select');
    if (select) {
        select.innerHTML = '';
        const instances = Object.values(allInstancesMap);
        if (instances.length === 0) {
            select.innerHTML = '<option value="9610">Default View Server (Port 9610)</option>';
        } else {
            instances.forEach(inst => {
                const opt = document.createElement('option');
                opt.value = inst.id || inst.port;
                opt.textContent = `${inst.name} — ${inst.subpath} (Plant ${inst.plant}, Port ${inst.port})`;
                if (preselectedInstanceId && (inst.id === preselectedInstanceId || String(inst.port) === String(preselectedInstanceId))) {
                    opt.selected = true;
                }
                select.appendChild(opt);
            });
        }
    }

    // Reset file / form state
    selectedMigrateFile = null;
    selectedMigrateFiles = [];
    const fileInput = document.getElementById('migrate-file-input');
    if (fileInput) fileInput.value = '';
    const dropText = document.getElementById('dropzone-text');
    if (dropText) dropText.innerHTML = 'Click to select or drop <span style="color: #fbbf24;">project.json</span> or <span style="color: #38bdf8;">.fuxap</span> files (Multiple supported)';
    const resBox = document.getElementById('migrate-results');
    if (resBox) {
        resBox.style.display = 'none';
        resBox.innerHTML = '';
    }

    // When an instanceId is passed or opening from view server, ALWAYS default destination to 'view'
    const targetDest = defaultDestination || (preselectedInstanceId ? 'view' : 'view');
    setMigrateDestination(targetDest);
    setMigrateSourceMode('file');
    setupDropzone();
    modal.classList.add('show');
}

function closeMigrateModal() {
    const modal = document.getElementById('migrate-modal');
    if (modal) modal.classList.remove('show');
}

function setMigrateSourceMode(mode) {
    migrateSourceMode = mode;
    const tabFile = document.getElementById('tab-upload-file');
    const tabUrl = document.getElementById('tab-upload-url');
    const modeFile = document.getElementById('migrate-mode-file');
    const modeUrl = document.getElementById('migrate-mode-url');

    if (!tabFile || !tabUrl || !modeFile || !modeUrl) return;

    if (mode === 'file') {
        tabFile.className = 'btn btn-sm btn-primary';
        tabUrl.className = 'btn btn-sm btn-secondary';
        modeFile.style.display = 'block';
        modeUrl.style.display = 'none';
    } else {
        tabFile.className = 'btn btn-sm btn-secondary';
        tabUrl.className = 'btn btn-sm btn-primary';
        modeFile.style.display = 'none';
        modeUrl.style.display = 'block';
    }
}

function handleMigrateFileSelect(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    selectedMigrateFiles = files;
    selectedMigrateFile = files[0];
    const dropText = document.getElementById('dropzone-text');
    if (dropText) {
        if (files.length === 1) {
            dropText.innerHTML = `✅ Selected: <strong style="color: #4ade80;">${files[0].name}</strong> (${(files[0].size / 1024).toFixed(1)} KB)`;
        } else {
            dropText.innerHTML = `✅ Selected <strong style="color: #4ade80;">${files.length} project files</strong> (${files.map(f => f.name).slice(0, 3).join(', ')}${files.length > 3 ? '...' : ''})`;
        }
    }
}

function setupDropzone() {
    const dropzone = document.getElementById('dropzone');
    if (!dropzone || dropzone.dataset.hooked) return;
    dropzone.dataset.hooked = 'true';

    ['dragenter', 'dragover'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.style.borderColor = '#fbbf24';
            dropzone.style.background = 'rgba(245, 158, 11, 0.1)';
        });
    });
    ['dragleave', 'drop'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.style.borderColor = '#475569';
            dropzone.style.background = 'rgba(30, 41, 59, 0.4)';
        });
    });
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length > 0) {
            const files = Array.from(dt.files);
            selectedMigrateFiles = files;
            selectedMigrateFile = files[0];
            const dropText = document.getElementById('dropzone-text');
            if (dropText) {
                if (files.length === 1) {
                    dropText.innerHTML = `✅ Selected: <strong style="color: #4ade80;">${files[0].name}</strong> (${(files[0].size / 1024).toFixed(1)} KB)`;
                } else {
                    dropText.innerHTML = `✅ Selected <strong style="color: #4ade80;">${files.length} project files</strong> (${files.map(f => f.name).slice(0, 3).join(', ')}${files.length > 3 ? '...' : ''})`;
                }
            }
        }
    });
}

async function executeProjectMigration() {
    const btn = document.getElementById('btn-execute-migrate');
    const resBox = document.getElementById('migrate-results');
    const dryRun = document.getElementById('migrate-opt-dryrun')?.checked ?? false;

    // A. STORAGE SERVER MODE (Extract & Deduplicate Devices Only)
    if (migrateDestination === 'storage') {
        const plantId = document.getElementById('migrate-storage-plant')?.value || '9';
        const restart = document.getElementById('migrate-opt-restart')?.checked ?? true;

        if (selectedMigrateFiles.length === 0 && !selectedMigrateFile) {
            alert('Please select or drop at least one project.json or .fuxap file.');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '⏳ Deduplicating & Importing Devices...';
        resBox.style.display = 'block';
        resBox.style.background = '#0f172a';
        resBox.style.border = '1px solid #334155';
        resBox.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 12px;">Auditing devices, computing hardware signatures, and merging tags...</div>';

        try {
            const formData = new FormData();
            formData.append('dry_run', dryRun ? 'true' : 'false');
            formData.append('restart', restart ? 'true' : 'false');
            const cleanDev = document.getElementById('migrate-opt-clean')?.checked ?? false;
            formData.append('clean_devices', cleanDev ? 'true' : 'false');
            const autoHist = document.getElementById('migrate-enable-history')?.checked ?? true;
            formData.append('enable_history', autoHist ? 'true' : 'false');
            formData.append('daq_mode', 'change');
            selectedMigrateFiles.forEach(f => formData.append('files', f));

            const resp = await fetch(`/api/storage/${plantId}/import-devices`, {
                method: 'POST',
                body: formData
            });

            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.detail || 'Device import failed');
            }

            const rep = data.report || {};
            resBox.style.background = '#064e3b';
            resBox.style.border = '1px solid #10b981';
            resBox.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: #34d399; font-size: 0.95rem;">
                        ${dryRun ? '🔍 Dry Run Simulation Complete' : '🎉 Devices Successfully Imported to Storage Server!'}
                    </strong>
                    <span style="background: rgba(16, 185, 129, 0.2); color: #6ee7b7; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;">
                        Plant ${plantId} Storage
                    </span>
                </div>
                <div style="grid-template-columns: repeat(4, 1fr); display: grid; gap: 6px; margin: 10px 0; background: rgba(0,0,0,0.25); padding: 8px; border-radius: 6px; text-align: center;">
                    <div><div style="font-size: 1.1rem; font-weight: 800; color: #f8fafc;">${rep.total_incoming_devices || 0}</div><div style="font-size: 0.7rem; color: #94a3b8;">Scanned Devices</div></div>
                    <div><div style="font-size: 1.1rem; font-weight: 800; color: #4ade80;">+${rep.new_devices_added || 0}</div><div style="font-size: 0.7rem; color: #94a3b8;">New Devices</div></div>
                    <div><div style="font-size: 1.1rem; font-weight: 800; color: #fbbf24;">${rep.duplicate_devices_merged || 0}</div><div style="font-size: 0.7rem; color: #94a3b8;">Merged Duplicates</div></div>
                    <div><div style="font-size: 1.1rem; font-weight: 800; color: #38bdf8;">+${rep.new_tags_added || 0}</div><div style="font-size: 0.7rem; color: #94a3b8;">Tags Imported</div></div>
                </div>
                <div style="max-height: 140px; overflow-y: auto; background: #020617; border-radius: 4px; padding: 6px 10px; font-size: 0.75rem; font-family: monospace; color: #cbd5e1; margin-top: 8px;">
                    ${(rep.devices || []).map(d => `
                        <div style="padding: 2px 0; border-bottom: 1px solid #1e293b;">
                            <span style="color: ${d.action === 'CREATED' ? '#4ade80' : '#facc15'}; font-weight: 700;">[${d.action}]</span>
                            <strong>${d.name}</strong> (${d.type}): ${d.action === 'MERGED' ? `Merged into '${d.target_device}' (+${d.tags_added} tags, ${d.tags_duplicate} dups)` : `+${d.tags_added} tags`}
                        </div>
                    `).join('')}
                </div>
                ${!dryRun ? `
                    <div style="margin-top: 10px; text-align: right;">
                        <button class="btn btn-sm btn-secondary" onclick="syncAllTags()" style="font-size: 0.75rem;">
                            🔄 Sync Tags to View Servers Now
                        </button>
                    </div>
                ` : ''}
            `;
            if (!dryRun) loadMatrix();
        } catch (err) {
            resBox.style.background = '#450a0a';
            resBox.style.border = '1px solid #ef4444';
            resBox.innerHTML = `
                <strong style="color: #f87171;">Import Failed:</strong>
                <div style="color: #fca5a5; font-size: 0.8rem; margin-top: 4px;">${err.message}</div>
            `;
        } finally {
            btn.disabled = false;
            btn.innerHTML = '🚀 Import & Deduplicate Devices to Storage';
        }
        return;
    }

    // B. VIEW SERVER MODE (Extract Dashboards & Views Only)
    const targetSelect = document.getElementById('migrate-target-select');
    const target = targetSelect ? targetSelect.value : '9610';
    const keepExisting = document.getElementById('migrate-opt-keep')?.checked ?? true;

    if (migrateSourceMode === 'file' && !selectedMigrateFile) {
        alert('Please select or drop a project.json or .fuxap file first.');
        return;
    }
    const sourceUrl = (document.getElementById('migrate-source-url')?.value || '').trim();
    if (migrateSourceMode === 'url' && !sourceUrl) {
        alert('Please enter a remote server URL (e.g. http://192.168.1.50:1881).');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '⏳ Migrating & Remapping Views...';
    resBox.style.display = 'block';
    resBox.style.background = '#0f172a';
    resBox.style.border = '1px solid #334155';
    resBox.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 12px;">Analyzing views and resolving Central Storage tag bindings...</div>';

    try {
        const formData = new FormData();
        formData.append('target', target);
        formData.append('keep_existing', keepExisting ? 'true' : 'false');
        formData.append('dry_run', dryRun ? 'true' : 'false');

        if (migrateSourceMode === 'file') {
            formData.append('file', selectedMigrateFile);
        } else {
            formData.append('source_url', sourceUrl);
        }

        const resp = await fetch('/api/migrate-project', {
            method: 'POST',
            body: formData
        });

        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || 'Migration request failed');
        }

        const stats = data.stats || {};
        const matchedInst = allInstancesMap[target] || allInstancesMap[data.target_instance] || { port: data.target_port, subpath: `/p9/ps/ems` };
        const host = window.location.hostname || '127.0.0.1';
        const proto = window.location.protocol || 'http:';
        const otView = `${proto}//${host}${matchedInst.subpath || ''}/home`;
        const otEditor = `${proto}//${host}${matchedInst.subpath || ''}/editor`;

        let unmatchedHtml = '';
        if (stats.unmatched && stats.unmatched.length > 0) {
            unmatchedHtml = `
                <details style="margin-top: 10px; cursor: pointer;">
                    <summary style="color: #facc15; font-weight: 600; font-size: 0.8rem;">
                        ⚠️ Notice: ${stats.unmatched.length} unmatched tag(s) in source widgets (Click to expand)
                    </summary>
                    <div style="background: #020617; border-radius: 4px; padding: 8px; margin-top: 6px; max-height: 140px; overflow-y: auto; font-family: monospace; font-size: 0.75rem; color: #cbd5e1;">
                        ${stats.unmatched.map(u => `<div>• [${u.item_type}] Variable: <code>${u.variable}</code></div>`).join('')}
                    </div>
                </details>
            `;
        }

        resBox.style.background = '#064e3b';
        resBox.style.border = '1px solid #10b981';
        resBox.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <strong style="color: #34d399; font-size: 0.95rem;">
                    ${data.dry_run ? '🔍 Dry Run Completed Successfully' : '🎉 Dashboards Migrated Successfully!'}
                </strong>
                <span style="background: rgba(16, 185, 129, 0.2); color: #6ee7b7; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;">
                    ${data.views_count} View(s)
                </span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 10px 0; background: rgba(0,0,0,0.25); padding: 8px; border-radius: 6px; text-align: center;">
                <div><div style="font-size: 1.1rem; font-weight: 800; color: #f8fafc;">${stats.total_items || 0}</div><div style="font-size: 0.7rem; color: #94a3b8;">Widgets</div></div>
                <div><div style="font-size: 1.1rem; font-weight: 800; color: #38bdf8;">${stats.bound_items || 0}</div><div style="font-size: 0.7rem; color: #94a3b8;">Telemetry</div></div>
                <div><div style="font-size: 1.1rem; font-weight: 800; color: #4ade80;">${(stats.exact_matches || 0) + (stats.remapped || 0)}</div><div style="font-size: 0.7rem; color: #94a3b8;">Auto-Remapped</div></div>
                <div><div style="font-size: 1.1rem; font-weight: 800; color: ${stats.unmatched && stats.unmatched.length > 0 ? '#facc15' : '#94a3b8'};">${(stats.unmatched || []).length}</div><div style="font-size: 0.7rem; color: #94a3b8;">Unmatched</div></div>
            </div>
            ${unmatchedHtml}
            ${!data.dry_run ? `
                <div style="margin-top: 12px; display: flex; gap: 8px; justify-content: flex-end;">
                    <a href="${otView}" target="_blank" class="btn btn-sm btn-primary" style="background: #10b981; border-color: #059669; text-decoration: none;">
                        🌐 Open Operator View ↗
                    </a>
                    <a href="${otEditor}" target="_blank" class="btn btn-sm btn-secondary" style="text-decoration: none;">
                        ✏️ Open Editor ↗
                    </a>
                </div>
            ` : ''}
        `;

        if (!data.dry_run) {
            loadMatrix();
        }
    } catch (err) {
        resBox.style.background = '#450a0a';
        resBox.style.border = '1px solid #ef4444';
        resBox.innerHTML = `
            <strong style="color: #f87171;">Migration Failed:</strong>
            <div style="color: #fca5a5; font-size: 0.8rem; margin-top: 4px;">${err.message}</div>
        `;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🚀 Start 1-Click Dashboard Migration';
    }
}

// ==============================================================================
// 100% Reliable Industrial Diagnostics & Self-Healing Engine
// ==============================================================================
let currentDiagTarget = null; // { type: 'instance'|'storage', id: ... }

async function openDiagnosticsModal(instanceId) {
    currentDiagTarget = { type: 'instance', id: instanceId };
    const modal = document.getElementById('diagnostics-modal');
    if (!modal) return;

    const inst = allInstancesMap[instanceId] || {};
    document.getElementById('diag-title').textContent = `Diagnostics: ${inst.name || instanceId}`;
    document.getElementById('diag-subpath').textContent = `Subpath: ${inst.subpath || '--'} (Plant ${inst.plant || '?'}, Line ${inst.line || '?'})`;
    document.getElementById('diag-port').textContent = inst.port || '--';
    document.getElementById('diag-fault-summary').textContent = 'Fetching live diagnostics...';
    document.getElementById('diag-fault-details').textContent = '';
    document.getElementById('diag-remedy-text').textContent = 'Analyzing system state...';
    document.getElementById('diag-log-content').textContent = 'Loading logs...';

    modal.classList.add('show');

    try {
        const res = await fetch(`/api/instances/${instanceId}/diagnostics`);
        const data = await res.json();
        renderDiagnosticsData(data);
    } catch (e) {
        document.getElementById('diag-fault-summary').textContent = 'Diagnostic request error: ' + e.message;
    }
}

async function openStorageDiagnosticsModal(plantId) {
    currentDiagTarget = { type: 'storage', id: plantId };
    const modal = document.getElementById('diagnostics-modal');
    if (!modal) return;

    document.getElementById('diag-title').textContent = `Storage Diagnostics: Plant ${plantId} Master`;
    document.getElementById('diag-subpath').textContent = `Subpath: /p${plantId}/storage (Central Field Poller & InfluxDB)`;
    document.getElementById('diag-fault-summary').textContent = 'Fetching storage diagnostics...';
    document.getElementById('diag-log-content').textContent = 'Loading logs...';

    modal.classList.add('show');

    try {
        const res = await fetch(`/api/storage/${plantId}/diagnostics`);
        const data = await res.json();
        renderDiagnosticsData(data);
    } catch (e) {
        document.getElementById('diag-fault-summary').textContent = 'Diagnostic request error: ' + e.message;
    }
}

function renderDiagnosticsData(data) {
    const diag = data.diagnostics || {};
    const isLive = data.is_live;
    const portEl = document.getElementById('diag-port');
    const statusPill = document.getElementById('diag-status-pill');
    const faultBox = document.getElementById('diag-fault-box');
    const faultSummary = document.getElementById('diag-fault-summary');
    const faultDetails = document.getElementById('diag-fault-details');
    const remedyBox = document.getElementById('diag-remedy-box');
    const remedyText = document.getElementById('diag-remedy-text');
    const logContent = document.getElementById('diag-log-content');
    const logPath = document.getElementById('diag-log-path');
    const dbStatus = document.getElementById('diag-db-status');

    portEl.textContent = diag.port || data.port || '--';
    dbStatus.textContent = diag.db_status || 'OK';
    dbStatus.style.color = diag.db_status === 'OK' ? '#4ade80' : '#f87171';
    logPath.textContent = diag.log_path || '';

    if (isLive) {
        statusPill.textContent = 'ONLINE & HEALTHY';
        statusPill.style.background = '#064e3b';
        statusPill.style.color = '#34d399';
        faultBox.style.background = 'rgba(16, 185, 129, 0.1)';
        faultBox.style.borderColor = '#10b981';
        faultSummary.style.color = '#34d399';
        faultSummary.innerHTML = '✓ Instance is running and accepting connections on assigned port.';
        faultDetails.textContent = diag.port_occupant ? `Process PID ${diag.port_occupant.pid} (${diag.port_occupant.name}) is actively listening.` : 'Port is open.';
        remedyBox.style.display = 'none';
    } else {
        statusPill.textContent = 'FAULTED / DOWN';
        statusPill.style.background = '#450a0a';
        statusPill.style.color = '#f87171';
        faultBox.style.background = 'rgba(239, 68, 68, 0.14)';
        faultBox.style.borderColor = '#ef4444';
        faultSummary.style.color = '#f87171';
        faultSummary.textContent = diag.fault_summary || 'SCADA Server failed to start';
        faultDetails.textContent = diag.fault_details || 'Process exited prematurely.';
        remedyBox.style.display = 'block';
        remedyText.textContent = diag.remedy || 'Click "1-Click Auto-Fix & Relaunch" to clear rogue locks and restart.';
    }

    const logLines = diag.log_tail || [];
    logContent.textContent = logLines.length > 0 ? logLines.join('\n') : 'No log output captured yet.';
    logContent.scrollTop = logContent.scrollHeight;
}

function closeDiagnosticsModal() {
    const modal = document.getElementById('diagnostics-modal');
    if (modal) modal.classList.remove('show');
    currentDiagTarget = null;
}

async function executeModalSelfHeal() {
    if (!currentDiagTarget) return;
    const btn = document.getElementById('btn-diag-self-heal');
    btn.disabled = true;
    btn.textContent = '⏳ Auto-Healing & Starting...';

    try {
        if (currentDiagTarget.type === 'instance') {
            await triggerInstanceSelfHeal(currentDiagTarget.id, false);
            // Re-fetch diagnostics
            const res = await fetch(`/api/instances/${currentDiagTarget.id}/diagnostics`);
            const data = await res.json();
            renderDiagnosticsData(data);
        } else {
            await triggerStorageSelfHeal(currentDiagTarget.id, false);
            const res = await fetch(`/api/storage/${currentDiagTarget.id}/diagnostics`);
            const data = await res.json();
            renderDiagnosticsData(data);
        }
    } catch (e) {
        alert('Self-heal failed: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '⚡ 1-Click Auto-Fix & Relaunch';
        loadMatrix();
    }
}

async function triggerInstanceSelfHeal(id, showAlert = true) {
    try {
        const res = await fetch(`/api/instances/${id}/self-heal`, { method: 'POST' });
        const data = await res.json();
        if (showAlert) {
            alert(data.success ? `✓ ${data.message}` : `[-] ${data.message}`);
        }
        loadMatrix();
    } catch (e) {
        if (showAlert) alert('Self-heal error: ' + e.message);
    }
}

async function triggerStorageSelfHeal(plantId, showAlert = true) {
    try {
        const res = await fetch(`/api/storage/${plantId}/self-heal`, { method: 'POST' });
        const data = await res.json();
        if (showAlert) {
            alert(data.success ? `✓ ${data.message}` : `[-] ${data.message}`);
        }
        loadMatrix();
    } catch (e) {
        if (showAlert) alert('Self-heal error: ' + e.message);
    }
}

function copyDiagnosticLogs() {
    const logContent = document.getElementById('diag-log-content')?.textContent || '';
    navigator.clipboard.writeText(logContent).then(() => {
        alert('Diagnostic logs copied to clipboard!');
    }).catch(() => {
        alert('Failed to copy logs.');
    });
}

async function copyInstanceApiKey(instanceId) {
    try {
        const resp = await fetch(`/api/instances/${instanceId}/apikeys`);
        const data = await resp.json();
        const key = data.primary_api_key || data.secret_code || 'fuxa-secret-jwt-key';
        await navigator.clipboard.writeText(key);
        alert(`🔑 API Key Copied to Clipboard!\n\nKey: ${key}\nInstance: ${instanceId}`);
    } catch (e) {
        alert(`Failed to fetch API key: ${e.message}`);
    }
}

function scrollToFirstFault() {
    const faultedEl = document.querySelector('.instance-card-row[style*="border-color"]');
    if (faultedEl) {
        faultedEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// ==============================================================================
// Bulk Historical Tagging (DAQ) UI Handlers
// ==============================================================================
function openBulkHistoryModal(plantId = '9') {
    const modal = document.getElementById('bulk-history-modal');
    if (!modal) return;
    const plantSel = document.getElementById('bulk-history-plant');
    if (plantSel) plantSel.value = String(plantId);

    const resBox = document.getElementById('bulk-history-results');
    if (resBox) {
        resBox.style.display = 'none';
        resBox.innerHTML = '';
    }
    toggleBulkHistoryModeUI();
    modal.classList.add('active');
}

function closeBulkHistoryModal() {
    const modal = document.getElementById('bulk-history-modal');
    if (modal) modal.classList.remove('active');
}

function toggleBulkHistoryModeUI() {
    const isEnable = document.querySelector('input[name="bulk-daq-state"]:checked')?.value === 'enable';
    const optBox = document.getElementById('bulk-daq-options');
    if (optBox) {
        optBox.style.opacity = isEnable ? '1' : '0.4';
        optBox.style.pointerEvents = isEnable ? 'auto' : 'none';
    }
}

async function submitBulkHistory() {
    const btn = document.getElementById('btn-apply-bulk-history');
    const resBox = document.getElementById('bulk-history-results');
    const plantId = parseInt(document.getElementById('bulk-history-plant')?.value || '9', 10);
    const enabled = document.querySelector('input[name="bulk-daq-state"]:checked')?.value === 'enable';
    const mode = document.querySelector('input[name="bulk-daq-mode"]:checked')?.value || 'change';
    const interval = parseInt(document.getElementById('bulk-daq-interval')?.value || '60', 10);

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Applying DAQ Settings...';
    }

    try {
        const resp = await fetch(`/api/storage/${plantId}/bulk-history`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled: enabled,
                mode: mode,
                interval: interval,
                restart: true
            })
        });

        const data = await resp.json();
        if (resBox) {
            resBox.style.display = 'block';
            if (data.success && data.report) {
                const rep = data.report;
                resBox.style.background = 'rgba(16, 185, 129, 0.12)';
                resBox.style.border = '1px solid #10b981';
                resBox.style.color = '#a7f3d0';
                resBox.innerHTML = `
                    <div style="font-weight: 700; font-size: 0.95rem; margin-bottom: 6px;">
                        ✓ Bulk Historical DAQ Applied Successfully!
                    </div>
                    <div>• <strong>Historical State:</strong> ${rep.enabled ? 'ENABLED' : 'DISABLED'}</div>
                    <div>• <strong>Mode:</strong> ${rep.mode.toUpperCase()} ${rep.mode === 'interval' ? `(${rep.interval_seconds}s)` : ''}</div>
                    <div>• <strong>Devices Affected:</strong> ${rep.total_devices_affected}</div>
                    <div>• <strong>Total Tags Updated:</strong> ${rep.total_tags_updated}</div>
                    <div style="margin-top: 6px; font-size: 0.75rem; color: #6ee7b7;">
                        Storage Server on Plant ${plantId} reloaded and actively logging to InfluxDB.
                    </div>
                `;
            } else {
                resBox.style.background = 'rgba(239, 68, 68, 0.12)';
                resBox.style.border = '1px solid #ef4444';
                resBox.style.color = '#fca5a5';
                resBox.innerHTML = `❌ Failed: ${data.detail || data.error || 'Unknown error'}`;
            }
        }
    } catch (err) {
        if (resBox) {
            resBox.style.display = 'block';
            resBox.style.background = 'rgba(239, 68, 68, 0.12)';
            resBox.style.border = '1px solid #ef4444';
            resBox.style.color = '#fca5a5';
            resBox.innerHTML = `❌ Network Error: ${err.message}`;
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🚀 Apply Bulk History (DAQ)';
        }
    }
}

// ==============================================================================
// 7. Device Topology & Sub-Location Grouping Engine
// ==============================================================================
let topoDevicesList = [];
let selectedTopoDeviceIds = new Set();

function openDeviceTopologyModal() {
    const modal = document.getElementById('device-topology-modal');
    if (!modal) return;
    modal.classList.add('show');
    loadStorageTopologyDevices();
}

function closeDeviceTopologyModal() {
    const modal = document.getElementById('device-topology-modal');
    if (modal) modal.classList.remove('show');
}

function handleTopologyPresetChange() {
    const preset = document.getElementById('topo-bulk-preset')?.value || '';
    const locInput = document.getElementById('topo-bulk-location');
    const subdivInput = document.getElementById('topo-bulk-subdiv');
    if (!locInput) return;
    if (preset === '__none__') {
        locInput.value = '';
        if (subdivInput) subdivInput.value = '';
    } else if (preset && preset !== '__custom__') {
        locInput.value = preset;
    } else if (preset === '__custom__') {
        locInput.value = '';
        locInput.focus();
    }
}

async function loadStorageTopologyDevices() {
    const plantId = document.getElementById('topo-storage-plant')?.value || '9';
    const tbody = document.getElementById('topo-devices-tbody');
    const linkBtn = document.getElementById('btn-view-storage-tree');
    const resBox = document.getElementById('topo-results-box');
    if (resBox) resBox.style.display = 'none';

    const storagePort = (plantId === '9') ? 5900 : 5000 + parseInt(plantId, 10) * 100;
    if (linkBtn) {
        linkBtn.href = `http://${window.location.hostname || 'localhost'}:${storagePort}/p${plantId}/storage/device`;
        linkBtn.textContent = `🌐 View Storage Tree (Port ${storagePort})`;
    }

    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="8" style="padding: 24px; text-align: center; color: #94a3b8;">⏳ Loading devices from Plant ' + plantId + ' Storage...</td></tr>';
    }

    try {
        const resp = await fetch(`/api/storage/${plantId}/devices`);
        const data = await resp.json();
        topoDevicesList = data.devices || [];
        selectedTopoDeviceIds.clear();

        // Dynamically add unique active locations to preset dropdown so user can pick/reassign them
        const presetSelect = document.getElementById('topo-bulk-preset');
        if (presetSelect) {
            const activeLocs = new Set();
            topoDevicesList.forEach(d => {
                if (d.location && d.location.trim()) activeLocs.add(d.location.trim());
            });
            const existingOptValues = new Set(Array.from(presetSelect.options).map(o => o.value));
            activeLocs.forEach(loc => {
                if (!existingOptValues.has(loc)) {
                    const opt = document.createElement('option');
                    opt.value = loc;
                    opt.textContent = `📍 ${loc}`;
                    opt.dataset.div = '6';
                    presetSelect.appendChild(opt);
                }
            });
        }

        renderTopoDevicesTable();
    } catch (err) {
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="8" style="padding: 24px; text-align: center; color: #f87171;">❌ Failed to load devices: ${err.message}</td></tr>`;
        }
    }
}

function renderTopoDevicesTable() {
    const tbody = document.getElementById('topo-devices-tbody');
    const selCount = document.getElementById('topo-selected-count');
    const selectAll = document.getElementById('topo-select-all');

    if (selCount) selCount.textContent = selectedTopoDeviceIds.size;
    if (selectAll) {
        selectAll.checked = (topoDevicesList.length > 0 && selectedTopoDeviceIds.size === topoDevicesList.length);
    }

    if (!tbody) return;
    if (topoDevicesList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="padding: 24px; text-align: center; color: #94a3b8;">No devices configured in this Storage Server yet.</td></tr>';
        return;
    }

    tbody.innerHTML = topoDevicesList.map((dev) => {
        const isChecked = selectedTopoDeviceIds.has(dev.id);
        const loc = dev.location || '';
        const subdiv = dev.subdivision || 'Line 1';
        const addr = dev.address || (dev.property && dev.property.address) || '—';
        const type = dev.type || 'Unknown';
        const tagCount = dev.tag_count || (dev.tags ? Object.keys(dev.tags).length : 0);

        return `
            <tr style="border-bottom: 1px solid #1e293b; background: ${isChecked ? 'rgba(37,99,235,0.08)' : 'transparent'};">
                <td style="padding: 8px 12px; text-align: center;">
                    <input type="checkbox" ${isChecked ? 'checked' : ''} onchange="toggleTopoDeviceSelect('${dev.id}', this.checked)" style="cursor: pointer;">
                </td>
                <td style="padding: 8px 12px; font-weight: 600; color: #f8fafc;">
                    ${dev.name || dev.id}
                </td>
                <td style="padding: 8px 12px;">
                    <span style="background: rgba(148, 163, 184, 0.12); color: #cbd5e1; padding: 2px 6px; border-radius: 4px; font-size: 0.72rem; font-family: monospace;">
                        ${type}
                    </span>
                </td>
                <td style="padding: 8px 12px; color: #94a3b8; font-size: 0.75rem; font-family: monospace; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${addr}">
                    ${addr}
                </td>
                <td style="padding: 8px 12px; text-align: center; color: #38bdf8; font-weight: 700;">
                    ${tagCount}
                </td>
                <td style="padding: 6px 12px;">
                    <input type="text" value="${loc}" placeholder="e.g. Decoater Station"
                           onchange="updateInlineTopoDevice('${dev.id}', 'location', this.value)"
                           style="width: 100%; background: #020617; border: 1px solid #334155; color: #60a5fa; padding: 5px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">
                </td>
                <td style="padding: 6px 12px;">
                    <input type="text" value="${subdiv}" placeholder="Line 1"
                           onchange="updateInlineTopoDevice('${dev.id}', 'subdivision', this.value)"
                           style="width: 100%; background: #020617; border: 1px solid #334155; color: #cbd5e1; padding: 5px 8px; border-radius: 4px; font-size: 0.8rem;">
                </td>
                <td style="padding: 6px 12px; text-align: center;">
                    <button type="button" class="btn btn-sm" onclick="event.stopPropagation(); deleteStorageDevice('${dev.id}', '${(dev.name || dev.id).replace(/'/g, "\\'")}')" title="Delete device from storage" style="background: rgba(239,68,68,0.15); border: 1px solid #ef4444; color: #fca5a5; padding: 3px 8px; border-radius: 4px; font-size: 0.72rem; cursor: pointer;">
                        🗑️
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function toggleTopoDeviceSelect(devId, isChecked) {
    if (isChecked) {
        selectedTopoDeviceIds.add(devId);
    } else {
        selectedTopoDeviceIds.delete(devId);
    }
    renderTopoDevicesTable();
}

function toggleSelectAllTopoDevices(event) {
    const isChecked = event.target.checked;
    if (isChecked) {
        topoDevicesList.forEach(d => selectedTopoDeviceIds.add(d.id));
    } else {
        selectedTopoDeviceIds.clear();
    }
    renderTopoDevicesTable();
}

function updateInlineTopoDevice(devId, field, value) {
    const dev = topoDevicesList.find(d => d.id === devId);
    if (dev) {
        dev[field] = value.trim();
    }
}

function applyBulkTopology() {
    const loc = (document.getElementById('topo-bulk-location')?.value || '').trim();
    const subdiv = (document.getElementById('topo-bulk-subdiv')?.value || 'Line 1').trim();

    if (selectedTopoDeviceIds.size === 0) {
        alert('Please select at least one device from the table.');
        return;
    }

    const presetSelect = document.getElementById('topo-bulk-preset');
    const selectedOption = presetSelect?.selectedOptions[0];
    const divId = parseInt(selectedOption?.dataset?.div || '6', 10);

    topoDevicesList.forEach(dev => {
        if (selectedTopoDeviceIds.has(dev.id)) {
            dev.location = loc;
            dev.subdivision = subdiv;
            dev.division = divId;
        }
    });

    renderTopoDevicesTable();
}

async function deleteStorageDevice(devId, devName) {
    if (!confirm(`Are you sure you want to permanently delete device "${devName}" from this Central Storage Server?`)) {
        return;
    }
    const plantId = document.getElementById('topo-storage-plant')?.value || '9';
    try {
        const resp = await fetch(`/api/storage/${plantId}/delete-device`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: devId })
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            loadStorageTopologyDevices();
        } else {
            alert('Failed to delete device: ' + (data.detail || data.message || 'Unknown error'));
        }
    } catch (err) {
        alert('Network error deleting device: ' + err.message);
    }
}

async function purgeSimulatedStorageDevices() {
    const plantId = document.getElementById('topo-storage-plant')?.value || '9';
    if (!confirm(`Are you sure you want to purge all simulated demo devices (e.g. Oven Line 1, Spray Booth Line 1, Pre Treatment Line 1, port 4849 SoftOPC) from Plant ${plantId} Storage Server? This will permanently remove them from the database and restart the server.`)) {
        return;
    }
    const resBox = document.getElementById('topo-results-box');
    if (resBox) {
        resBox.style.display = 'block';
        resBox.style.background = '#0f172a';
        resBox.style.border = '1px solid #334155';
        resBox.style.color = '#94a3b8';
        resBox.innerHTML = '🧹 Purging simulated demo devices and cleaning database...';
    }
    try {
        const resp = await fetch(`/api/storage/${plantId}/purge-simulated-devices`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            if (resBox) {
                resBox.style.background = '#064e3b';
                resBox.style.border = '1px solid #10b981';
                resBox.style.color = '#a7f3d0';
                resBox.innerHTML = `✓ ${data.message || 'Purged simulated devices successfully!'}`;
            }
            loadStorageTopologyDevices();
        } else {
            throw new Error(data.detail || data.message || 'Failed to purge devices');
        }
    } catch (err) {
        if (resBox) {
            resBox.style.background = 'rgba(239, 68, 68, 0.15)';
            resBox.style.border = '1px solid #ef4444';
            resBox.style.color = '#fca5a5';
            resBox.innerHTML = `❌ Error: ${err.message}`;
        }
    }
}

async function saveDeviceTopology() {
    const plantId = document.getElementById('topo-storage-plant')?.value || '9';
    const btn = document.getElementById('btn-save-topology');
    const resBox = document.getElementById('topo-results-box');

    if (!btn || topoDevicesList.length === 0) return;

    btn.disabled = true;
    btn.innerHTML = '⏳ Saving & Restarting Storage Server...';
    if (resBox) {
        resBox.style.display = 'block';
        resBox.style.background = '#0f172a';
        resBox.style.border = '1px solid #334155';
        resBox.style.color = '#94a3b8';
        resBox.innerHTML = 'Updating device topology in SQLite and applying tree layout...';
    }

    const updates = topoDevicesList.map(d => {
        let divNum = 6;
        if (typeof d.division === 'number' && !isNaN(d.division)) {
            divNum = d.division;
        } else if (typeof d.division === 'string') {
            const parsed = parseInt(d.division, 10);
            if (!isNaN(parsed)) divNum = parsed;
        }
        return {
            id: d.id,
            location: (d.location || '').trim(),
            subdivision: (d.subdivision || 'Line 1').trim(),
            division: divNum
        };
    });

    try {
        const resp = await fetch(`/api/storage/${plantId}/update-device-topology`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ updates: updates })
        });
        let data;
        try {
            data = await resp.json();
        } catch (jErr) {
            const rawText = await resp.text();
            throw new Error(`Server returned error (${resp.status}): ${rawText || jErr.message}`);
        }

        if (resp.ok && data.success) {
            const storagePort = (plantId === '9') ? 5900 : 5000 + parseInt(plantId, 10) * 100;
            if (resBox) {
                resBox.style.background = '#064e3b';
                resBox.style.border = '1px solid #10b981';
                resBox.style.color = '#a7f3d0';
                resBox.innerHTML = `
                    <div style="font-weight: 700; margin-bottom: 4px;">🎉 Device Grouping Saved Successfully!</div>
                    <div>${data.message || `Updated ${updates.length} devices.`}</div>
                    <div style="margin-top: 6px;">
                        <a href="http://${window.location.hostname || 'localhost'}:${storagePort}/p${plantId}/storage/device" target="_blank" style="color: #67e8f9; font-weight: 700; text-decoration: underline;">
                            👉 Open Central Storage Tree (Port ${storagePort}) to view the live rearranged branches!
                        </a>
                    </div>
                `;
            }
        } else {
            throw new Error(data.detail || data.error || 'Failed to update topology');
        }
    } catch (err) {
        if (resBox) {
            resBox.style.background = 'rgba(239, 68, 68, 0.15)';
            resBox.style.border = '1px solid #ef4444';
            resBox.style.color = '#fca5a5';
            resBox.innerHTML = `❌ Error: ${err.message}`;
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = '💾 Save & Rearrange Tree';
    }
}

// Auto-Refresh
loadMatrix();
setInterval(loadMatrix, 5000);

// URL Query Parameter Handlers (e.g. ?action=import&target=9621)
window.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('action') === 'import' || params.get('import')) {
        const target = params.get('target') || params.get('port');
        const dest = params.get('dest') || 'view';
        setTimeout(() => {
            openMigrateModal(target, dest);
        }, 350);
    }
});
