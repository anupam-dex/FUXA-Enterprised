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
    document.getElementById('p-calc-result').textContent = basePort;
    document.getElementById('subpath-preview').textContent = `/p${plant}/div${div}/l${line}`;
}

async function submitCreateProject() {
    const plant = parseInt(document.getElementById('sel-plant').value);
    const div = parseInt(document.getElementById('sel-div').value);
    const line = parseInt(document.getElementById('input-line').value || '1');
    const name = document.getElementById('input-name').value || `Plant ${plant} Div ${div} Line ${line}`;

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
                project_name: name
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
