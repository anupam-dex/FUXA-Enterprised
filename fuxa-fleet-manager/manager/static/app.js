// FUXA Enterprise Fleet Manager Frontend Logic

let selectedPlantFilter = localStorage.getItem('fuxa_selected_plant') || '9';
let cachedMatrix = [];

function getServerHost() {
    if (window.location.hostname && window.location.hostname !== '') {
        return window.location.hostname;
    }
    return '127.0.0.1';
}

async function loadMatrix() {
    try {
        const res = await fetch('/api/matrix');
        const data = await res.json();
        cachedMatrix = data.matrix || [];
        
        // Update PM2 pill
        const pm2Status = document.getElementById('pm2-status');
        const pm2Pill = document.getElementById('pm2-pill');
        if (data.pm2_available) {
            pm2Status.textContent = 'Active (Live)';
            pm2Pill.querySelector('.dot').className = 'dot live';
        } else {
            pm2Status.textContent = 'CLI Fallback';
            pm2Pill.querySelector('.dot').className = 'dot';
        }

        renderStorageGrid(cachedMatrix);
        renderPlantSelector(cachedMatrix);
        renderPlantGrid(cachedMatrix);
        document.getElementById('stat-plants').textContent = cachedMatrix.length;
    } catch (err) {
        console.error("Failed to load matrix:", err);
    }
}

function renderStorageGrid(matrix) {
    const grid = document.getElementById('storage-grid');
    grid.innerHTML = '';

    matrix.forEach(plant => {
        const card = document.createElement('div');
        card.className = 'storage-card';

        const isOnline = plant.storage_online;
        const statusClass = isOnline ? 'badge-online' : 'badge-stopped';
        const statusText = isOnline ? 'ONLINE' : 'STOPPED';

        card.innerHTML = `
            <div class="storage-card-header">
                <div>
                    <div style="font-weight: 700; font-size: 0.95rem;">${plant.name}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px;">
                        PM2: <strong>${plant.storage_pm2_name || 'untracked'}</strong> | Port: <strong>${plant.storage_port}</strong>
                    </div>
                </div>
                <span class="badge ${statusClass}">${statusText}</span>
            </div>
            <div class="storage-card-stats">
                <div class="stat-item">
                    <span>CPU</span>
                    <strong>${plant.storage_cpu || 0}%</strong>
                </div>
                <div class="stat-item">
                    <span>RAM</span>
                    <strong>${plant.storage_memory || 0} MB</strong>
                </div>
                <div class="stat-item">
                    <span>Web Console</span>
                    <a href="http://${getServerHost()}:${plant.storage_port}" target="_blank" class="link-open">&#8599; :${plant.storage_port}</a>
                </div>
            </div>
            <div class="storage-card-actions">
                ${isOnline 
                    ? `<button onclick="stopStorage(${plant.plant_id})" class="btn btn-secondary btn-sm" style="flex:1;">Stop</button>`
                    : `<button onclick="startStorage(${plant.plant_id})" class="btn btn-primary btn-sm" style="flex:1;">Start in PM2</button>`
                }
                <button onclick="openImportModal('storage', '${plant.plant_id}', '${plant.name}')" class="btn btn-secondary btn-sm" title="Import project.json to Storage Server">&#128229; Import</button>
                <button onclick="openEditPortModal('storage', '${plant.plant_id}', ${plant.storage_port}, '${plant.name}')" class="btn btn-secondary btn-sm" title="Configure Port">&#9881; Port</button>
                <button onclick="openLogs('${plant.storage_port}')" class="btn btn-secondary btn-sm" title="View PM2 Logs">&#128196; Logs</button>
            </div>
        `;
        grid.appendChild(card);
    });
}

function renderPlantSelector(matrix) {
    const container = document.getElementById('plant-selector-bar');
    if (!container) return;
    container.innerHTML = '';

    const totalInstances = matrix.reduce((acc, p) => acc + (p.instances ? p.instances.length : 0), 0);

    // "All Plants" Tab
    const allTab = document.createElement('button');
    allTab.className = `plant-tab ${selectedPlantFilter === 'all' ? 'active' : ''}`;
    allTab.innerHTML = `🌐 All Plants <span class="plant-tab-badge">${totalInstances}</span>`;
    allTab.onclick = () => selectPlantFilter('all');
    container.appendChild(allTab);

    // Tab per Plant
    matrix.forEach(plant => {
        const pTab = document.createElement('button');
        const isActive = String(selectedPlantFilter) === String(plant.plant_id);
        pTab.className = `plant-tab ${isActive ? 'active' : ''}`;
        const count = plant.instances ? plant.instances.length : 0;
        const shortName = plant.name.split(' - ')[0] || `Plant ${plant.plant_id}`;
        pTab.innerHTML = `🏭 ${shortName} <span class="plant-tab-badge">${count}</span>`;
        pTab.onclick = () => selectPlantFilter(String(plant.plant_id));
        container.appendChild(pTab);
    });

    const summaryEl = document.getElementById('plant-quick-summary');
    if (summaryEl) {
        if (selectedPlantFilter === 'all') {
            summaryEl.textContent = `Showing all ${matrix.length} plants (${totalInstances} view ports)`;
        } else {
            const p = matrix.find(x => String(x.plant_id) === String(selectedPlantFilter));
            if (p) {
                summaryEl.textContent = `Plant ${p.plant_id} | Storage: :${p.storage_port} | Views: ${p.instances ? p.instances.length : 0} ports`;
            }
        }
    }
}

function selectPlantFilter(plantId) {
    selectedPlantFilter = plantId;
    localStorage.setItem('fuxa_selected_plant', plantId);
    renderPlantSelector(cachedMatrix);
    renderPlantGrid(cachedMatrix);
}

function renderPlantGrid(matrix) {
    const grid = document.getElementById('plant-grid');
    grid.innerHTML = '';

    const isSingle = selectedPlantFilter !== 'all';
    const displayPlants = isSingle 
        ? matrix.filter(p => String(p.plant_id) === String(selectedPlantFilter))
        : matrix;

    if (displayPlants.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1; padding: 40px; text-align: center; background: #0d1117; border: 1px dashed var(--border-color); border-radius: 10px;">
                <p style="color: var(--text-muted); margin-bottom: 12px; font-size: 0.95rem;">No view servers deployed for this plant yet.</p>
                <button class="btn btn-primary" onclick="openCreateModal(${selectedPlantFilter})">+ Provision First View Server</button>
            </div>
        `;
        return;
    }

    displayPlants.forEach(plant => {
        const card = document.createElement('div');
        card.className = `plant-card ${isSingle ? 'single-view' : ''}`;

        let instancesHtml = '';
        if (!plant.instances || plant.instances.length === 0) {
            instancesHtml = `
                <div style="color: var(--text-muted); font-size: 0.85rem; padding: 24px; text-align: center; background: #161b22; border-radius: 8px;">
                    <div style="margin-bottom: 12px;">No active view servers deployed for ${plant.name}.</div>
                    <button class="btn btn-primary btn-sm" onclick="openCreateModal(${plant.plant_id})">+ Add View Server for Plant ${plant.plant_id}</button>
                </div>
            `;
        } else {
            instancesHtml = plant.instances.map(inst => {
                const isOnline = inst.is_live;
                const statusBadge = isOnline 
                    ? `<span class="badge badge-online">ONLINE</span>` 
                    : `<span class="badge badge-stopped">STOPPED</span>`;

                return `
                    <div class="instance-row">
                        <div class="instance-info">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <div class="instance-name">${inst.name}</div>
                                ${statusBadge}
                            </div>
                            <div class="instance-sub">
                                Port: <strong style="color: var(--accent-cyan); font-size: 0.85rem;">:${inst.port}</strong> | Subpath: <code>${inst.subpath}</code> | RAM: ${inst.memory_mb || 0} MB | CPU: ${inst.cpu || 0}%
                            </div>
                        </div>
                        <div class="instance-actions">
                            <a href="http://${getServerHost()}:${inst.port}/editor" target="_blank" class="btn btn-primary btn-sm" title="Open HMI Screen Drawing Editor">Editor</a>
                            <a href="http://${getServerHost()}:${inst.port}/home" target="_blank" class="btn btn-secondary btn-sm" title="Open Operator Live View">View</a>
                            <button onclick="openImportModal('view', '${inst.id}', '${inst.name}')" class="btn btn-secondary btn-sm" title="Import project.json to View Server">&#128229; Import</button>
                            <button onclick="openEditPortModal('view', '${inst.id}', ${inst.port}, '${inst.name}')" class="btn btn-secondary btn-sm" title="Configure Port">&#9881; Port</button>
                            <button onclick="openLogs('${inst.port}')" class="btn btn-secondary btn-sm" title="View PM2 Logs">&#128196; Logs</button>
                            ${isOnline 
                                ? `<button onclick="stopInstance('${inst.id}')" class="btn btn-secondary btn-sm" title="Stop in PM2">&#9632;</button>` 
                                : `<button onclick="startInstance('${inst.id}')" class="btn btn-primary btn-sm" title="Start in PM2">&#9654;</button>`
                            }
                            <button onclick="deleteInstance('${inst.id}')" class="btn btn-danger btn-sm" title="Delete from PM2">&#128465;</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        card.innerHTML = `
            <div class="plant-card-header">
                <div>
                    <div class="plant-title" style="font-size: 1.15rem;">${plant.name}</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; font-family: var(--font-mono);">
                        Master Storage: <strong style="color: var(--accent-storage);">:${plant.storage_port}</strong> | Target Bridge: <code>opc.tcp://127.0.0.1:4840</code> | Deployed Views: <strong>${plant.instances ? plant.instances.length : 0}</strong>
                    </div>
                </div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <span class="badge badge-storage">Plant ${plant.plant_id}</span>
                    <button class="btn btn-primary btn-sm" onclick="openCreateModal(${plant.plant_id})">+ Add View Port</button>
                </div>
            </div>
            <div class="instances-list">
                ${instancesHtml}
            </div>
        `;
        grid.appendChild(card);
    });
}

function openCreateModal(preselectedPlantId) {
    document.getElementById('create-modal').classList.add('show');
    if (preselectedPlantId) {
        const plantSelect = document.getElementById('sel-plant');
        if (plantSelect) {
            plantSelect.value = String(preselectedPlantId);
        }
    }
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
    const customPortInput = document.getElementById('input-custom-port');
    if (customPortInput) {
        customPortInput.value = basePort;
    }
    document.getElementById('subpath-preview').textContent = `/p${plant}/div${div}/l${line}`;
    onWizardCustomPortChange();
}

function onWizardCustomPortChange() {
    clearTimeout(wizardPortDebounceTimer);
    const portVal = parseInt(document.getElementById('input-custom-port').value);
    const statusEl = document.getElementById('wizard-port-status');
    const btn = document.getElementById('btn-submit');

    if (!portVal || isNaN(portVal) || portVal < 1024 || portVal > 65535) {
        statusEl.textContent = '❌ Invalid (1024-65535)';
        statusEl.style.color = 'var(--accent-red)';
        btn.disabled = true;
        return;
    }

    if (portVal === 9000) {
        statusEl.textContent = '❌ Port 9000 reserved';
        statusEl.style.color = 'var(--accent-red)';
        btn.disabled = true;
        return;
    }

    statusEl.textContent = '⏳ Checking...';
    statusEl.style.color = 'var(--accent-storage)';

    wizardPortDebounceTimer = setTimeout(async () => {
        try {
            const res = await fetch(`/api/ports/check?port=${portVal}`);
            const data = await res.json();
            if (data.available) {
                statusEl.textContent = '🟢 Free & Available';
                statusEl.style.color = 'var(--accent-view)';
                btn.disabled = false;
            } else {
                statusEl.textContent = `🔴 ${data.message}`;
                statusEl.style.color = 'var(--accent-red)';
                btn.disabled = true;
            }
        } catch (e) {
            statusEl.textContent = '⚠️ Check error';
            statusEl.style.color = 'var(--accent-red)';
        }
    }, 250);
}

async function submitCreateProject() {
    const plant = parseInt(document.getElementById('sel-plant').value);
    const div = parseInt(document.getElementById('sel-div').value);
    const line = parseInt(document.getElementById('input-line').value || '1');
    const name = document.getElementById('input-name').value || `Plant ${plant} Div ${div} Line ${line}`;
    const customPort = parseInt(document.getElementById('input-custom-port').value);

    const btn = document.getElementById('btn-submit');
    btn.disabled = true;
    btn.textContent = 'Provisioning in PM2...';

    try {
        const res = await fetch('/api/create-view', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plant: plant,
                division: div,
                line: line,
                project_name: name,
                custom_port: customPort
            })
        });

        const data = await res.json();
        if (data.success) {
            closeCreateModal();
            loadMatrix();
            showAlert(`
                <strong>&#10003; View Server Provisioned Successfully!</strong><br/>
                &bull; <strong>Port:</strong> ${data.instance.port}<br/>
                &bull; <strong>PM2 Process:</strong> <code>${data.instance.id}</code> (Saved)<br/>
                &bull; <strong>Nginx Route:</strong> ${data.nginx_status.reloaded ? 'Generated & Reloaded' : 'Config saved in nginx/conf.d/'}<br/>
                &bull; <strong>Storage Bridge:</strong> Connected via OPC-UA
            `, 'success');
        } else {
            showAlert(`Failed to create instance: ${data.detail || 'Unknown error'}`, 'error');
        }
    } catch (err) {
        showAlert('Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Launch View Server in PM2';
    }
}

async function startInstance(id) {
    await fetch(`/api/instances/${id}/start`, { method: 'POST' });
    loadMatrix();
}

async function stopInstance(id) {
    await fetch(`/api/instances/${id}/stop`, { method: 'POST' });
    loadMatrix();
}

async function deleteInstance(id) {
    if (confirm(`Remove instance ${id} from PM2 and delete registration?`)) {
        await fetch(`/api/instances/${id}`, { method: 'DELETE' });
        loadMatrix();
    }
}

async function startStorage(plantId) {
    await fetch(`/api/storage/${plantId}/start`, { method: 'POST' });
    loadMatrix();
}

async function stopStorage(plantId) {
    await fetch(`/api/storage/${plantId}/stop`, { method: 'POST' });
    loadMatrix();
}

async function syncInstances() {
    showAlert('Scanning PM2 and directories for new instances...', 'info');
    const res = await fetch('/api/sync', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
        renderPlantGrid(data.matrix);
        renderStorageGrid(data.matrix);
        showAlert('Auto-sync complete: PM2 processes and instances updated!', 'success');
    }
}

function showAlert(html, type) {
    const banner = document.getElementById('alert-banner');
    banner.className = `alert-banner alert-${type}`;
    banner.innerHTML = html;
    banner.style.display = 'block';
    setTimeout(() => {
        banner.style.display = 'none';
    }, 8000);
}

// Initial load & poll every 5s
loadMatrix();
setInterval(loadMatrix, 5000);

// Log Viewer Modal Functions
let currentLogTarget = null;
let currentLogData = null;
let currentLogTab = 'out';

async function openLogs(target) {
    currentLogTarget = target;
    const modal = document.getElementById('log-modal');
    modal.classList.add('show');
    document.getElementById('log-modal-title').textContent = `PM2 Logs for Target: ${target}`;
    await refreshCurrentLogs();
}

async function refreshCurrentLogs() {
    if (!currentLogTarget) return;
    const outputEl = document.getElementById('log-output');
    outputEl.textContent = 'Fetching logs from PM2...';
    try {
        const res = await fetch(`/api/logs/${encodeURIComponent(currentLogTarget)}?lines=100`);
        const data = await res.json();
        currentLogData = data;

        if (!data.found) {
            outputEl.textContent = data.error || 'No logs found.';
            return;
        }

        renderLogContent();
    } catch (err) {
        outputEl.textContent = `Failed to fetch logs: ${err.message}`;
    }
}

function switchLogTab(tab) {
    currentLogTab = tab;
    const btnOut = document.getElementById('btn-tab-out');
    const btnErr = document.getElementById('btn-tab-err');
    if (tab === 'out') {
        btnOut.className = 'btn btn-sm btn-primary';
        btnErr.className = 'btn btn-sm btn-secondary';
    } else {
        btnOut.className = 'btn btn-sm btn-secondary';
        btnErr.className = 'btn btn-sm btn-primary';
    }
    renderLogContent();
}

function renderLogContent() {
    const outputEl = document.getElementById('log-output');
    if (!currentLogData) return;

    const lines = currentLogTab === 'out' ? currentLogData.stdout : currentLogData.stderr;
    const filePath = currentLogTab === 'out' ? currentLogData.out_log_path : currentLogData.err_log_path;

    if (!lines || lines.length === 0) {
        outputEl.textContent = `[Log file: ${filePath}]\n(No log entries recorded yet)`;
    } else {
        outputEl.textContent = `[Log file: ${filePath}]\n\n` + lines.join('');
    }
    outputEl.scrollTop = outputEl.scrollHeight;
}

function closeLogModal() {
    const modal = document.getElementById('log-modal');
    modal.classList.remove('show');
    currentLogTarget = null;
    currentLogData = null;
}

// ==============================================================================
// Versatile Dynamic Port Configuration & Live Pre-Check
// ==============================================================================
let editPortType = null;
let editPortTargetId = null;
let editPortCurrentVal = null;
let editPortDebounceTimer = null;
let wizardPortDebounceTimer = null;

function openEditPortModal(type, targetId, currentPort, name) {
    editPortType = type;
    editPortTargetId = targetId;
    editPortCurrentVal = parseInt(currentPort);

    const modal = document.getElementById('edit-port-modal');
    document.getElementById('edit-port-title').textContent = `⚙️ Configure Port — ${name}`;
    document.getElementById('edit-port-current-badge').textContent = `Current Port: :${currentPort}`;

    const input = document.getElementById('input-edit-port');
    input.value = currentPort;

    const statusBox = document.getElementById('edit-port-status-box');
    statusBox.style.display = 'block';
    statusBox.className = 'port-status-box loading';
    statusBox.textContent = `Current active port: :${currentPort} (no change)`;

    const applyBtn = document.getElementById('btn-apply-port');
    applyBtn.disabled = false;
    applyBtn.textContent = 'Apply & Run Instantly';

    modal.classList.add('show');
}

function closeEditPortModal() {
    document.getElementById('edit-port-modal').classList.remove('show');
    clearTimeout(editPortDebounceTimer);
    editPortType = null;
    editPortTargetId = null;
    editPortCurrentVal = null;
}

function onEditPortInput() {
    clearTimeout(editPortDebounceTimer);
    const newPort = parseInt(document.getElementById('input-edit-port').value);
    const statusBox = document.getElementById('edit-port-status-box');
    const applyBtn = document.getElementById('btn-apply-port');

    statusBox.style.display = 'block';

    if (!newPort || isNaN(newPort) || newPort < 1024 || newPort > 65535) {
        statusBox.className = 'port-status-box error';
        statusBox.textContent = '❌ Port must be a valid number between 1024 and 65535.';
        applyBtn.disabled = true;
        return;
    }

    if (newPort === 9000) {
        statusBox.className = 'port-status-box error';
        statusBox.textContent = '❌ Port 9000 is strictly reserved for the Fleet Manager.';
        applyBtn.disabled = true;
        return;
    }

    if (newPort === editPortCurrentVal) {
        statusBox.className = 'port-status-box loading';
        statusBox.textContent = `Current active port: :${newPort} (no change)`;
        applyBtn.disabled = false;
        return;
    }

    statusBox.className = 'port-status-box loading';
    statusBox.textContent = `⏳ Verifying availability of port ${newPort} on host network...`;
    applyBtn.disabled = true;

    editPortDebounceTimer = setTimeout(async () => {
        try {
            const currentOwnerId = editPortType === 'storage' ? `storage_${editPortTargetId}` : editPortTargetId;
            const res = await fetch(`/api/ports/check?port=${newPort}&current_id=${currentOwnerId}`);
            const data = await res.json();

            if (data.available) {
                statusBox.className = 'port-status-box success';
                statusBox.innerHTML = `🟢 <strong>Available!</strong> Port ${newPort} is free and ready to assign.`;
                applyBtn.disabled = false;
            } else {
                statusBox.className = 'port-status-box error';
                statusBox.innerHTML = `🔴 <strong>Conflict:</strong> ${data.message}`;
                applyBtn.disabled = true;
            }
        } catch (e) {
            statusBox.className = 'port-status-box error';
            statusBox.textContent = `⚠️ Error checking port availability: ${e.message}`;
            applyBtn.disabled = true;
        }
    }, 250);
}

async function submitReconfigurePort() {
    const newPort = parseInt(document.getElementById('input-edit-port').value);
    const applyBtn = document.getElementById('btn-apply-port');
    const statusBox = document.getElementById('edit-port-status-box');

    applyBtn.disabled = true;
    applyBtn.textContent = 'Reconfiguring PM2 & Preserving DB...';

    const endpoint = editPortType === 'storage'
        ? `/api/storage/${editPortTargetId}/reconfigure`
        : `/api/instances/${editPortTargetId}/reconfigure`;

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_port: newPort })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            closeEditPortModal();
            showAlert(`<strong>&#10003; Port Reconfigured Successfully!</strong><br/>Server running on port <strong>:${newPort}</strong> in PM2. Project database and screens preserved.`);
            loadMatrix();
        } else {
            statusBox.className = 'port-status-box error';
            statusBox.textContent = `❌ ${data.detail || data.message || 'Failed to reconfigure port'}`;
            applyBtn.disabled = false;
            applyBtn.textContent = 'Apply & Run Instantly';
        }
    } catch (e) {
        statusBox.className = 'port-status-box error';
        statusBox.textContent = `❌ Request failed: ${e.message}`;
        applyBtn.disabled = false;
        applyBtn.textContent = 'Apply & Run Instantly';
    }
}

// ---------------------------------------------------------------------
// Project Import Wizard Logic
// ---------------------------------------------------------------------

let currentImportProjectData = null;

function openImportModal(targetType, targetId, targetName) {
    const modal = document.getElementById('import-modal');
    if (!modal) return;

    // Reset file and inspect box
    currentImportProjectData = null;
    const fileInput = document.getElementById('file-project-input');
    if (fileInput) fileInput.value = '';
    
    const inspectBox = document.getElementById('import-inspect-box');
    if (inspectBox) {
        inspectBox.style.display = 'none';
        inspectBox.innerHTML = '';
    }
    
    const dropzoneLabel = document.getElementById('dropzone-label');
    if (dropzoneLabel) dropzoneLabel.textContent = 'Click to Browse or Drag & Drop project.json';
    
    const submitBtn = document.getElementById('btn-import-submit');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = '🚀 Import & Apply Now';
    }

    const statusBox = document.getElementById('import-status-box');
    if (statusBox) {
        statusBox.style.display = 'none';
        statusBox.innerHTML = '';
    }

    // Populate View Instances Dropdown
    const viewSelect = document.getElementById('sel-import-view');
    if (viewSelect) {
        viewSelect.innerHTML = '';
        let hasViews = false;
        cachedMatrix.forEach(plant => {
            if (plant.instances && plant.instances.length > 0) {
                plant.instances.forEach(inst => {
                    hasViews = true;
                    const opt = document.createElement('option');
                    opt.value = inst.id;
                    opt.textContent = `${inst.name} (Port :${inst.port} | Plant ${plant.plant_id})`;
                    viewSelect.appendChild(opt);
                });
            }
        });

        if (!hasViews) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '(No View Servers Deployed - Create one first)';
            viewSelect.appendChild(opt);
        }
    }

    // Set Target Selection if provided
    if (targetType === 'view') {
        const rView = document.getElementById('radio-import-view');
        if (rView) rView.checked = true;
        onImportTargetTypeChange();
        if (targetId && viewSelect) {
            viewSelect.value = targetId;
        }
    } else if (targetType === 'storage') {
        const rStorage = document.getElementById('radio-import-storage');
        if (rStorage) rStorage.checked = true;
        onImportTargetTypeChange();
        if (targetId) {
            const plantSelect = document.getElementById('sel-import-plant');
            if (plantSelect) plantSelect.value = String(targetId);
        }
    } else {
        const rStorage = document.getElementById('radio-import-storage');
        if (rStorage) rStorage.checked = true;
        onImportTargetTypeChange();
    }

    setupDropzone();
    modal.classList.add('show');
}

function closeImportModal() {
    const modal = document.getElementById('import-modal');
    if (modal) modal.classList.remove('show');
}

function onImportTargetTypeChange() {
    const rView = document.getElementById('radio-import-view');
    const isView = rView ? rView.checked : false;
    const gStorage = document.getElementById('group-import-storage');
    const gView = document.getElementById('group-import-view');
    const gMode = document.getElementById('group-view-mode');

    if (gStorage) gStorage.style.display = isView ? 'none' : 'block';
    if (gView) gView.style.display = isView ? 'block' : 'none';
    if (gMode) gMode.style.display = isView ? 'block' : 'none';
}

function setupDropzone() {
    const dropzone = document.getElementById('import-dropzone');
    if (!dropzone || dropzone.dataset.initialized) return;
    dropzone.dataset.initialized = 'true';

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('drag-over');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
        }, false);
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt ? dt.files : null;
        if (files && files.length > 0) {
            onFileSelected(files);
        }
    }, false);
}

function onFileSelected(files) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const reader = new FileReader();

    const statusBox = document.getElementById('import-status-box');
    if (statusBox) statusBox.style.display = 'none';

    reader.onload = function(e) {
        try {
            let content = e.target.result;
            // Strip potential UTF-8 BOM
            if (content.charCodeAt(0) === 0xFEFF) {
                content = content.substr(1);
            }
            const data = JSON.parse(content);
            currentImportProjectData = data;

            const labelEl = document.getElementById('dropzone-label');
            if (labelEl) labelEl.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            
            renderInspectBox(data);
            const submitBtn = document.getElementById('btn-import-submit');
            if (submitBtn) submitBtn.disabled = false;
        } catch (err) {
            if (statusBox) {
                statusBox.style.display = 'block';
                statusBox.className = 'port-status-box error';
                statusBox.textContent = `❌ Failed to parse JSON in '${file.name}': ${err.message}`;
            }
            const submitBtn = document.getElementById('btn-import-submit');
            if (submitBtn) submitBtn.disabled = true;
        }
    };
    reader.readAsText(file);
}

function renderInspectBox(data) {
    const box = document.getElementById('import-inspect-box');
    if (!box) return;
    box.style.display = 'block';

    const title = data.name || (data.general && data.general.title) || 'FUXA Project';
    const version = data.version || '1.00';

    // Devices
    let devs = data.devices || {};
    let devList = Array.isArray(devs) ? devs : Object.values(devs);
    let devNames = devList.map(d => d.name || d.id || 'Unnamed Device');
    let totalTags = 0;
    devList.forEach(d => {
        if (d && d.tags) {
            totalTags += Array.isArray(d.tags) ? d.tags.length : Object.keys(d.tags).length;
        }
    });

    // Views
    let views = (data.hmi && data.hmi.views) ? data.hmi.views : (data.views || []);
    let viewList = Array.isArray(views) ? views : Object.values(views);
    let viewNames = viewList.map(v => v.name || v.id || 'Unnamed Screen');

    box.innerHTML = `
        <div class="inspect-header">
            <div>
                <strong style="color: #fff; font-size: 0.95rem;">${title}</strong>
                <span style="color: var(--text-muted); font-size: 0.75rem; margin-left: 6px;">(v${version})</span>
            </div>
            <span class="badge badge-online">VALID FUXA PROJECT</span>
        </div>
        <div class="inspect-pills">
            <span class="inspect-pill" style="color: var(--accent-storage);">🔌 <strong>${devNames.length}</strong> Devices</span>
            <span class="inspect-pill" style="color: var(--accent-cyan);">📊 <strong>${totalTags.toLocaleString()}</strong> Tags</span>
            <span class="inspect-pill" style="color: #7ee787;">🖥️ <strong>${viewNames.length}</strong> HMI Views</span>
        </div>
        ${viewNames.length > 0 ? `
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">Detected Views:</div>
            <div class="inspect-chips">
                ${viewNames.map(name => `<span class="view-chip">${name}</span>`).join('')}
            </div>
        ` : ''}
    `;
}

async function submitImportProject() {
    if (!currentImportProjectData) {
        alert("Please select a project.json file first.");
        return;
    }

    const rView = document.getElementById('radio-import-view');
    const isView = rView ? rView.checked : false;
    const btn = document.getElementById('btn-import-submit');
    const statusBox = document.getElementById('import-status-box');
    const chkReload = document.getElementById('chk-auto-reload');
    const autoReload = chkReload ? chkReload.checked : true;
    const chkBridge = document.getElementById('chk-preserve-bridge');
    const preserveBridge = chkBridge ? chkBridge.checked : true;

    let endpoint = '';
    let targetDesc = '';

    if (isView) {
        const viewId = document.getElementById('sel-import-view').value;
        if (!viewId) {
            alert("Please select a destination View Server.");
            return;
        }
        endpoint = `/api/instances/${viewId}/import-project`;
        targetDesc = `View Server (${viewId})`;
    } else {
        const plantId = document.getElementById('sel-import-plant').value;
        endpoint = `/api/storage/${plantId}/import-project`;
        targetDesc = `Plant ${plantId} Master Storage Server`;
    }

    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Importing & Backing Up Database...';
    }
    if (statusBox) {
        statusBox.style.display = 'block';
        statusBox.className = 'port-status-box loading';
        statusBox.textContent = `⏳ Importing project into ${targetDesc}... Creating pre-import backup...`;
    }

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_data: currentImportProjectData,
                preserve_bridge: preserveBridge,
                auto_restart: autoReload
            })
        });

        if (res.status === 404) {
            if (statusBox) {
                statusBox.className = 'port-status-box error';
                statusBox.innerHTML = `
                    <div style="font-weight: 700; margin-bottom: 6px;">❌ Backend Route Not Found (404)</div>
                    <div>The Fleet Manager process running on port 9000 has not reloaded the new Python backend routes yet.</div>
                    <div style="margin-top: 8px; font-size: 0.8rem; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 4px;">
                        <strong>To fix, run on your terminal:</strong><br/>
                        <code style="color: #79c0ff; font-weight: 700;">pm2 restart FUXA_Enterprise_Manager</code>
                    </div>
                `;
            }
            if (btn) {
                btn.disabled = false;
                btn.textContent = '🚀 Import & Apply Now';
            }
            return;
        }

        const data = await res.json();

        if (res.ok && data.success) {
            if (statusBox) {
                statusBox.className = 'port-status-box success';
                const details = data.details || {};
                statusBox.innerHTML = `
                    <div style="font-weight: 700; margin-bottom: 4px;">&#10003; Project Successfully Imported!</div>
                    <div>Target: <strong>${targetDesc}</strong></div>
                    <div>Screens Imported: <strong>${details.views_count || 0} views</strong> | Devices: <strong>${details.devices_count || 0}</strong></div>
                    ${details.backup_path ? `<div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">🛡️ Pre-backup: <code>${details.backup_path}</code></div>` : ''}
                    ${data.pm2 && data.pm2.restarted ? `<div style="font-size: 0.78rem; color: #7ee787; margin-top: 4px;">📢 PM2 process reloaded live successfully!</div>` : ''}
                `;
            }
            if (btn) btn.textContent = '✓ Import Complete';

            setTimeout(() => {
                closeImportModal();
                showAlert(`<strong>&#10003; Project Imported Successfully!</strong><br/>Loaded into ${targetDesc}.`);
                loadMatrix();
            }, 1800);
        } else {
            if (statusBox) {
                statusBox.className = 'port-status-box error';
                statusBox.textContent = `❌ Import Failed: ${data.detail || data.message || 'Unknown server error'}`;
            }
            if (btn) {
                btn.disabled = false;
                btn.textContent = '🚀 Import & Apply Now';
            }
        }
    } catch (err) {
        if (statusBox) {
            statusBox.className = 'port-status-box error';
            statusBox.textContent = `❌ Import Request Failed: ${err.message}`;
        }
        if (btn) {
            btn.disabled = false;
            btn.textContent = '🚀 Import & Apply Now';
        }
    }
}
