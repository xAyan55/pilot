// Admin LXC Control Panel JS Actions

document.addEventListener('DOMContentLoaded', () => {
  // 1. Sidebar Tab Transitions
  const menuLinks = document.querySelectorAll('.db-menu-item a');
  const panels = document.querySelectorAll('.db-tab-panel');

  if (menuLinks.length > 0) {
    menuLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        if (link.getAttribute('href').includes('logout')) return;
        e.preventDefault();
        
        menuLinks.forEach(item => item.parentElement.classList.remove('active'));
        link.parentElement.classList.add('active');
        
        const targetId = link.getAttribute('data-target');
        panels.forEach(panel => {
          if (panel.id === targetId) {
            panel.classList.add('active');
            // Trigger specific tab loads
            if (targetId === 'panel-overview') {
              loadOverview();
            } else if (targetId === 'panel-deploy') {
              loadUsers();
            } else if (targetId === 'panel-containers') {
              loadContainers();
            } else if (targetId === 'panel-logs') {
              loadLogs();
            }
          } else {
            panel.classList.remove('active');
          }
        });

        // Mobile close sidebar
        const sidebar = document.querySelector('.db-sidebar');
        if (sidebar && sidebar.classList.contains('active')) {
          sidebar.classList.remove('active');
        }
      });
    });
  }

  // Mobile Sidebar Toggle
  const dbToggle = document.querySelector('.db-menu-toggle');
  const dbSidebar = document.querySelector('.db-sidebar');
  if (dbToggle && dbSidebar) {
    dbToggle.addEventListener('click', () => {
      dbSidebar.classList.toggle('active');
    });
  }

  // Initialize Page Loader
  loadOverview();
  // Auto refresh overview stats and container lists every 15 seconds
  setInterval(() => {
    const activePanel = document.querySelector('.db-tab-panel.active');
    if (activePanel) {
      if (activePanel.id === 'panel-overview') {
        loadOverview(true); // silent update
      } else if (activePanel.id === 'panel-containers') {
        loadContainers(true);
      }
    }
  }, 15000);
});

// Helper: Go to logs tab
window.showAuditTab = function() {
  const logLink = document.querySelector('.db-sidebar a[data-target="panel-logs"]');
  if (logLink) {
    logLink.click();
  }
};

// Sliders updates
window.updateDeployCPUVal = function(val) {
  document.getElementById('cpu-slider-val').textContent = `${val} Cores`;
};
window.updateDeployRAMVal = function(val) {
  document.getElementById('ram-slider-val').textContent = `${val} MB`;
};
window.updateDeployDiskVal = function(val) {
  document.getElementById('disk-slider-val').textContent = `${val} GB`;
};

// Load Overview Statistics
async function loadOverview(silent = false) {
  try {
    const response = await fetch('/api/admin/stats');
    const stats = await window.handleFetchResponse(response);

    document.getElementById('stats-vps-count').textContent = stats.vps_count;
    document.getElementById('stats-cpu-count').textContent = `${stats.allocated_cpu} Cores`;
    document.getElementById('stats-ram-allocated').textContent = `${stats.allocated_ram} MB`;
    document.getElementById('stats-clients-count').textContent = stats.clients;

    // Node environment badge
    const badge = document.getElementById('mock-badge');
    if (stats.is_mock) {
      badge.textContent = "Mock Mode Active";
      badge.style.color = "var(--color-cool)";
    } else {
      badge.textContent = "Production Active";
      badge.style.color = "var(--color-success)";
    }

    // Host node resource simulation (CPU fluctuates, RAM is base + active containers RAM)
    const mockCPU = Math.floor(Math.random() * 15) + 5; // 5% - 20%
    const totalRAM = 16384; // 16GB hypervisor node
    const baseRAM = 1536; // 1.5GB OS baseline
    const containerRAM = stats.allocated_ram;
    const currentRAMLoad = Math.min(totalRAM, baseRAM + containerRAM);
    const ramPercent = Math.round((currentRAMLoad / totalRAM) * 100);

    document.getElementById('node-cpu-percent').textContent = `${mockCPU}%`;
    document.getElementById('node-cpu-bar').style.width = `${mockCPU}%`;
    
    document.getElementById('node-ram-usage').textContent = `${currentRAMLoad} MB / ${totalRAM} MB`;
    document.getElementById('node-ram-bar').style.width = `${ramPercent}%`;

    // Fetch and populate top 5 logs
    if (!silent) {
      const logsResp = await fetch('/api/admin/logs');
      const logs = await window.handleFetchResponse(logsResp);
      const quickBody = document.getElementById('quick-logs-body');
      quickBody.innerHTML = '';
      
      const topLogs = logs.slice(0, 5);
      if (topLogs.length === 0) {
        quickBody.innerHTML = `<tr><td colspan="4" class="text-center" style="color: var(--color-text-muted);">No logs recorded.</td></tr>`;
      } else {
        topLogs.forEach(log => {
          const row = document.createElement('tr');
          row.innerHTML = `
            <td style="font-family: monospace;">#${log.id}</td>
            <td><strong>${log.username || 'System'}</strong></td>
            <td>${log.action}</td>
            <td style="font-size: 12px; color: var(--color-text-muted);">${log.timestamp}</td>
          `;
          quickBody.appendChild(row);
        });
      }
    }
  } catch (err) {
    if (!silent) showToast(`Failed to load node stats: ${err.message}`, 'error');
  }
}

// Load Users for the Owner dropdown list
async function loadUsers() {
  try {
    const response = await fetch('/api/admin/users');
    const users = await window.handleFetchResponse(response);
    
    const select = document.getElementById('deployOwner');
    select.innerHTML = '<option value="" disabled selected>Select client...</option>';
    
    users.forEach(user => {
      const option = document.createElement('option');
      option.value = user.id;
      option.textContent = `${user.username} (${user.email})`;
      select.appendChild(option);
    });
  } catch (err) {
    showToast(`Failed to load users: ${err.message}`, 'error');
  }
}

// Load and render Containers list
async function loadContainers(silent = false) {
  try {
    const response = await fetch('/api/admin/vps');
    const containers = await window.handleFetchResponse(response);
    
    const tbody = document.getElementById('containers-table-body');
    tbody.innerHTML = '';
    
    if (containers.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="padding: 40px; color: var(--color-text-muted);">No active LXC containers found on the host.</td></tr>`;
      return;
    }

    // Since container stats are dynamic, we fetch them on loop
    for (const vps of containers) {
      const row = document.createElement('tr');
      row.setAttribute('data-vps-id', vps.id);
      
      // Determine status badge class
      let statusClass = 'stopped';
      if (vps.status === 'running') statusClass = 'running';
      if (vps.status === 'suspended') statusClass = 'suspended';
      
      row.innerHTML = `
        <td><strong>${vps.container_name}</strong></td>
        <td>${vps.owner_username}</td>
        <td style="font-size: 13px;">${vps.os}</td>
        <td style="font-size: 13px;">${vps.cpu} Cores / ${vps.ram} MB RAM / ${vps.disk} GB SSD</td>
        <td style="font-family: monospace; font-size: 13px;" id="ip-cell-${vps.id}">Fetching IP...</td>
        <td>
          <span class="vps-status-badge ${statusClass}" id="badge-${vps.id}" style="display: inline-flex; align-items: center; gap: 6px;">
            <span class="status-dot ${vps.status !== 'running' ? vps.status : ''}"></span>
            <span id="badge-text-${vps.id}" style="text-transform: capitalize;">${vps.status}</span>
          </span>
        </td>
        <td style="font-size: 12px; color: var(--color-text-muted);">${vps.created_at.split(' ')[0]}</td>
        <td class="text-right" style="white-space: nowrap;">
          <button class="btn btn-outline action-btn-small" onclick="toggleSuspend(${vps.id}, '${vps.status}')" id="suspend-btn-${vps.id}" style="margin-right: 6px;">
            <i data-lucide="shield-alert" style="width: 13px; height: 13px; margin-right: 4px;"></i> ${vps.status === 'suspended' ? 'Unsuspend' : 'Suspend'}
          </button>
          <button class="btn btn-outline action-btn-small" onclick="destroyVPS(${vps.id}, '${vps.container_name}')" style="background-color: #fdf2f2; border-color: #f6d1d1; color: #b91c1c;">
            <i data-lucide="trash-2" style="width: 13px; height: 13px; margin-right: 4px;"></i> Wipe
          </button>
        </td>
      `;
      tbody.appendChild(row);
      
      // Async fetch container IP & live stats to verify actual status
      fetchLiveContainerInfo(vps.id);
    }
    
    if (typeof lucide !== 'undefined') {
      lucide.createIcons();
    }
  } catch (err) {
    if (!silent) showToast(`Failed to load containers list: ${err.message}`, 'error');
  }
}

// Fetch live IP and state for a container
async function fetchLiveContainerInfo(vpsId) {
  try {
    const res = await fetch(`/api/client/vps/${vpsId}/stats`);
    if (!res.ok) return;
    const stats = await res.json();
    
    const ipCell = document.getElementById(`ip-cell-${vpsId}`);
    if (ipCell) ipCell.textContent = stats.ip || 'N/A';
    
    const badgeText = document.getElementById(`badge-text-${vpsId}`);
    const badgeContainer = document.getElementById(`badge-${vpsId}`);
    const statusDot = badgeContainer ? badgeContainer.querySelector('.status-dot') : null;
    const suspendBtn = document.getElementById(`suspend-btn-${vpsId}`);
    
    if (stats.status && badgeText) {
      badgeText.textContent = stats.status;
      if (badgeContainer) {
        badgeContainer.className = `vps-status-badge ${stats.status}`;
      }
      if (statusDot) {
        statusDot.className = `status-dot ${stats.status !== 'running' ? stats.status : ''}`;
      }
      if (suspendBtn) {
        suspendBtn.innerHTML = stats.status === 'suspended' 
          ? `<i data-lucide="shield-check" style="width: 13px; height: 13px; margin-right: 4px;"></i> Unsuspend` 
          : `<i data-lucide="shield-alert" style="width: 13px; height: 13px; margin-right: 4px;"></i> Suspend`;
        if (typeof lucide !== 'undefined') { lucide.createIcons(); }
      }
    }
  } catch (e) {
    console.error("Error fetching live stats for row:", vpsId, e);
  }
}

// Suspend / Unsuspend action
async function toggleSuspend(vpsId, currentStatus) {
  const isSuspended = (currentStatus === 'suspended');
  const actionText = isSuspended ? 'unsuspend / resume' : 'suspend';
  
  if (!confirm(`Are you sure you want to ${actionText} this container instance?`)) return;
  
  try {
    const response = await fetch(`/api/admin/vps/${vpsId}/suspend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suspend: !isSuspended })
    });
    
    const data = await window.handleFetchResponse(response);
    showToast(data.message, 'success');
    loadContainers();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// Wipe / Destroy Container action
async function destroyVPS(vpsId, name) {
  if (!confirm(`WARNING: Wiping will stop container ${name} and permanently delete all root filesystem data. This action is irreversible!\n\nAre you sure you want to proceed?`)) {
    return;
  }
  
  showToast(`Initiating wipe operation for ${name}...`, 'info');
  
  try {
    const response = await fetch(`/api/admin/vps/${vpsId}`, {
      method: 'DELETE'
    });
    
    const data = await window.handleFetchResponse(response);
    showToast(data.message, 'success');
    loadContainers();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// Load and render full audit logs
async function loadLogs() {
  try {
    const response = await fetch('/api/admin/logs');
    const logs = await window.handleFetchResponse(response);
    
    const tbody = document.getElementById('full-logs-body');
    tbody.innerHTML = '';
    
    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-center" style="padding: 24px; color: var(--color-text-muted);">No audit events.</td></tr>`;
      return;
    }
    
    logs.forEach(log => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td style="font-family: monospace;">#${log.id}</td>
        <td><strong>${log.username || 'System'}</strong></td>
        <td>${log.action}</td>
        <td style="font-family: monospace; font-size: 13px;">${log.timestamp}</td>
      `;
      tbody.appendChild(row);
    });
  } catch (err) {
    showToast(`Failed to load audit logs: ${err.message}`, 'error');
  }
}

// Handle VPS Creation via SSE deploy-stream
window.handleDeployVPS = function(event) {
  event.preventDefault();
  
  const name = document.getElementById('deployName').value.trim();
  const userId = document.getElementById('deployOwner').value;
  const os = document.getElementById('deployOS').value;
  const cpu = document.getElementById('deployCPU').value;
  const ram = document.getElementById('deployRAM').value;
  const disk = document.getElementById('deployDisk').value;
  const password = document.getElementById('deployPassword').value;

  if (!name || !userId || !os || !password) {
    showToast("Please fill in all deployment fields.", "error");
    return;
  }

  // Open Log Modal overlay
  const modal = document.getElementById('deployLogModal');
  const closeBtnH = document.getElementById('closeDeployModal');
  const closeBtnB = document.getElementById('btn-close-deploy');
  const logsArea = document.getElementById('deploy-terminal-logs');
  const progressFill = document.getElementById('deploy-progress-fill');

  modal.classList.add('active');
  closeBtnH.style.display = 'none';
  closeBtnB.style.display = 'none';
  progressFill.style.width = '0%';
  progressFill.style.backgroundColor = 'var(--color-cool)';
  logsArea.innerHTML = '<div style="color: #7de8a3;">[SYSTEM] Initiating server side EventStream connection...</div>';

  // Open SSE stream
  const url = `/api/admin/vps/deploy-stream?name=${name}&user_id=${userId}&os=${os}&cpu=${cpu}&ram=${ram}&disk=${disk}&root_password=${encodeURIComponent(password)}`;
  const source = new EventSource(url);
  
  let currentProgress = 5;

  source.onmessage = function(event) {
    const line = event.data;
    const lineDiv = document.createElement('div');
    lineDiv.textContent = line;
    
    // Add colored line styling based on keywords
    if (line.includes('[SUCCESS]')) {
      lineDiv.style.color = '#7de8a3';
      lineDiv.style.fontWeight = 'bold';
      progressFill.style.width = '100%';
      progressFill.style.backgroundColor = 'var(--color-accent)';
      
      // Enable close
      closeBtnH.style.display = 'block';
      closeBtnB.style.display = 'block';
      showToast("VPS Instance deployed successfully!", "success");
      
      // Reset form
      document.getElementById('deployVPSForm').reset();
      updateDeployCPUVal(2);
      updateDeployRAMVal(2048);
      updateDeployDiskVal(20);
      
      source.close();
    } else if (line.includes('[ERROR]')) {
      lineDiv.style.color = '#ea7373';
      lineDiv.style.fontWeight = 'bold';
      progressFill.style.backgroundColor = 'var(--color-danger)';
      
      // Enable close
      closeBtnH.style.display = 'block';
      closeBtnB.style.display = 'block';
      showToast("Deployment failed. See logs.", "error");
      source.close();
    } else if (line.includes('[INFO]')) {
      lineDiv.style.color = '#d6e87d';
      currentProgress = Math.min(95, currentProgress + 12);
      progressFill.style.width = `${currentProgress}%`;
    }
    
    logsArea.appendChild(lineDiv);
    logsArea.scrollTop = logsArea.scrollHeight;
  };

  source.onerror = function(err) {
    console.error("SSE stream error: ", err);
    const errDiv = document.createElement('div');
    errDiv.textContent = "[ERROR] Connection lost or stream error. Stream closed.";
    errDiv.style.color = '#ea7373';
    logsArea.appendChild(errDiv);
    
    progressFill.style.backgroundColor = 'var(--color-danger)';
    closeBtnH.style.display = 'block';
    closeBtnB.style.display = 'block';
    source.close();
  };
};

window.closeDeployModal = function() {
  document.getElementById('deployLogModal').classList.remove('active');
};
