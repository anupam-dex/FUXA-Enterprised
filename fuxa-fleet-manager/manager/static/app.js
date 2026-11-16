// FUXA Enterprise Fleet Manager Frontend Logic

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

        renderStorageGrid(data.matrix);
        renderPlantGrid(data.matrix);
        document.getElementById('stat-plants').textContent = data.matrix.length;
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

function renderPlantGrid(matrix) {
    const grid = document.getElementById('plant-grid');
    grid.innerHTML = '';

    matrix.forEach(plant => {
        const card = document.createElement('div');
        card.className = 'plant-card';

        let instancesHtml = '';
        if (plant.instances.length === 0) {
            instancesHtml = `<div style="color: var(--text-muted); font-size: 0.85rem; padding: 12px 0;">No active view servers deployed for this plant.</div>`;
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
                                Port: <strong>${inst.port}</strong> | Subpath: <code>${inst.subpath}</code> | RAM: ${inst.memory_mb || 0} MB | CPU: ${inst.cpu || 0}%
                            </div>
                        </div>
                        <div class="instance-actions">
                            <a href="http://${getServerHost()}:${inst.port}/editor" target="_blank" class="btn btn-primary btn-sm">Editor</a>
                            <a href="http://${getServerHost()}:${inst.port}/home" target="_blank" class="btn btn-secondary btn-sm">View</a>
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
                    <div class="plant-title">${plant.name}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">
                        Storage Endpoint: :${plant.storage_port} (OPC-UA: opc.tcp://127.0.0.1:4840)
                    </div>
                </div>
                <span class="badge badge-storage">Plant ${plant.plant_id}</span>
            </div>
            <div class="instances-list">
                ${instancesHtml}
            </div>
        `;
        grid.appendChild(card);
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
