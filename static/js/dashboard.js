// Client LXC Control Panel JS Actions

let currentVpsId = null;
let vpsList = [];
let statsInterval = null;
let gridStatsInterval = null;
let resourceChart = null;
let terminalObj = null;
let socketObj = null;
let isChartPrepopulated = false;

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
          } else {
            panel.classList.remove('active');
          }
        });

        // Close terminal session if switching tabs
        if (targetId !== 'panel-console' && socketObj) {
          socketObj.disconnect();
          socketObj = null;
        }

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

  // 2. Active VPS Dropdown Selector Change
  const selector = document.getElementById('vps-selector');
  if (selector) {
    selector.addEventListener('change', (e) => {
      const selectedId = parseInt(e.target.value);
      selectAndManageVPS(selectedId);
    });
  }

  // 3. Protocol switch for firewall form
  const fwProtocol = document.getElementById('fwProtocol');
  const fwPortGroup = document.getElementById('fwPortGroup');
  const fwPort = document.getElementById('fwPort');
  if (fwProtocol && fwPortGroup && fwPort) {
    fwProtocol.addEventListener('change', () => {
      if (fwProtocol.value === 'ICMP') {
        fwPortGroup.style.display = 'none';
        fwPort.required = false;
        fwPort.value = '0';
      } else {
        fwPortGroup.style.display = 'block';
        fwPort.required = true;
        fwPort.value = '';
      }
    });
  }

  // Fetch all assigned servers
  fetchClientVPSList();
});

// Fetch assigned containers
async function fetchClientVPSList() {
  try {
    const response = await fetch('/api/client/vps');
    vpsList = await window.handleFetchResponse(response);
    
    const selectorContainer = document.getElementById('vps-selector-container');
    const activeWrapper = document.getElementById('vps-active-wrapper');
    const emptyState = document.getElementById('vps-empty-state');
    const selector = document.getElementById('vps-selector');

    if (vpsList.length === 0) {
      selectorContainer.style.display = 'none';
      activeWrapper.style.display = 'none';
      emptyState.style.display = 'block';
      return;
    }

    // Show panel wrapper
    selectorContainer.style.display = 'none'; // Keep dropdown wrapper hidden
    activeWrapper.style.display = 'block';
    emptyState.style.display = 'none';

    // Populate drop select for legacy/compatibility reasons
    selector.innerHTML = '';
    vpsList.forEach(vps => {
      const opt = document.createElement('option');
      opt.value = vps.id;
      opt.textContent = vps.container_name;
      selector.appendChild(opt);
    });

    // Render the grid cards
    renderVPSGrid();

    // Start background stats polling for the grid
    startGridStatsPolling();

  } catch (err) {
    showToast(`Failed to load server list: ${err.message}`, 'error');
  }
}

// Render the grid layout of VPS cards
function renderVPSGrid() {
  const gridContainer = document.getElementById('vps-grid-container');
  if (!gridContainer) return;

  gridContainer.innerHTML = '';

  vpsList.forEach(vps => {
    const isUbuntu = vps.os.toLowerCase().includes('ubuntu');
    const osName = isUbuntu ? 'Ubuntu' : 'Debian';
    const osClass = isUbuntu ? 'os-ubuntu' : 'os-debian';
    const osLetter = isUbuntu ? 'U' : 'D';

    const cardHtml = `
      <div class="vps-grid-card" id="vps-card-${vps.id}">
        <!-- Card Header -->
        <div class="vps-card-header">
          <div class="vps-card-os-badge ${osClass}">
            <span class="os-icon-logo">${osLetter}</span>
            <span>${osName}</span>
          </div>
          <div class="vps-card-status-badge status-${vps.status}" id="card-status-badge-${vps.id}">
            <span class="status-dot"></span>
            <span class="status-text">${vps.status}</span>
          </div>
        </div>
        
        <!-- Card Body -->
        <div class="vps-card-body">
          <h4 class="vps-card-name" title="${vps.container_name}">${vps.container_name}</h4>
          
          <div class="vps-card-ip-section">
            <code class="vps-card-ip" id="card-ip-${vps.id}">Fetching IP...</code>
            <button class="btn-copy-ip" onclick="copyCardIP(event, ${vps.id})" title="Copy IP Address">
              <i data-lucide="copy"></i>
            </button>
          </div>
          
          <!-- Specs -->
          <div class="vps-card-specs-row">
            <div class="spec-item" title="CPU Limit">
              <i data-lucide="cpu"></i>
              <span>${vps.cpu} Core${vps.cpu > 1 ? 's' : ''}</span>
            </div>
            <div class="spec-item" title="Disk Capacity">
              <i data-lucide="hard-drive"></i>
              <span>${vps.disk} GB</span>
            </div>
            <div class="spec-item" title="RAM Allocation">
              <i data-lucide="layers"></i>
              <span>${vps.ram} MB</span>
            </div>
          </div>
          
          <!-- Live Resource Bars -->
          <div class="vps-card-meters" id="card-meters-${vps.id}">
            <div class="card-meter-item">
              <div class="meter-label">
                <span>CPU Utilization</span>
                <span class="meter-val" id="card-cpu-val-${vps.id}">--</span>
              </div>
              <div class="meter-track">
                <div class="meter-bar" id="card-cpu-bar-${vps.id}" style="width: 0%"></div>
              </div>
            </div>
            <div class="card-meter-item">
              <div class="meter-label">
                <span>RAM Usage</span>
                <span class="meter-val" id="card-ram-val-${vps.id}">--</span>
              </div>
              <div class="meter-track">
                <div class="meter-bar" id="card-ram-bar-${vps.id}" style="width: 0%"></div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Card Footer -->
        <div class="vps-card-footer">
          <div class="vps-card-power-controls">
            <button class="btn-power start" id="card-btn-start-${vps.id}" onclick="triggerCardAction(event, ${vps.id}, 'start')" title="Start Server">
              <i data-lucide="play"></i>
            </button>
            <button class="btn-power stop" id="card-btn-stop-${vps.id}" onclick="triggerCardAction(event, ${vps.id}, 'stop')" title="Stop Server">
              <i data-lucide="square"></i>
            </button>
            <button class="btn-power reboot" id="card-btn-reboot-${vps.id}" onclick="triggerCardAction(event, ${vps.id}, 'restart')" title="Reboot Server">
              <i data-lucide="refresh-cw"></i>
            </button>
          </div>
          
          <button class="btn btn-secondary btn-manage" onclick="selectAndManageVPS(${vps.id})">
            <i data-lucide="sliders"></i> Manage
          </button>
        </div>
      </div>
    `;
    gridContainer.insertAdjacentHTML('beforeend', cardHtml);
  });

  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

// Start polling status/metrics for grid view
function startGridStatsPolling() {
  if (gridStatsInterval) clearInterval(gridStatsInterval);
  
  // Initial quick poll
  vpsList.forEach(vps => {
    fetchSingleCardStats(vps.id);
  });

  gridStatsInterval = setInterval(() => {
    vpsList.forEach(vps => {
      fetchSingleCardStats(vps.id);
    });
  }, 4000);
}

// Fetch stats for a single card in grid
async function fetchSingleCardStats(vpsId) {
  try {
    const response = await fetch(`/api/client/vps/${vpsId}/stats`);
    if (!response.ok) return;
    const stats = await response.json();

    // Update IP in card
    const ipEl = document.getElementById(`card-ip-${vpsId}`);
    if (ipEl) ipEl.textContent = stats.ip || 'N/A';

    // Update Status Badge in card
    const badge = document.getElementById(`card-status-badge-${vpsId}`);
    if (badge) {
      badge.className = `vps-card-status-badge status-${stats.status}`;
      const txt = badge.querySelector('.status-text');
      if (txt) txt.textContent = stats.status;
    }

    // Update power button states
    const startBtn = document.getElementById(`card-btn-start-${vpsId}`);
    const stopBtn = document.getElementById(`card-btn-stop-${vpsId}`);
    const rebootBtn = document.getElementById(`card-btn-reboot-${vpsId}`);

    if (startBtn && stopBtn && rebootBtn) {
      if (stats.status === 'running') {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        rebootBtn.disabled = false;
      } else if (stats.status === 'stopped') {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        rebootBtn.disabled = true;
      } else {
        startBtn.disabled = true;
        stopBtn.disabled = true;
        rebootBtn.disabled = true;
      }
    }

    // Update meters
    const cpuValEl = document.getElementById(`card-cpu-val-${vpsId}`);
    const cpuBarEl = document.getElementById(`card-cpu-bar-${vpsId}`);
    const ramValEl = document.getElementById(`card-ram-val-${vpsId}`);
    const ramBarEl = document.getElementById(`card-ram-bar-${vpsId}`);

    const cpuVal = stats.status === 'running' ? stats.cpu : 0.0;
    const ramMB = stats.status === 'running' ? stats.ram_used : 0;
    const ramPercent = Math.min(100, Math.round((ramMB / stats.ram_limit) * 100));

    if (cpuValEl) cpuValEl.textContent = stats.status === 'running' ? `${cpuVal}%` : 'Offline';
    if (cpuBarEl) {
      cpuBarEl.style.width = `${cpuVal}%`;
      if (cpuVal > 80) cpuBarEl.className = 'meter-bar high';
      else cpuBarEl.className = 'meter-bar';
    }
    if (ramValEl) ramValEl.textContent = stats.status === 'running' ? `${ramMB} MB / ${stats.ram_limit} MB` : 'Offline';
    if (ramBarEl) {
      ramBarEl.style.width = `${ramPercent}%`;
      if (ramPercent > 80) ramBarEl.className = 'meter-bar high';
      else ramBarEl.className = 'meter-bar';
    }

  } catch (err) {
    console.error(`Error polling stats for VPS ${vpsId}:`, err);
  }
}

// Power action trigger for a card in grid
window.triggerCardAction = async function(event, vpsId, action) {
  if (event) {
    event.stopPropagation();
  }
  
  // Disable buttons temporarily
  const startBtn = document.getElementById(`card-btn-start-${vpsId}`);
  const stopBtn = document.getElementById(`card-btn-stop-${vpsId}`);
  const rebootBtn = document.getElementById(`card-btn-reboot-${vpsId}`);
  
  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;
  if (rebootBtn) rebootBtn.disabled = true;

  showToast(`Initiating power state request: ${action}...`, 'info');

  try {
    const response = await fetch(`/api/client/vps/${vpsId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action })
    });
    const data = await window.handleFetchResponse(response);
    showToast(data.message, 'success');
    
    // Quick reload
    setTimeout(() => {
      fetchSingleCardStats(vpsId);
    }, 1000);
  } catch (err) {
    showToast(err.message, 'error');
    fetchSingleCardStats(vpsId);
  }
};

// Clipboard copy helpers
window.copyCardIP = function(event, vpsId) {
  if (event) {
    event.stopPropagation();
  }
  const ipText = document.getElementById(`card-ip-${vpsId}`).textContent;
  if (!ipText || ipText.includes('Fetching') || ipText === 'N/A') return;
  navigator.clipboard.writeText(ipText).then(() => {
    showToast("IP Address copied to clipboard!", "success");
  }).catch(err => {
    showToast("Failed to copy IP address.", "error");
  });
};

window.copyOverviewIP = function() {
  const ipText = document.getElementById('ip-val').textContent;
  if (!ipText || ipText.includes('Fetching') || ipText === 'N/A') return;
  navigator.clipboard.writeText(ipText).then(() => {
    showToast("IP Address copied to clipboard!", "success");
  }).catch(err => {
    showToast("Failed to copy IP address.", "error");
  });
};

// Select a VPS from the grid to manage in detailed tabs
window.selectAndManageVPS = function(vpsId) {
  // Clear grid polling
  if (gridStatsInterval) {
    clearInterval(gridStatsInterval);
    gridStatsInterval = null;
  }

  currentVpsId = vpsId;
  const currentVPS = vpsList.find(v => v.id === vpsId);
  if (!currentVPS) return;

  isChartPrepopulated = false;

  // Show detailed management tabs headers and links in the sidebar
  document.getElementById('menu-mgmt-header').style.display = 'block';
  
  const detailedMenuIds = [
    'menu-overview', 'menu-console', 'menu-snapshots', 
    'menu-backups', 'menu-firewall', 'menu-rebuild', 'menu-settings'
  ];
  detailedMenuIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'block';
  });

  // Populate Active Server Card widget in sidebar
  const isUbuntu = currentVPS.os.toLowerCase().includes('ubuntu');
  const osLetter = isUbuntu ? 'U' : 'D';
  document.getElementById('sidebar-vps-os-icon').textContent = osLetter;
  document.getElementById('sidebar-vps-name').textContent = currentVPS.container_name;
  document.getElementById('sidebar-vps-ip').textContent = 'Fetching IP...';
  
  // Set correct background classes for OS badge in sidebar card
  const osIcon = document.getElementById('sidebar-vps-os-icon');
  if (osIcon) {
    osIcon.className = `active-os-icon ${isUbuntu ? 'os-ubuntu' : 'os-debian'}`;
  }

  const activeCard = document.getElementById('active-server-card');
  if (activeCard) activeCard.style.display = 'flex';

  // Update Breadcrumb in Header
  document.getElementById('header-vps-name').textContent = currentVPS.container_name;
  document.getElementById('header-breadcrumb').style.display = 'flex';

  // Deactivate "My Instances" in sidebar, and activate "Overview" menu item
  const menuLinks = document.querySelectorAll('.db-menu-item');
  menuLinks.forEach(item => item.classList.remove('active'));
  document.getElementById('menu-overview').classList.add('active');

  // Deactivate all panels and activate panel-overview
  const panels = document.querySelectorAll('.db-tab-panel');
  panels.forEach(p => p.classList.remove('active'));
  document.getElementById('panel-overview').classList.add('active');

  // Sync the legacy dropdown selector value
  const selector = document.getElementById('vps-selector');
  if (selector) selector.value = vpsId;

  // Load details
  loadVPSDetails(vpsId);
};

// Switch back to "My Instances" grid screen
window.switchToInstances = function() {
  // Clear active server polling
  if (statsInterval) {
    clearInterval(statsInterval);
    statsInterval = null;
  }

  // Clear current active vps
  currentVpsId = null;

  // Disconnect active console socket
  if (socketObj) {
    socketObj.disconnect();
    socketObj = null;
  }

  // Hide detailed management menu headers and links in the sidebar
  document.getElementById('menu-mgmt-header').style.display = 'none';
  
  const detailedMenuIds = [
    'menu-overview', 'menu-console', 'menu-snapshots', 
    'menu-backups', 'menu-firewall', 'menu-rebuild', 'menu-settings'
  ];
  detailedMenuIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  // Hide sidebar active card and header breadcrumb
  const activeCard = document.getElementById('active-server-card');
  if (activeCard) activeCard.style.display = 'none';
  document.getElementById('header-breadcrumb').style.display = 'none';

  // Deactivate all sidebar items, activate "My Instances"
  const menuItems = document.querySelectorAll('.db-menu-item');
  menuItems.forEach(item => item.classList.remove('active'));
  document.getElementById('menu-instances').classList.add('active');

  // Deactivate all tab panels, activate "panel-instances"
  const panels = document.querySelectorAll('.db-tab-panel');
  panels.forEach(p => p.classList.remove('active'));
  document.getElementById('panel-instances').classList.add('active');

  // Start grid polling again
  startGridStatsPolling();
};

// Get Selected Container Name helper
function getActiveVPSContainerName() {
  const v = vpsList.find(item => item.id === currentVpsId);
  return v ? v.container_name : null;
}

// Load specifications and metrics for active container
async function loadVPSDetails(vpsId) {
  if (!vpsId) return;

  const currentVPS = vpsList.find(v => v.id === vpsId);
  if (!currentVPS) return;

  // Initialize general data
  document.getElementById('info-os').textContent = currentVPS.os;
  document.getElementById('info-created').textContent = currentVPS.created_at.split(' ')[0];
  document.getElementById('cpu-core-count').textContent = currentVPS.cpu;
  document.getElementById('ram-limit-text').textContent = `${currentVPS.ram} MB`;
  document.getElementById('disk-limit-text').textContent = `${currentVPS.disk} GB`;

  // Fetch Live Metrics and subcomponents lists
  fetchLiveStats(vpsId);
  fetchSnapshots(vpsId);
  fetchBackups(vpsId);
  fetchFirewall(vpsId);

  // Initialize Performance line graph if not initialized
  initResourceChart();

  // Reset polling interval
  if (statsInterval) clearInterval(statsInterval);
  statsInterval = setInterval(() => {
    fetchLiveStats(currentVpsId);
  }, 4000);
}

// Fetch stats, update meters and status badges
async function fetchLiveStats(vpsId) {
  try {
    const response = await fetch(`/api/client/vps/${vpsId}/stats`);
    if (!response.ok) return;
    const stats = await response.json();

    // Update IP and Uptime in Overview and Sidebar widget
    document.getElementById('ip-val').textContent = stats.ip || 'N/A';
    document.getElementById('uptime-val').textContent = stats.uptime || 'Offline';
    
    const sidebarIp = document.getElementById('sidebar-vps-ip');
    if (sidebarIp) sidebarIp.textContent = stats.ip || 'N/A';

    // Status classes
    const statusText = document.getElementById('status-text');
    const statusVal = document.getElementById('status-val');
    if (statusText) statusText.textContent = stats.status;
    
    if (statusVal) {
      // Reset classes
      statusVal.className = 'db-stat-value';
      const statusDot = statusVal.querySelector('.status-dot');
      if (statusDot) statusDot.className = 'status-dot';
      
      if (stats.status === 'running') {
        statusVal.classList.add('running');
      } else if (stats.status === 'stopped') {
        statusVal.classList.add('stopped');
        if (statusDot) statusDot.classList.add('stopped');
      } else {
        statusVal.classList.add('suspended');
        if (statusDot) statusDot.classList.add('suspended');
      }
    }

    // Sync Sidebar Active Card Status Badge
    const sidebarStatus = document.getElementById('sidebar-vps-status');
    const sidebarStatusText = document.getElementById('sidebar-vps-status-text');
    if (sidebarStatus && sidebarStatusText) {
      sidebarStatus.className = `vps-status-badge ${stats.status}`;
      sidebarStatusText.textContent = stats.status;
    }

    // Toggle button availabilities
    const startBtn = document.getElementById('btn-start');
    const stopBtn = document.getElementById('btn-stop');
    const rebootBtn = document.getElementById('btn-reboot');
    
    if (startBtn && stopBtn && rebootBtn) {
      if (stats.status === 'running') {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        rebootBtn.disabled = false;
      } else if (stats.status === 'stopped') {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        rebootBtn.disabled = true;
      } else {
        // suspended state
        startBtn.disabled = true;
        stopBtn.disabled = true;
        rebootBtn.disabled = true;
      }
    }

    // Compute metrics
    const cpuVal = stats.status === 'running' ? stats.cpu : 0.0;
    const ramMB = stats.status === 'running' ? stats.ram_used : 0;
    const diskGB = stats.disk_used;

    const ramPercent = Math.min(100, Math.round((ramMB / stats.ram_limit) * 100));
    const diskPercent = Math.min(100, Math.round((diskGB / stats.disk_limit) * 100));

    // Update meters text
    document.getElementById('cpu-percent').textContent = `${cpuVal}%`;
    const cpuBar = document.getElementById('cpu-bar');
    if (cpuBar) {
      cpuBar.style.width = `${cpuVal}%`;
      if (cpuVal > 80) cpuBar.className = 'meter-bar high';
      else cpuBar.className = 'meter-bar';
    }

    document.getElementById('ram-usage-text').textContent = `${ramMB} MB / ${stats.ram_limit} MB`;
    const ramBar = document.getElementById('ram-bar');
    if (ramBar) {
      ramBar.style.width = `${ramPercent}%`;
      if (ramPercent > 80) ramBar.className = 'meter-bar high';
      else ramBar.className = 'meter-bar';
    }

    document.getElementById('disk-usage-text').textContent = `${diskGB} GB / ${stats.disk_limit} GB`;
    const diskBar = document.getElementById('disk-bar');
    if (diskBar) {
      diskBar.style.width = `${diskPercent}%`;
      if (diskPercent > 80) diskBar.className = 'meter-bar high';
      else diskBar.className = 'meter-bar';
    }

    // Update line chart
    if (resourceChart) {
      if (!isChartPrepopulated && stats.history && stats.history.length > 0) {
        const histData = stats.history.slice(-10);
        resourceChart.data.datasets[0].data = histData.map(h => h.cpu);
        resourceChart.data.datasets[1].data = histData.map(h => h.ram_percent);
        isChartPrepopulated = true;
      } else {
        resourceChart.data.datasets[0].data.shift();
        resourceChart.data.datasets[0].data.push(cpuVal);
        resourceChart.data.datasets[1].data.shift();
        resourceChart.data.datasets[1].data.push(ramPercent);
      }
      resourceChart.update('none');
    }

  } catch (err) {
    console.error("Stats polling error:", err);
  }
}

// Power Action Triggers
window.triggerVPSAction = async function(action) {
  if (!currentVpsId) return;
  
  const startBtn = document.getElementById('btn-start');
  const stopBtn = document.getElementById('btn-stop');
  const rebootBtn = document.getElementById('btn-reboot');
  
  startBtn.disabled = true;
  stopBtn.disabled = true;
  rebootBtn.disabled = true;

  showToast(`Initiating power state request: ${action}...`, 'info');

  try {
    const response = await fetch(`/api/client/vps/${currentVpsId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action })
    });
    const data = await window.handleFetchResponse(response);
    showToast(data.message, 'success');
    
    // Quick reload
    setTimeout(() => {
      fetchLiveStats(currentVpsId);
    }, 1000);
  } catch (err) {
    showToast(err.message, 'error');
    fetchLiveStats(currentVpsId);
  }
};

// 4. Chart JS Initialization
function initResourceChart() {
  if (resourceChart) return;
  const canvas = document.getElementById('resourceChart');
  if (!canvas) return;

  const colorCool = getComputedStyle(document.documentElement).getPropertyValue('--color-cool').trim() || '#93BFC7';
  const colorAccent = getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim() || '#ABE7B2';

  resourceChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels: ['10m ago', '9m ago', '8m ago', '7m ago', '6m ago', '5m ago', '4m ago', '3m ago', '2m ago', 'Just now'],
      datasets: [
        {
          label: 'CPU Usage (%)',
          data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
          borderColor: colorCool,
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          pointBackgroundColor: colorCool,
          pointRadius: 3
        },
        {
          label: 'Memory Allocation (%)',
          data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
          borderColor: colorAccent,
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          pointBackgroundColor: colorAccent,
          pointRadius: 3
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { font: { family: 'Inter', size: 11 } } }
      },
      scales: {
        y: { beginAtZero: true, max: 100, grid: { color: '#f0f4f1' }, ticks: { font: { family: 'Inter' } } },
        x: { grid: { display: false }, ticks: { font: { family: 'Inter' } } }
      }
    }
  });
}

// 5. Web Console Connections via Socket.IO + Real PTY
window.connectTerminal = function() {
  const container = document.getElementById('terminal-container');
  const activeVpsName = getActiveVPSContainerName();

  if (!activeVpsName) {
    showToast("No active container selected.", "error");
    return;
  }

  container.innerHTML = '';

  // Create xterm.js terminal
  terminalObj = new Terminal({
    cursorBlink: true,
    fontFamily: 'Courier New, monospace',
    fontSize: 13,
    theme: {
      background: '#000000',
      foreground: '#ffffff'
    }
  });

  let fitAddon;
  if (window.FitAddon && window.FitAddon.FitAddon) {
    fitAddon = new window.FitAddon.FitAddon();
    terminalObj.loadAddon(fitAddon);
  }

  terminalObj.open(container);
  if (fitAddon) {
    fitAddon.fit();
  }

  terminalObj.write('Connecting to real LXC container shell...\r\n');

  // Disconnect previous socket if exists
  if (socketObj) {
    socketObj.disconnect();
    socketObj = null;
  }

  // Connect via Socket.IO
  socketObj = io();

  socketObj.on('connect', () => {
    terminalObj.write('\x1b[32mSocket connected. Attaching to container...\x1b[0m\r\n');
    socketObj.emit('terminal_connect', { container_name: activeVpsName });
  });

  socketObj.on('terminal_output', (data) => {
    terminalObj.write(data.output);
  });

  socketObj.on('disconnect', () => {
    terminalObj.write('\r\n\x1b[31m*** Console connection terminated ***\x1b[0m\r\n');
  });

  socketObj.on('connect_error', () => {
    terminalObj.write('\r\n\x1b[31m*** Terminal connection failure ***\x1b[0m\r\n');
  });

  // Send keyboard input to backend PTY
  terminalObj.onData((data) => {
    if (socketObj && socketObj.connected) {
      socketObj.emit('terminal_input', { input: data });
    }
  });

  // Handle terminal resize
  const sendResize = () => {
    if (fitAddon) fitAddon.fit();
    if (socketObj && socketObj.connected && terminalObj) {
      socketObj.emit('terminal_resize', { cols: terminalObj.cols, rows: terminalObj.rows });
    }
  };

  window.addEventListener('resize', sendResize);
  terminalObj.onResize(({ cols, rows }) => {
    if (socketObj && socketObj.connected) {
      socketObj.emit('terminal_resize', { cols, rows });
    }
  });
};

// 6. Snapshots
async function fetchSnapshots(vpsId) {
  try {
    const res = await fetch(`/api/client/vps/${vpsId}/snapshots`);
    const snaps = await window.handleFetchResponse(res);
    
    const tbody = document.getElementById('snapshots-table-body');
    tbody.innerHTML = '';
    
    if (snaps.length === 0) {
      tbody.innerHTML = `<tr><td colspan="3" class="text-center" style="color: var(--color-text-muted);">No snapshots saved.</td></tr>`;
      return;
    }

    snaps.forEach(s => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><strong>${s.name.split('-')[0]}</strong> <span style="font-size:11px; color:var(--color-text-muted);">(${s.name})</span></td>
        <td>${s.created_at}</td>
        <td class="text-right">
          <button class="btn btn-primary btn-small" onclick="restoreSnapshot('${s.name}')" style="margin-right: 6px;"><i data-lucide="refresh-cw" style="width: 12px; height:12px;"></i> Restore</button>
          <button class="btn btn-outline btn-small" onclick="deleteSnapshot('${s.name}')" style="color: var(--color-danger); border-color:#f6d1d1;"><i data-lucide="trash" style="width: 12px; height:12px;"></i> Delete</button>
        </td>
      `;
      tbody.appendChild(row);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    console.error(err);
  }
}

window.handleCreateSnapshot = async function(event) {
  event.preventDefault();
  if (!currentVpsId) return;

  const snapNameInput = document.getElementById('snapName');
  const snapName = snapNameInput.value.trim();
  const submitBtn = event.target.querySelector('button[type="submit"]');

  submitBtn.disabled = true;
  showToast("Saving container state snapshot...", "info");

  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/snapshots`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: snapName })
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    snapNameInput.value = '';
    fetchSnapshots(currentVpsId);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    submitBtn.disabled = false;
  }
};

window.restoreSnapshot = async function(name) {
  if (!currentVpsId) return;
  if (!confirm(`Are you sure you want to restore snapshot ${name.split('-')[0]}? The container will revert back to this saved state.`)) return;

  showToast("Reverting system state...", "info");
  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/snapshots/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    fetchLiveStats(currentVpsId);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

window.deleteSnapshot = async function(name) {
  if (!currentVpsId) return;
  if (!confirm(`Confirm deleting state snapshot: ${name.split('-')[0]}?`)) return;

  showToast("Removing snapshot archive...", "info");
  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/snapshots/${name}`, {
      method: 'DELETE'
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    fetchSnapshots(currentVpsId);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// 7. Backups
async function fetchBackups(vpsId) {
  try {
    const res = await fetch(`/api/client/vps/${vpsId}/backups`);
    const backups = await window.handleFetchResponse(res);
    
    const tbody = document.getElementById('backups-table-body');
    tbody.innerHTML = '';
    
    if (backups.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-center" style="color: var(--color-text-muted);">No tarball backups built.</td></tr>`;
      return;
    }

    backups.forEach(b => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td style="font-family: monospace; font-size:12px;">${b.filename}</td>
        <td>${b.size}</td>
        <td>${b.created_at}</td>
        <td class="text-right">
          <a href="#" onclick="showToast('Starting file download...', 'success')" class="btn btn-outline btn-small"><i data-lucide="download" style="width:12px; height:12px;"></i> Download</a>
        </td>
      `;
      tbody.appendChild(row);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    console.error(err);
  }
}

window.triggerBackup = async function() {
  if (!currentVpsId) return;

  showToast("Packing container archive (lxc export)...", "info");
  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/backups`, {
      method: 'POST'
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    fetchBackups(currentVpsId);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// 8. Firewall
async function fetchFirewall(vpsId) {
  try {
    const res = await fetch(`/api/client/vps/${vpsId}/firewall`);
    const rules = await window.handleFetchResponse(res);
    
    const tbody = document.getElementById('firewall-table-body');
    tbody.innerHTML = '';
    
    if (rules.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-center" style="color: var(--color-text-muted);">No firewall rules active. All traffic is ALLOWED by default.</td></tr>`;
      return;
    }

    rules.forEach(r => {
      const portText = r.protocol === 'ICMP' ? 'All (ICMP)' : r.port;
      const badgeClass = r.action === 'ALLOW' ? 'badge-resolved' : 'badge-open';
      
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><strong>${r.protocol}</strong></td>
        <td style="font-family: monospace;">${portText}</td>
        <td><span class="badge ${badgeClass}">${r.action}</span></td>
        <td style="font-size:12px; color:var(--color-text-muted);">${r.created_at.split(' ')[0]}</td>
        <td class="text-right">
          <button class="btn btn-outline btn-small" onclick="deleteFirewallRule(${r.id})" style="color: var(--color-danger); border-color:#f6d1d1;"><i data-lucide="x-circle" style="width:12px; height:12px;"></i> Remove</button>
        </td>
      `;
      tbody.appendChild(row);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    console.error(err);
  }
}

window.handleAddFirewall = async function(event) {
  event.preventDefault();
  if (!currentVpsId) return;

  const protocol = document.getElementById('fwProtocol').value;
  const port = document.getElementById('fwPort').value;
  const action = document.getElementById('fwAction').value;
  const submitBtn = event.target.querySelector('button[type="submit"]');

  submitBtn.disabled = true;
  showToast("Updating hypervisor routing rules...", "info");

  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/firewall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ protocol, port, action })
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    
    // reset form
    document.getElementById('firewallForm').reset();
    document.getElementById('fwPortGroup').style.display = 'block';
    document.getElementById('fwPort').required = true;
    
    fetchFirewall(currentVpsId);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    submitBtn.disabled = false;
  }
};

window.deleteFirewallRule = async function(ruleId) {
  if (!currentVpsId) return;

  showToast("Removing rule policy...", "info");
  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/firewall/${ruleId}`, {
      method: 'DELETE'
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    fetchFirewall(currentVpsId);
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// 9. Reinstall OS
window.handleReinstall = async function(event) {
  event.preventDefault();
  if (!currentVpsId) return;

  const os = document.getElementById('reinstallOS').value;
  const password = document.getElementById('reinstallPassword').value;
  const confirmCh = document.getElementById('reinstallConfirm');
  const submitBtn = event.target.querySelector('button[type="submit"]');

  if (!confirmCh.checked) {
    showToast("Please check the confirmation box to trigger reinstall.", "error");
    return;
  }

  if (!confirm("Are you 100% sure you want to format and rebuild this server instance? All configuration parameters will be wiped.")) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "Formatting & Provisioning...";
  showToast("Initiating formatting, OS wipe, and lxc launch...", "info");

  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/reinstall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ os, root_password: password })
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    
    // Clear forms and reset
    document.getElementById('reinstallForm').reset();
    
    // Update container lists local caching data
    const idx = vpsList.findIndex(v => v.id === currentVpsId);
    if (idx !== -1) {
      vpsList[idx].os = os;
    }

    setTimeout(() => {
      window.location.reload();
    }, 1500);
  } catch (err) {
    showToast(err.message, 'error');
    submitBtn.disabled = false;
    submitBtn.textContent = "Rebuild Container";
  }
};

// 10. Settings - Rename & Credentials modification
window.handleRename = async function(event) {
  event.preventDefault();
  if (!currentVpsId) return;

  const newNameInput = document.getElementById('vpsNewName');
  const newName = newNameInput.value.trim();
  const submitBtn = event.target.querySelector('button[type="submit"]');

  submitBtn.disabled = true;
  showToast("Moving container profile...", "info");

  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName })
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    newNameInput.value = '';
    
    // Trigger list reload
    setTimeout(() => {
      window.location.reload();
    }, 1000);
  } catch (err) {
    showToast(err.message, 'error');
    submitBtn.disabled = false;
  }
};

window.handleChangePassword = async function(event) {
  event.preventDefault();
  if (!currentVpsId) return;

  const pwdInput = document.getElementById('rootPassword');
  const pwd = pwdInput.value;
  const submitBtn = event.target.querySelector('button[type="submit"]');

  submitBtn.disabled = true;
  showToast("Injecting user credentials inside container...", "info");

  try {
    const res = await fetch(`/api/client/vps/${currentVpsId}/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_password: pwd })
    });
    const data = await window.handleFetchResponse(res);
    showToast(data.message, 'success');
    pwdInput.value = '';
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    submitBtn.disabled = false;
  }
};
