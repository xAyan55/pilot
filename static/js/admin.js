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
              loadNodesDropdown();
              loadDiscordUsers();
            } else if (targetId === 'panel-containers') {
              loadContainers();
            } else if (targetId === 'panel-users') {
              loadAdminUsers();
            } else if (targetId === 'panel-nodes') {
              loadAdminNodes();
            } else if (targetId === 'panel-logs') {
              loadLogs();
            } else if (targetId === 'panel-customization') {
              // Set branding tab active by default
              const brandingBtn = document.querySelector('.subnav-btn[data-subtarget="subpanel-branding"]');
              if (brandingBtn) brandingBtn.click();
            } else if (targetId === 'panel-apikeys') {
              loadAdminApiKeys();
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

  // 2. Customization Subpanel Switcher
  const subnavBtns = document.querySelectorAll('.subnav-btn');
  const subpanels = document.querySelectorAll('.sub-tab-panel');

  if (subnavBtns.length > 0) {
    subnavBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        subnavBtns.forEach(item => item.classList.remove('active'));
        btn.classList.add('active');

        const subtargetId = btn.getAttribute('data-subtarget');
        subpanels.forEach(panel => {
          if (panel.id === subtargetId) {
            panel.classList.add('active');
            panel.style.display = 'block';
            // Trigger specific subtab loads
            if (subtargetId === 'subpanel-plans') {
              loadCustomPlans();
            } else if (subtargetId === 'subpanel-faqs') {
              loadCustomFaqs();
            }
          } else {
            panel.classList.remove('active');
            panel.style.display = 'none';
          }
        });
      });
    });
  }

  // 3. Sync Color Inputs with hex text inputs
  ['Primary', 'Secondary', 'Accent', 'Cool'].forEach(colorName => {
    const picker = document.getElementById(`brandColor${colorName}`);
    const text = document.getElementById(`brandColor${colorName}Text`);
    if (picker && text) {
      picker.addEventListener('input', () => {
        text.value = picker.value.toUpperCase();
      });
      text.addEventListener('input', () => {
        if (/^#[0-9A-Fa-f]{6}$/.test(text.value)) {
          picker.value = text.value;
        }
      });
    }
  });

  // 3b. Bind Theme Presets
  const presetCards = document.querySelectorAll('.theme-preset-card');
  if (presetCards.length > 0) {
    function highlightActivePreset() {
      const currentPrimary = document.getElementById('brandColorPrimaryText')?.value?.toUpperCase();
      const currentSecondary = document.getElementById('brandColorSecondaryText')?.value?.toUpperCase();
      const currentAccent = document.getElementById('brandColorAccentText')?.value?.toUpperCase();
      const currentCool = document.getElementById('brandColorCoolText')?.value?.toUpperCase();

      presetCards.forEach(card => {
        const primary = card.getAttribute('data-primary')?.toUpperCase();
        const secondary = card.getAttribute('data-secondary')?.toUpperCase();
        const accent = card.getAttribute('data-accent')?.toUpperCase();
        const cool = card.getAttribute('data-cool')?.toUpperCase();

        if (currentPrimary === primary &&
            currentSecondary === secondary &&
            currentAccent === accent &&
            currentCool === cool) {
          card.classList.add('active');
        } else {
          card.classList.remove('active');
        }
      });
    }

    presetCards.forEach(card => {
      card.addEventListener('click', () => {
        const primary = card.getAttribute('data-primary');
        const secondary = card.getAttribute('data-secondary');
        const accent = card.getAttribute('data-accent');
        const cool = card.getAttribute('data-cool');

        const colorMapping = {
          Primary: primary,
          Secondary: secondary,
          Accent: accent,
          Cool: cool
        };

        for (const [name, color] of Object.entries(colorMapping)) {
          const picker = document.getElementById(`brandColor${name}`);
          const text = document.getElementById(`brandColor${name}Text`);
          if (picker && text && color) {
            picker.value = color;
            text.value = color.toUpperCase();
          }
        }
        highlightActivePreset();
      });
    });

    // Run active highlight on page load
    highlightActivePreset();

    // Listen to changes to dynamically update preset highlight state
    ['Primary', 'Secondary', 'Accent', 'Cool'].forEach(colorName => {
      const picker = document.getElementById(`brandColor${colorName}`);
      const text = document.getElementById(`brandColor${colorName}Text`);
      if (picker) picker.addEventListener('input', highlightActivePreset);
      if (text) text.addEventListener('input', highlightActivePreset);
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

  // Bind OS cards click events dynamically
  const osCards = document.querySelectorAll('.os-card');
  if (osCards.length > 0) {
    osCards.forEach(card => {
      card.addEventListener('click', () => {
        window.selectOSCard(card);
      });
    });
  }

  // Initialize Page Loader
  loadOverview();

  // Auto refresh overview stats every 3 seconds
  setInterval(() => {
    const activePanel = document.querySelector('.db-tab-panel.active');
    if (activePanel && activePanel.id === 'panel-overview') {
      loadOverview(true); // silent update
    }
  }, 3000);

  // Auto refresh container lists every 15 seconds
  setInterval(() => {
    const activePanel = document.querySelector('.db-tab-panel.active');
    if (activePanel && activePanel.id === 'panel-containers') {
      loadContainers(true);
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
  if (window.updateHostImpactPreview) window.updateHostImpactPreview();
};
window.updateDeployRAMVal = function(val) {
  document.getElementById('ram-slider-val').textContent = `${val} MB`;
  if (window.updateHostImpactPreview) window.updateHostImpactPreview();
};
window.updateDeployDiskVal = function(val) {
  document.getElementById('disk-slider-val').textContent = `${val} GB`;
  if (window.updateHostImpactPreview) window.updateHostImpactPreview();
};

// Helper function to convert HEX color to RGBA for Chart.js
function hexToRgba(hex, alpha) {
  if (!hex || typeof hex !== 'string') return `rgba(0, 0, 0, ${alpha})`;
  hex = hex.trim();
  if (!hex.startsWith('#')) {
    if (hex.includes('rgb')) return hex;
    return `rgba(0, 0, 0, ${alpha})`;
  }
  hex = hex.replace('#', '');
  if (hex.length === 3) {
    hex = hex.split('').map(char => char + char).join('');
  }
  const r = parseInt(hex.substring(0, 2), 16) || 0;
  const g = parseInt(hex.substring(2, 4), 16) || 0;
  const b = parseInt(hex.substring(4, 6), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Update the real-time Chart.js line graph
function updateHostStatsChart(history) {
  try {
    if (!history || !Array.isArray(history)) return;
    const labels = history.map(h => h.timestamp);
    const cpuData = history.map(h => h.cpu);
    const ramData = history.map(h => h.ram);

    if (window.hostStatsChart && window.hostStatsChart instanceof Chart) {
      window.hostStatsChart.data.labels = labels;
      window.hostStatsChart.data.datasets[0].data = cpuData;
      window.hostStatsChart.data.datasets[1].data = ramData;
      window.hostStatsChart.update('none'); // silent update
    } else {
      const canvas = document.getElementById('hostStatsChart');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');

      // Get dynamic styles from HTML document
      const style = getComputedStyle(document.documentElement);
      const accentColor = style.getPropertyValue('--color-accent').trim() || '#ABE7B2';
      const coolColor = style.getPropertyValue('--color-cool').trim() || '#93BFC7';
      const textMainColor = style.getPropertyValue('--color-text-main').trim() || '#0f172a';
      const textMutedColor = style.getPropertyValue('--color-text-muted').trim() || '#475569';
      const fontHeading = style.getPropertyValue('--font-heading').trim() || 'Outfit';
      const fontBody = style.getPropertyValue('--font-body').trim() || 'Inter';

      const cpuGradient = ctx.createLinearGradient(0, 0, 0, 200);
      cpuGradient.addColorStop(0, hexToRgba(accentColor, 0.3));
      cpuGradient.addColorStop(1, hexToRgba(accentColor, 0.0));

      const ramGradient = ctx.createLinearGradient(0, 0, 0, 200);
      ramGradient.addColorStop(0, hexToRgba(coolColor, 0.3));
      ramGradient.addColorStop(1, hexToRgba(coolColor, 0.0));

      window.hostStatsChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'CPU Usage (%)',
              data: cpuData,
              borderColor: accentColor,
              backgroundColor: cpuGradient,
              borderWidth: 3,
              fill: true,
              tension: 0.4,
              pointRadius: 3,
              pointHoverRadius: 6,
              yAxisID: 'yCPU'
            },
            {
              label: 'RAM Usage (%)',
              data: ramData,
              borderColor: coolColor,
              backgroundColor: ramGradient,
              borderWidth: 3,
              fill: true,
              tension: 0.4,
              pointRadius: 3,
              pointHoverRadius: 6,
              yAxisID: 'yRAM'
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: {
                color: textMainColor,
                font: {
                  family: fontHeading,
                  size: 12,
                  weight: 'bold'
                }
              }
            },
            tooltip: {
              mode: 'index',
              intersect: false,
              titleFont: {
                family: fontHeading,
                size: 13,
                weight: 'bold'
              },
              bodyFont: {
                family: fontBody,
                size: 12
              }
            }
          },
          scales: {
            x: {
              grid: {
                display: false
              },
              ticks: {
                color: textMutedColor,
                font: {
                  family: fontBody,
                  size: 11
                }
              }
            },
            yCPU: {
              type: 'linear',
              display: true,
              position: 'left',
              min: 0,
              max: 100,
              title: {
                display: true,
                text: 'CPU Usage (%)',
                color: textMainColor,
                font: {
                  family: fontHeading,
                  size: 12,
                  weight: 'bold'
                }
              },
              grid: {
                color: '#e2e8f0'
              },
              ticks: {
                color: textMutedColor,
                font: {
                  family: fontBody,
                  size: 11
                }
              }
            },
            yRAM: {
              type: 'linear',
              display: true,
              position: 'right',
              min: 0,
              max: 100,
              title: {
                display: true,
                text: 'RAM Usage (%)',
                color: textMainColor,
                font: {
                  family: fontHeading,
                  size: 12,
                  weight: 'bold'
                }
              },
              grid: {
                drawOnChartArea: false
              },
              ticks: {
                color: textMutedColor,
                font: {
                  family: fontBody,
                  size: 11
                }
              }
            }
          }
        }
      });
    }
  } catch (err) {
    console.error("Error rendering Chart.js Live Monitor:", err);
    showToast(`Chart error: ${err.message}`, 'error');
  }
}

// Load Overview Statistics
async function loadOverview(silent = false) {
  try {
    const response = await fetch('/api/admin/stats');
    const stats = await window.handleFetchResponse(response);
    window.lastHostStats = stats; // Cache stats globally for preview

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

    // Populate actual host stats from the backend API response
    document.getElementById('node-cpu-percent').textContent = `${stats.host_cpu}%`;
    document.getElementById('node-cpu-bar').style.width = `${stats.host_cpu}%`;
    
    document.getElementById('node-ram-usage').textContent = `${stats.host_ram_used} GB / ${stats.host_ram_total} GB`;
    document.getElementById('node-ram-bar').style.width = `${stats.host_ram_percent}%`;

    document.getElementById('node-disk-usage').textContent = `${stats.host_disk_used} GB / ${stats.host_disk_total} GB`;
    document.getElementById('node-disk-bar').style.width = `${stats.host_disk_percent}%`;

    // Render / update the Chart.js line graph
    updateHostStatsChart(stats.history);

    // Trigger host impact calculation
    if (window.updateHostImpactPreview) {
      window.updateHostImpactPreview();
    }

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
  const nodeId = document.getElementById('deployNode').value;
  const os = document.getElementById('deployOS').value;
  const cpu = document.getElementById('deployCPU').value;
  const ram = document.getElementById('deployRAM').value;
  const disk = document.getElementById('deployDisk').value;
  const password = document.getElementById('deployPassword').value;
  const discordUserId = document.getElementById('deployDiscordUser')?.value || '';

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
  const progressPercent = document.getElementById('deploy-progress-percent');

  modal.classList.add('active');
  closeBtnH.style.display = 'none';
  closeBtnB.style.display = 'none';
  progressFill.style.width = '0%';
  progressFill.style.backgroundColor = 'var(--color-cool)';
  progressPercent.textContent = '0%';
  logsArea.innerHTML = '<div style="color: #7de8a3;">[SYSTEM] Initiating server side EventStream connection...</div>';

  // Reset stepper states
  for (let i = 1; i <= 4; i++) {
    window.updateStepper(i, i === 1 ? 'active' : 'pending');
  }

  // Open SSE stream
  const url = `/api/admin/vps/deploy-stream?name=${name}&user_id=${userId}&os=${os}&cpu=${cpu}&ram=${ram}&disk=${disk}&root_password=${encodeURIComponent(password)}&node_id=${nodeId}&discord_user_id=${encodeURIComponent(discordUserId)}`;
  const source = new EventSource(url);
  
  let currentProgress = 5;

  source.onmessage = function(event) {
    const line = event.data;
    const lineDiv = document.createElement('div');
    lineDiv.textContent = line;
    
    // Parse stepper states and progress bar percentage based on SSE log lines
    if (line.includes('[INFO] Validating parameters')) {
      currentProgress = 15;
      window.updateStepper(1, 'active');
    } else if (line.includes('[INFO] Initiating LXC deploy')) {
      currentProgress = 35;
      window.updateStepper(1, 'completed');
      window.updateStepper(2, 'active');
    } else if (line.includes('[INFO] Container image downloaded')) {
      currentProgress = 60;
      window.updateStepper(2, 'completed');
      window.updateStepper(3, 'active');
    } else if (line.includes('[INFO] Initiating background installation')) {
      currentProgress = 85;
      window.updateStepper(3, 'completed');
      window.updateStepper(4, 'active');
    }
    
    progressFill.style.width = `${currentProgress}%`;
    progressPercent.textContent = `${currentProgress}%`;

    // Add colored line styling based on keywords
    if (line.includes('[SUCCESS]')) {
      lineDiv.style.color = '#7de8a3';
      lineDiv.style.fontWeight = 'bold';
      
      currentProgress = 100;
      progressFill.style.width = '100%';
      progressPercent.textContent = '100%';
      progressFill.style.backgroundColor = 'var(--color-accent)';
      window.updateStepper(4, 'completed');
      
      // Enable close
      closeBtnH.style.display = 'block';
      closeBtnB.style.display = 'block';
      showToast("VPS Instance deployed successfully!", "success");
      
      // Reset form
      document.getElementById('deployVPSForm').reset();
      window.updateDeployCPUVal(2);
      window.updateDeployRAMVal(2048);
      window.updateDeployDiskVal(20);
      
      // Reset OS selection to default card
      const defaultCard = document.querySelector('.os-card[data-os="ubuntu/22.04"]');
      if (defaultCard) {
        window.selectOSCard(defaultCard);
      }
      
      source.close();
    } else if (line.includes('[ERROR]')) {
      lineDiv.style.color = '#ea7373';
      lineDiv.style.fontWeight = 'bold';
      progressFill.style.backgroundColor = 'var(--color-danger)';
      
      // Mark active stepper item as failed
      const activeStep = document.querySelector('.step-item.active');
      if (activeStep) {
        activeStep.className = 'step-item pending';
        const badge = activeStep.querySelector('.step-icon-badge');
        if (badge) {
          badge.innerHTML = '✗';
          badge.style.backgroundColor = 'var(--color-danger)';
          badge.style.color = '#fff';
        }
      }

      // Enable close
      closeBtnH.style.display = 'block';
      closeBtnB.style.display = 'block';
      showToast("Deployment failed. See logs.", "error");
      source.close();
    } else if (line.includes('[INFO]')) {
      lineDiv.style.color = '#d6e87d';
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

// --- OS SELECTOR, PASSWORD HELPERS & RESOURCE PREVIEW UTILITIES ---

// OS card selection
window.selectOSCard = function(el) {
  const cards = document.querySelectorAll('.os-card');
  cards.forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('deployOS').value = el.getAttribute('data-os');
};

// Toggle password input type (visibility)
window.toggleDeployPassword = function() {
  const input = document.getElementById('deployPassword');
  const icon = document.getElementById('password-toggle-icon');
  if (input.type === 'password') {
    input.type = 'text';
    icon.setAttribute('data-lucide', 'eye-off');
  } else {
    input.type = 'password';
    icon.setAttribute('data-lucide', 'eye');
  }
  lucide.createIcons();
};

// Copy password to clipboard
window.copyGeneratedPassword = function() {
  const password = document.getElementById('deployPassword').value;
  if (!password) {
    showToast("No password to copy!", "error");
    return;
  }
  navigator.clipboard.writeText(password).then(() => {
    showToast("Password copied to clipboard!", "success");
  }).catch(() => {
    showToast("Failed to copy password", "error");
  });
};

// Generate random strong password
window.triggerPasswordGeneration = function() {
  const length = 12;
  const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*";
  let password = "";
  password += "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)];
  password += "abcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 26)];
  password += "0123456789"[Math.floor(Math.random() * 10)];
  password += "!@#$%^&*"[Math.floor(Math.random() * 8)];
  for (let i = 4; i < length; i++) {
    password += charset[Math.floor(Math.random() * charset.length)];
  }
  // Shuffle
  password = password.split('').sort(() => 0.5 - Math.random()).join('');
  
  const input = document.getElementById('deployPassword');
  input.value = password;
  input.type = 'text'; // Reveal
  const icon = document.getElementById('password-toggle-icon');
  icon.setAttribute('data-lucide', 'eye-off');
  lucide.createIcons();
  showToast("Secure password generated!", "success");
};

// Update stepper step UI
window.updateStepper = function(stepNumber, status) {
  const stepItem = document.getElementById(`step-${stepNumber}`);
  if (!stepItem) return;
  
  stepItem.className = `step-item ${status}`;
  const badge = stepItem.querySelector('.step-icon-badge');
  if (!badge) return;

  if (status === 'completed') {
    badge.innerHTML = '✓';
  } else if (status === 'active') {
    badge.innerHTML = `<span style="display:inline-block; animation: spin 1.5s linear infinite;">↻</span>`;
  } else {
    badge.innerHTML = stepNumber;
  }
};

// Update dynamic projected resource bars
window.updateHostImpactPreview = function() {
  if (!window.lastHostStats) return;
  const stats = window.lastHostStats;

  const allocCPU = parseInt(document.getElementById('deployCPU').value) || 2;
  const allocRAM = parseInt(document.getElementById('deployRAM').value) || 2048;
  const allocDisk = parseInt(document.getElementById('deployDisk').value) || 20;

  const currentCPU = stats.host_cpu || 0;
  const projectedCPU = Math.min(100, Math.round(currentCPU + (allocCPU * 3))); // Estimation model
  
  const hostRAMTotal = stats.host_ram_total || 16.0;
  const currentRAMUsed = stats.host_ram_used || 0;
  const allocRAMGb = allocRAM / 1024;
  const projectedRAMUsed = Math.min(hostRAMTotal, currentRAMUsed + allocRAMGb);
  const projectedRAMPercent = Math.round((projectedRAMUsed / hostRAMTotal) * 100);

  const hostDiskTotal = stats.host_disk_total || 120.0;
  const currentDiskUsed = stats.host_disk_used || 0;
  const projectedDiskUsed = Math.min(hostDiskTotal, currentDiskUsed + allocDisk);
  const projectedDiskPercent = Math.round((projectedDiskUsed / hostDiskTotal) * 100);

  document.getElementById('preview-cpu-text').textContent = `${projectedCPU}%`;
  document.getElementById('preview-cpu-bar').style.width = `${projectedCPU}%`;
  document.getElementById('preview-cpu-delta').textContent = `Current: ${currentCPU}% | Allocation: +${allocCPU} cores`;

  document.getElementById('preview-ram-text').textContent = `${projectedRAMUsed.toFixed(1)} GB / ${hostRAMTotal.toFixed(1)} GB`;
  document.getElementById('preview-ram-bar').style.width = `${projectedRAMPercent}%`;
  document.getElementById('preview-ram-delta').textContent = `Current: ${currentRAMUsed.toFixed(1)} GB | Allocation: +${(allocRAM/1024).toFixed(1)} GB`;

  document.getElementById('preview-disk-text').textContent = `${projectedDiskUsed.toFixed(1)} GB / ${hostDiskTotal.toFixed(1)} GB`;
  document.getElementById('preview-disk-bar').style.width = `${projectedDiskPercent}%`;
  document.getElementById('preview-disk-delta').textContent = `Current: ${currentDiskUsed.toFixed(1)} GB | Allocation: +${allocDisk} GB`;

  const warningBadge = document.getElementById('allocation-warning-badge');
  if (projectedRAMPercent > 95 || projectedDiskPercent > 95) {
    warningBadge.style.display = 'block';
    document.getElementById('preview-ram-bar').style.backgroundColor = 'var(--color-danger)';
    document.getElementById('preview-disk-bar').style.backgroundColor = 'var(--color-danger)';
  } else {
    warningBadge.style.display = 'none';
    document.getElementById('preview-ram-bar').style.backgroundColor = 'var(--color-accent)';
    document.getElementById('preview-disk-bar').style.backgroundColor = 'var(--color-accent)';
  }
};

// --- CUSTOMIZATION & BRANDING ACTIONS ---

// Save site name and color settings
async function saveBranding(event) {
  event.preventDefault();
  const siteName = document.getElementById('brandSiteName').value.trim();
  const colorPrimary = document.getElementById('brandColorPrimaryText').value.trim();
  const colorSecondary = document.getElementById('brandColorSecondaryText').value.trim();
  const colorAccent = document.getElementById('brandColorAccentText').value.trim();
  const colorCool = document.getElementById('brandColorCoolText').value.trim();
  const authImageUrl = document.getElementById('brandAuthImageUrl').value.trim();

  try {
    const response = await fetch('/api/admin/settings/branding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        site_name: siteName,
        color_primary: colorPrimary,
        color_secondary: colorSecondary,
        color_accent: colorAccent,
        color_cool: colorCool,
        auth_image_url: authImageUrl
      })
    });
    const result = await window.handleFetchResponse(response);
    showToast(result.message || "Branding settings saved successfully.", "success");
    // Reload page to apply new theme colors and branding name
    setTimeout(() => location.reload(), 1000);
  } catch (err) {
    showToast(`Failed to save branding: ${err.message}`, "error");
  }
}
window.saveBranding = saveBranding;

// Save public page details
async function savePagesContent(event) {
  event.preventDefault();
  const aboutIntro = document.getElementById('pageAboutIntro').value.trim();
  const aboutMission = document.getElementById('pageAboutMission').value.trim();
  const aboutInfra = document.getElementById('pageAboutInfra').value.trim();
  const aboutWhyTrust = document.getElementById('pageAboutWhyTrust').value.trim();
  const tosContent = document.getElementById('pageTosContent').value.trim();

  try {
    const response = await fetch('/api/admin/settings/pages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        about_intro: aboutIntro,
        about_mission: aboutMission,
        about_infra: aboutInfra,
        about_why_trust: aboutWhyTrust,
        tos_content: tosContent
      })
    });
    const result = await window.handleFetchResponse(response);
    showToast(result.message || "Page contents saved successfully.", "success");
  } catch (err) {
    showToast(`Failed to save page contents: ${err.message}`, "error");
  }
}
window.savePagesContent = savePagesContent;



// --- VPS PLANS CRUD ---
window.loadedPlans = [];

async function loadCustomPlans() {
  try {
    const res = await fetch('/api/admin/plans');
    const plans = await window.handleFetchResponse(res);
    window.loadedPlans = plans;
    
    const tbody = document.getElementById('custom-plans-table-body');
    tbody.innerHTML = '';
    
    if (plans.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center" style="color: var(--color-text-muted); padding: 20px;">No plans found.</td></tr>';
      return;
    }
    
    plans.forEach(plan => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><code style="background-color: var(--color-primary); padding: 2px 6px; border-radius: var(--radius-sm); font-size: 12px; font-family: monospace;">#${plan.id}</code></td>
        <td><strong>${plan.name}</strong></td>
        <td>$${parseFloat(plan.price).toFixed(2)}</td>
        <td>${plan.cpu}</td>
        <td>${plan.ram}</td>
        <td>${plan.storage}</td>
        <td>${plan.bandwidth}</td>
        <td><span style="font-size: 11px; color: var(--color-text-muted);">${plan.price_credits} Credits</span></td>
        <td class="text-right" style="white-space: nowrap;">
          <button class="btn btn-outline action-btn-small" onclick="openPlanModal(${plan.id})" style="margin-right: 6px;">
            <i data-lucide="edit" style="width: 13px; height: 13px; margin-right: 2px;"></i> Edit
          </button>
          <button class="btn btn-outline action-btn-small" onclick="deletePlan(${plan.id})" style="background-color: #fdf2f2; border-color: #f6d1d1; color: #b91c1c;">
            <i data-lucide="trash" style="width: 13px; height: 13px; margin-right: 2px;"></i> Delete
          </button>
        </td>
      `;
      tbody.appendChild(row);
    });
    
    if (typeof lucide !== 'undefined') {
      lucide.createIcons();
    }
  } catch (err) {
    showToast(`Failed to load plans: ${err.message}`, 'error');
  }
}
window.loadCustomPlans = loadCustomPlans;

window.openPlanModal = function(planId = null) {
  const modal = document.getElementById('planModal');
  const title = document.getElementById('planModalTitle');
  const form = document.getElementById('planForm');
  
  form.reset();
  document.getElementById('planFormId').value = '';
  
  if (planId) {
    title.textContent = "Edit VPS Plan";
    const plan = window.loadedPlans.find(p => p.id === planId);
    if (plan) {
      document.getElementById('planFormId').value = plan.id;
      document.getElementById('planName').value = plan.name;
      document.getElementById('planPrice').value = plan.price;
      document.getElementById('planPriceCredits').value = plan.price_credits;
      document.getElementById('planCpu').value = plan.cpu;
      document.getElementById('planRam').value = plan.ram;
      document.getElementById('planDisk').value = plan.storage;
      document.getElementById('planBandwidth').value = plan.bandwidth;
    }
  } else {
    title.textContent = "Add VPS Plan";
  }
  
  modal.classList.add('active');
};

window.closePlanModal = function() {
  document.getElementById('planModal').classList.remove('active');
};

window.handlePlanSubmit = async function(event) {
  event.preventDefault();
  const planId = document.getElementById('planFormId').value;
  const name = document.getElementById('planName').value.trim();
  const price = parseFloat(document.getElementById('planPrice').value);
  const priceCredits = parseInt(document.getElementById('planPriceCredits').value);
  const cpu = document.getElementById('planCpu').value.trim();
  const ram = document.getElementById('planRam').value.trim();
  const disk = document.getElementById('planDisk').value.trim();
  const bandwidth = document.getElementById('planBandwidth').value.trim();

  const payload = {
    name,
    price,
    price_credits: priceCredits,
    cpu,
    ram,
    storage: disk,
    bandwidth
  };

  const isEdit = !!planId;
  const url = isEdit ? `/api/admin/plans/${planId}` : '/api/admin/plans';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    closePlanModal();
    loadCustomPlans();
  } catch (err) {
    showToast(`Failed to save plan: ${err.message}`, 'error');
  }
};

window.deletePlan = async function(planId) {
  if (!confirm("Are you sure you want to delete this pricing plan?")) return;
  try {
    const res = await fetch(`/api/admin/plans/${planId}`, {
      method: 'DELETE'
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    loadCustomPlans();
  } catch (err) {
    showToast(`Failed to delete plan: ${err.message}`, 'error');
  }
};

// --- FAQ CRUD ---
window.loadedFaqs = [];

async function loadCustomFaqs() {
  try {
    const res = await fetch('/api/admin/faqs');
    const faqs = await window.handleFetchResponse(res);
    window.loadedFaqs = faqs;
    
    const tbody = document.getElementById('custom-faqs-table-body');
    tbody.innerHTML = '';
    
    if (faqs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center" style="color: var(--color-text-muted); padding: 20px;">No FAQs found.</td></tr>';
      return;
    }
    
    faqs.forEach(faq => {
      const row = document.createElement('tr');
      const answerPreview = faq.answer.length > 80 ? faq.answer.substring(0, 80) + '...' : faq.answer;
      
      row.innerHTML = `
        <td><code style="background-color: var(--color-primary); padding: 2px 6px; border-radius: var(--radius-sm); font-size: 12px; font-family: monospace;">#${faq.id}</code></td>
        <td><strong>${faq.question}</strong></td>
        <td style="font-size: 13px; color: var(--color-text-muted); max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${answerPreview}</td>
        <td class="text-right" style="white-space: nowrap;">
          <button class="btn btn-outline action-btn-small" onclick="openFaqModal(${faq.id})" style="margin-right: 6px;">
            <i data-lucide="edit" style="width: 13px; height: 13px; margin-right: 2px;"></i> Edit
          </button>
          <button class="btn btn-outline action-btn-small" onclick="deleteFaq(${faq.id})" style="background-color: #fdf2f2; border-color: #f6d1d1; color: #b91c1c;">
            <i data-lucide="trash" style="width: 13px; height: 13px; margin-right: 2px;"></i> Delete
          </button>
        </td>
      `;
      tbody.appendChild(row);
    });
    
    if (typeof lucide !== 'undefined') {
      lucide.createIcons();
    }
  } catch (err) {
    showToast(`Failed to load FAQs: ${err.message}`, 'error');
  }
}
window.loadCustomFaqs = loadCustomFaqs;

window.openFaqModal = function(faqId = null) {
  const modal = document.getElementById('faqModal');
  const title = document.getElementById('faqModalTitle');
  const form = document.getElementById('faqForm');
  
  form.reset();
  document.getElementById('faqFormId').value = '';
  
  if (faqId) {
    title.textContent = "Edit FAQ Item";
    const faq = window.loadedFaqs.find(f => f.id === faqId);
    if (faq) {
      document.getElementById('faqFormId').value = faq.id;
      document.getElementById('faqQuestion').value = faq.question;
      document.getElementById('faqAnswer').value = faq.answer;
    }
  } else {
    title.textContent = "Add FAQ Item";
  }
  
  modal.classList.add('active');
};

window.closeFaqModal = function() {
  document.getElementById('faqModal').classList.remove('active');
};

window.handleFaqSubmit = async function(event) {
  event.preventDefault();
  const faqId = document.getElementById('faqFormId').value;
  const question = document.getElementById('faqQuestion').value.trim();
  const answer = document.getElementById('faqAnswer').value.trim();

  const payload = {
    question,
    answer
  };

  const isEdit = !!faqId;
  const url = isEdit ? `/api/admin/faqs/${faqId}` : '/api/admin/faqs';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    closeFaqModal();
    loadCustomFaqs();
  } catch (err) {
    showToast(`Failed to save FAQ: ${err.message}`, 'error');
  }
};

window.deleteFaq = async function(faqId) {
  if (!confirm("Are you sure you want to delete this FAQ item?")) return;
  try {
    const res = await fetch(`/api/admin/faqs/${faqId}`, {
      method: 'DELETE'
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    loadCustomFaqs();
  } catch (err) {
    showToast(`Failed to delete FAQ: ${err.message}`, 'error');
  }
};

window.handleBrandingUpload = async function(input, type) {
  if (!input.files || !input.files[0]) return;
  
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  formData.append('type', type);
  
  showToast(`Uploading ${type}...`, 'info');
  
  try {
    const res = await fetch('/api/admin/settings/upload', {
      method: 'POST',
      body: formData
    });
    
    const result = await window.handleFetchResponse(res);
    showToast(result.message || `${type.toUpperCase()} uploaded successfully.`, 'success');
    
    // Update the previews dynamically without full reload
    if (type === 'logo') {
      const container = document.querySelector('.logo-preview-container');
      container.innerHTML = `<img id="adminLogoPreview" src="${result.url}" alt="Logo Preview" style="max-height: 80px; max-width: 90%; object-fit: contain;">`;
      
      const removeBtn = document.getElementById('btn-remove-logo');
      if (removeBtn) removeBtn.style.display = 'inline-flex';
      
      // Update sidebar logo if it's there
      const sidebarLogo = document.querySelector('.db-sidebar .logo');
      if (sidebarLogo) {
        let logoImg = sidebarLogo.querySelector('.logo-img');
        if (!logoImg) {
          const fallback = sidebarLogo.querySelector('.logo-icon');
          if (fallback) fallback.remove();
          logoImg = document.createElement('img');
          logoImg.className = 'logo-img';
          logoImg.alt = 'Logo';
          sidebarLogo.prepend(logoImg);
        }
        logoImg.src = result.url;
      }
    } else if (type === 'favicon') {
      const container = document.querySelector('.favicon-preview-container');
      container.innerHTML = `<img id="adminFaviconPreview" src="${result.url}" alt="Favicon Preview" style="width: 48px; height: 48px; object-fit: contain;">`;
      
      const removeBtn = document.getElementById('btn-remove-favicon');
      if (removeBtn) removeBtn.style.display = 'inline-flex';
      
      // Update favicon in head
      let fav = document.querySelector('link[rel*="icon"]');
      if (!fav) {
        fav = document.createElement('link');
        fav.rel = 'shortcut icon';
        fav.type = 'image/x-icon';
        document.head.appendChild(fav);
      }
      fav.href = result.url;
    }
    
    // Create new Lucide icons if any
    if (typeof lucide !== 'undefined') {
      lucide.createIcons();
    }
  } catch (err) {
    showToast(`Failed to upload ${type}: ${err.message}`, 'error');
  } finally {
    // Reset file input value so same file can be uploaded again
    input.value = '';
  }
};

window.removeBrandingImage = async function(type) {
  if (!confirm(`Are you sure you want to remove the custom ${type} and revert to default?`)) return;
  
  showToast(`Removing custom ${type}...`, 'info');
  
  try {
    const res = await fetch('/api/admin/settings/remove-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type })
    });
    
    const result = await window.handleFetchResponse(res);
    showToast(result.message || `${type.toUpperCase()} removed successfully.`, 'success');
    
    if (type === 'logo') {
      const container = document.querySelector('.logo-preview-container');
      const siteName = document.getElementById('brandSiteName')?.value || 'MintyHost';
      const firstLetter = siteName.charAt(0).toUpperCase();
      container.innerHTML = `<div id="adminLogoFallback" class="logo-icon" style="font-size: 32px; width: 60px; height: 60px; display: flex; align-items: center; justify-content: center; box-shadow: none; border-radius: var(--radius-sm);">${firstLetter}</div>`;
      
      const removeBtn = document.getElementById('btn-remove-logo');
      if (removeBtn) removeBtn.style.display = 'none';
      
      // Revert sidebar logo
      const sidebarLogo = document.querySelector('.db-sidebar .logo');
      if (sidebarLogo) {
        const logoImg = sidebarLogo.querySelector('.logo-img');
        if (logoImg) logoImg.remove();
        const fallback = document.createElement('div');
        fallback.className = 'logo-icon';
        fallback.textContent = firstLetter;
        sidebarLogo.prepend(fallback);
      }
    } else if (type === 'favicon') {
      const container = document.querySelector('.favicon-preview-container');
      container.innerHTML = `<div id="adminFaviconFallback" style="font-size: 32px; font-weight: bold; color: var(--color-text-muted);">FI</div>`;
      
      const removeBtn = document.getElementById('btn-remove-favicon');
      if (removeBtn) removeBtn.style.display = 'none';
      
      // Remove favicon in head
      const fav = document.querySelector('link[rel*="icon"]');
      if (fav) fav.remove();
    }
    
    if (typeof lucide !== 'undefined') {
      lucide.createIcons();
    }
  } catch (err) {
    showToast(`Failed to remove ${type}: ${err.message}`, 'error');
  }
};

// --- USER MANAGEMENT FUNCTIONS ---
window.loadedAdminUsersList = [];

async function loadAdminUsers() {
  try {
    const res = await fetch('/api/admin/users/all');
    const users = await window.handleFetchResponse(res);
    window.loadedAdminUsersList = users;
    
    const tbody = document.getElementById('users-table-body');
    tbody.innerHTML = '';
    
    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center" style="color: var(--color-text-muted); padding: 20px;">No users found.</td></tr>';
      return;
    }
    
    users.forEach(user => {
      const row = document.createElement('tr');
      const resourcesText = `${user.total_cpu} Cores / ${user.total_ram} MB / ${user.total_disk} GB`;
      const hashPreview = user.password_hash ? user.password_hash.substring(0, 15) + '...' : 'N/A';
      
      row.innerHTML = `
        <td><code style="background-color: var(--color-primary); padding: 2px 6px; border-radius: var(--radius-sm); font-size: 12px; font-family: monospace;">UID-${user.id}</code></td>
        <td><strong>${user.username}</strong></td>
        <td>${user.email}</td>
        <td><span class="badge ${user.role === 'admin' ? 'badge-resolved' : 'badge-open'}">${user.role.toUpperCase()}</span></td>
        <td style="font-family: monospace; font-size: 11px; color: var(--color-text-muted);" title="${user.password_hash}">${hashPreview}</td>
        <td><strong>${user.vps_count}</strong> instances</td>
        <td style="font-size: 13px;">${resourcesText}</td>
        <td class="text-right" style="white-space: nowrap;">
          <button class="btn btn-outline action-btn-small" onclick="openUserDetailsModal(${user.id})" style="margin-right: 6px;" title="View User Details">
            <i data-lucide="eye" style="width: 13px; height: 13px;"></i> Details
          </button>
          <button class="btn btn-outline action-btn-small" onclick="openUserEditModal(${user.id})" style="margin-right: 6px;" title="Edit Account">
            <i data-lucide="edit" style="width: 13px; height: 13px;"></i> Edit
          </button>
          <button class="btn btn-outline action-btn-small" onclick="suspendUserVPS(${user.id})" style="margin-right: 6px; background-color: #fff9f0; border-color: #f59e0b; color: #78350f;" title="Suspend All instances">
            <i data-lucide="shield-alert" style="width: 13px; height: 13px;"></i> Suspend All
          </button>
          <button class="btn btn-outline action-btn-small" onclick="deleteUser(${user.id}, '${user.username}')" style="background-color: #fdf2f2; border-color: #f6d1d1; color: #b91c1c;" title="Delete User">
            <i data-lucide="trash-2" style="width: 13px; height: 13px;"></i> Delete
          </button>
        </td>
      `;
      tbody.appendChild(row);
    });
    
    if (typeof lucide !== 'undefined') {
      lucide.createIcons();
    }
  } catch (err) {
    showToast(`Failed to load users: ${err.message}`, 'error');
  }
}
window.loadAdminUsers = loadAdminUsers;

// Modal Controls
window.openUserCreateModal = function() {
  document.getElementById('userCreateForm').reset();
  loadDiscordUsers();
  document.getElementById('userCreateModal').classList.add('active');
};
window.closeUserCreateModal = function() {
  document.getElementById('userCreateModal').classList.remove('active');
};

window.handleUserCreateSubmit = async function(event) {
  event.preventDefault();
  const username = document.getElementById('createUsername').value.trim();
  const email = document.getElementById('createEmail').value.trim();
  const role = document.getElementById('createRole').value;
  const password = document.getElementById('createPassword').value;
  const discordUserId = document.getElementById('createDiscordUser')?.value || '';

  try {
    const res = await fetch('/api/admin/users/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, role, password, discord_user_id: discordUserId })
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    closeUserCreateModal();
    loadAdminUsers();
  } catch (err) {
    showToast(`Failed to create user: ${err.message}`, 'error');
  }
};

window.openUserEditModal = function(userId) {
  const user = window.loadedAdminUsersList.find(u => u.id === userId);
  if (!user) return;

  document.getElementById('editUserId').value = user.id;
  document.getElementById('editUsername').value = user.username;
  document.getElementById('editEmail').value = user.email;
  document.getElementById('editRole').value = user.role;
  document.getElementById('editPassword').value = '';

  document.getElementById('userEditModal').classList.add('active');
};
window.closeUserEditModal = function() {
  document.getElementById('userEditModal').classList.remove('active');
};

window.handleUserEditSubmit = async function(event) {
  event.preventDefault();
  const userId = document.getElementById('editUserId').value;
  const username = document.getElementById('editUsername').value.trim();
  const email = document.getElementById('editEmail').value.trim();
  const role = document.getElementById('editRole').value;
  const password = document.getElementById('editPassword').value;

  const payload = { username, email, role };
  if (password && password.trim() !== '') {
    payload.password = password.trim();
  }

  try {
    const res = await fetch(`/api/admin/users/${userId}/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    closeUserEditModal();
    loadAdminUsers();
  } catch (err) {
    showToast(`Failed to update user: ${err.message}`, 'error');
  }
};

window.openUserDetailsModal = async function(userId) {
  const user = window.loadedAdminUsersList.find(u => u.id === userId);
  if (!user) return;

  // Set Profile PFP or Initials
  const pfpContainer = document.getElementById('detailsPfpContainer');
  if (user.pfp) {
    pfpContainer.innerHTML = `<img src="${user.pfp}" alt="PFP" style="width: 100%; height: 100%; object-fit: cover;">`;
    pfpContainer.style.padding = '0';
  } else {
    pfpContainer.innerHTML = `<span>${user.username.substring(0, 2).toUpperCase()}</span>`;
    pfpContainer.style.padding = '';
  }

  document.getElementById('detailsUsername').textContent = user.username;
  document.getElementById('detailsEmail').textContent = user.email;
  
  const roleBadge = document.getElementById('detailsRoleBadge');
  roleBadge.textContent = user.role.toUpperCase();
  roleBadge.className = `badge ${user.role === 'admin' ? 'badge-resolved' : 'badge-open'}`;

  // Resource statistics
  document.getElementById('detailsTotalCpu').textContent = `${user.total_cpu} Core${user.total_cpu > 1 ? 's' : ''}`;
  document.getElementById('detailsTotalRam').textContent = `${user.total_ram} MB`;
  document.getElementById('detailsTotalDisk').textContent = `${user.total_disk} GB`;

  // Fetch and display VPS sub-list
  const tbody = document.getElementById('details-vps-body');
  tbody.innerHTML = '<tr><td colspan="4" class="text-center">Loading owned servers...</td></tr>';

  document.getElementById('userDetailsModal').classList.add('active');

  try {
    const res = await fetch(`/api/admin/users/${userId}/vps`);
    const vpsList = await window.handleFetchResponse(res);
    tbody.innerHTML = '';

    if (vpsList.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center" style="color: var(--color-text-muted);">This user does not own any VPS.</td></tr>';
      return;
    }

    vpsList.forEach(vps => {
      const row = document.createElement('tr');
      const statusClass = vps.status === 'running' ? 'running' : (vps.status === 'suspended' ? 'suspended' : 'stopped');
      
      row.innerHTML = `
        <td><strong>${vps.container_name}</strong></td>
        <td>${vps.os}</td>
        <td style="font-size: 13px;">${vps.cpu} Cores / ${vps.ram} MB / ${vps.disk} GB</td>
        <td>
          <span class="vps-status-badge ${statusClass}" style="padding: 2px 8px; font-size: 10px;">
            <span class="status-dot"></span>
            <span>${vps.status}</span>
          </span>
        </td>
      `;
      tbody.appendChild(row);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-center" style="color: var(--color-danger);">Failed to load VPS: ${err.message}</td></tr>`;
  }
};

window.closeUserDetailsModal = function() {
  document.getElementById('userDetailsModal').classList.remove('active');
};

window.suspendUserVPS = async function(userId) {
  if (!confirm("Are you sure you want to suspend ALL virtual servers owned by this user?")) return;
  showToast('Suspending all instances...', 'info');
  try {
    const res = await fetch(`/api/admin/users/${userId}/suspend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suspend: true })
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    loadAdminUsers();
  } catch (err) {
    showToast(`Failed to suspend instances: ${err.message}`, 'error');
  }
};

window.deleteUser = async function(userId, username) {
  if (!confirm(`WARNING: Deleting user '${username}' will permanently delete their account AND immediately destroy all LXC containers they own on this node!\n\nThis action is completely irreversible. Are you sure you want to delete this user?`)) {
    return;
  }
  showToast(`Deleting user '${username}' and associated VPSes...`, 'info');
  try {
    const res = await fetch(`/api/admin/users/${userId}/delete`, {
      method: 'DELETE'
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    loadAdminUsers();
  } catch (err) {
    showToast(`Failed to delete user: ${err.message}`, 'error');
  }
};

// Nodes Management Actions
async function loadNodesDropdown() {
  try {
    const response = await fetch('/api/admin/nodes');
    const nodes = await window.handleFetchResponse(response);
    
    const select = document.getElementById('deployNode');
    if (!select) return;
    select.innerHTML = '';
    
    nodes.forEach(node => {
      const option = document.createElement('option');
      option.value = node.id;
      option.textContent = `${node.name} (${node.fqdn}:${node.port} - ${node.location})`;
      if (node.id === 1) option.selected = true;
      select.appendChild(option);
    });
  } catch (err) {
    showToast(`Failed to load nodes: ${err.message}`, 'error');
  }
}

async function loadAdminNodes() {
  try {
    const response = await fetch('/api/admin/nodes');
    const nodes = await window.handleFetchResponse(response);
    
    const tbody = document.getElementById('nodes-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    if (nodes.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center">No nodes configured.</td></tr>';
      return;
    }
    
    nodes.forEach(node => {
      const row = document.createElement('tr');
      row.setAttribute('data-node-id', node.id);
      
      const statusClass = node.status === 'online' ? 'running' : 'stopped';
      const statusLabel = node.status === 'online' ? 'ONLINE' : (node.status === 'connecting' ? 'CONNECTING' : 'OFFLINE');
      
      let actionButtons = `
        <button class="btn btn-outline btn-small" onclick="showNodeConfig(${node.id})"><i data-lucide="settings" style="width:12px; height:12px;"></i> Configure</button>
      `;
      if (node.id !== 1) {
        actionButtons += `
          <button class="btn btn-outline btn-small" style="border-color: var(--color-danger); color: var(--color-danger);" onclick="deleteNode(${node.id}, '${node.name}')"><i data-lucide="trash-2" style="width:12px; height:12px;"></i> Delete</button>
        `;
      }
      
      row.innerHTML = `
        <td><strong>#ND-${node.id}</strong></td>
        <td>${node.name}</td>
        <td><span style="font-family: monospace; font-size:12px;">${node.fqdn}:${node.port}</span></td>
        <td>${node.location || 'Unknown'}</td>
        <td>
          <span class="vps-status-badge ${statusClass}" id="node-badge-${node.id}" style="display: inline-flex; align-items: center; gap: 6px;">
            <span class="status-dot ${node.status !== 'running' && node.status !== 'online' ? 'stopped' : ''}"></span>
            <span id="node-status-text-${node.id}">${statusLabel}</span>
          </span>
        </td>
        <td class="text-right">${actionButtons}</td>
      `;
      tbody.appendChild(row);
      
      // Asynchronously fetch live status for remote nodes
      if (node.id !== 1) {
        fetchNodeLiveStatus(node.id);
      }
    });
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    showToast(`Failed to load nodes: ${err.message}`, 'error');
  }
}

async function fetchNodeLiveStatus(nodeId) {
  const badge = document.getElementById(`node-badge-${nodeId}`);
  const text = document.getElementById(`node-status-text-${nodeId}`);
  if (!badge || !text) return;
  
  text.textContent = 'CONNECTING';
  badge.className = 'vps-status-badge suspended';
  
  try {
    const res = await fetch(`/api/admin/nodes/${nodeId}/status`);
    const data = await window.handleFetchResponse(res);
    if (data.status === 'online') {
      badge.className = 'vps-status-badge running';
      text.textContent = 'ONLINE';
      const dot = badge.querySelector('.status-dot');
      if (dot) dot.className = 'status-dot';
    } else {
      badge.className = 'vps-status-badge stopped';
      text.textContent = 'OFFLINE';
      const dot = badge.querySelector('.status-dot');
      if (dot) dot.className = 'status-dot stopped';
    }
  } catch (err) {
    badge.className = 'vps-status-badge stopped';
    text.textContent = 'OFFLINE';
    const dot = badge.querySelector('.status-dot');
    if (dot) dot.className = 'status-dot stopped';
  }
}

window.openNodeCreateModal = function() {
  document.getElementById('nodeCreateForm').reset();
  document.getElementById('nodeCreateModal').classList.add('active');
};

window.closeNodeCreateModal = function() {
  document.getElementById('nodeCreateModal').classList.remove('active');
};

window.handleNodeCreateSubmit = async function(event) {
  event.preventDefault();
  const name = document.getElementById('nodeName').value.trim();
  const location = document.getElementById('nodeLocation').value.trim();
  const fqdn = document.getElementById('nodeFqdn').value.trim();
  const port = document.getElementById('nodePort').value;
  
  try {
    const res = await fetch('/api/admin/nodes/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, location, fqdn, port })
    });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    closeNodeCreateModal();
    loadAdminNodes();
    
    // Automatically open configuration helper for the newly created node
    if (result.node_id) {
      setTimeout(() => {
        showNodeConfig(result.node_id);
      }, 500);
    }
  } catch (err) {
    showToast(`Failed to register node: ${err.message}`, 'error');
  }
};

window.showNodeConfig = async function(nodeId) {
  try {
    const res = await fetch(`/api/admin/nodes/${nodeId}/config`);
    const data = await window.handleFetchResponse(res);
    
    document.getElementById('nodeConfigYaml').value = data.config_yaml;
    document.getElementById('nodeInstallCmd').value = data.install_cmd;
    document.getElementById('nodeConfigModal').classList.add('active');
  } catch (err) {
    showToast(`Failed to load configuration details: ${err.message}`, 'error');
  }
};

window.closeNodeConfigModal = function() {
  document.getElementById('nodeConfigModal').classList.remove('active');
};

window.deleteNode = async function(nodeId, nodeName) {
  if (!confirm(`Are you sure you want to permanently delete remote node '${nodeName}'?\n\nThis will remove the node from panel registration. Deletion will be rejected if there are active client VPS instances currently deployed on it.`)) {
    return;
  }
  
  try {
    const res = await fetch(`/api/admin/nodes/${nodeId}`, { method: 'DELETE' });
    const result = await window.handleFetchResponse(res);
    showToast(result.message, 'success');
    loadAdminNodes();
  } catch (err) {
    showToast(`Failed to delete node: ${err.message}`, 'error');
  }
};

window.copyConfigField = function(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.select();
  document.execCommand('copy');
  showToast("Command copied to clipboard!", "success");
};

// ───────────── ADMIN API KEYS MANAGEMENT ─────────────

let adminApiKeysList = []; // Local cache for filtering

window.loadAdminApiKeys = async function() {
  const tbody = document.getElementById('admin-apikeys-table-body');
  if (!tbody) return;

  try {
    const res = await fetch('/api/admin/keys');
    if (!res.ok) throw new Error("Failed to load active keys.");
    const keys = await res.json();
    adminApiKeysList = keys;

    // Render Stats
    const totalKeys = keys.length;
    const adminKeys = keys.filter(k => k.role === 'admin').length;
    const clientKeys = keys.filter(k => k.role !== 'admin').length;

    document.getElementById('adminTotalKeysCount').textContent = totalKeys;
    document.getElementById('adminActiveAdminKeysCount').textContent = adminKeys;
    document.getElementById('adminActiveClientKeysCount').textContent = clientKeys;

    renderAdminKeysTable(keys);
  } catch (err) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 24px; color: var(--color-danger); font-size: 13px;">
          Error: ${err.message}
        </td>
      </tr>
    `;
  }
};

function renderAdminKeysTable(keys) {
  const tbody = document.getElementById('admin-apikeys-table-body');
  if (!tbody) return;

  if (keys.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 32px; color: var(--color-text-muted); font-size: 13px;">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <i data-lucide="key-round" style="width: 28px; height: 28px; stroke-width: 1.5;"></i>
            <span>No registered API keys found in the system.</span>
          </div>
        </td>
      </tr>
    `;
    lucide.createIcons();
    return;
  }

  tbody.innerHTML = keys.map(k => {
    const created = new Date(k.created_at).toLocaleString();
    const lastUsed = k.last_used ? new Date(k.last_used).toLocaleString() : 'Never';
    const roleBadge = k.role === 'admin' ? '<span class="badge badge-open">Admin</span>' : '<span class="badge badge-closed">Client</span>';
    
    return `
      <tr style="border-bottom: 1px solid var(--color-border);">
        <td style="padding: 12px 8px;">
          <div style="font-weight: 700; color: var(--color-text-main); font-size: 13px;">${escapeHtml(k.username)}</div>
          <div style="font-size: 11px; color: var(--color-text-muted); margin-top: 2px;">${escapeHtml(k.email)}</div>
        </td>
        <td style="padding: 12px 8px; font-weight: 500; font-size: 13px; color: var(--color-text-main);">${escapeHtml(k.name)}</td>
        <td style="padding: 12px 8px; font-family: monospace; font-size: 13px; color: var(--color-text-muted);">${k.key_masked}</td>
        <td style="padding: 12px 8px;">${roleBadge}</td>
        <td style="padding: 12px 8px; font-size: 12px; color: var(--color-text-muted);">${created}</td>
        <td style="padding: 12px 8px; font-size: 12px; color: var(--color-text-muted);">${lastUsed}</td>
        <td style="padding: 12px 8px; text-align: right;">
          <button class="btn btn-outline btn-small" onclick="revokeAdminApiKey(${k.id}, '${escapeHtml(k.name)}')" style="color: var(--color-danger); border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.02); padding: 4px 8px; font-size: 11px;">
            <i data-lucide="trash-2" style="width: 12px; height: 12px; vertical-align: middle;"></i> Revoke
          </button>
        </td>
      </tr>
    `;
  }).join('');
  lucide.createIcons();
}

window.filterAdminApiKeys = function() {
  const query = document.getElementById('adminKeysSearchInput').value.toLowerCase().trim();
  if (!query) {
    renderAdminKeysTable(adminApiKeysList);
    return;
  }

  const filtered = adminApiKeysList.filter(k => {
    return k.name.toLowerCase().includes(query) ||
           k.username.toLowerCase().includes(query) ||
           k.email.toLowerCase().includes(query) ||
           k.key_masked.toLowerCase().includes(query);
  });

  renderAdminKeysTable(filtered);
};

window.revokeAdminApiKey = async function(keyId, keyName) {
  if (!confirm(`Are you sure you want to revoke the API key "${keyName}"? This action will immediately terminate access for this credential.`)) {
    return;
  }

  try {
    const res = await fetch(`/api/keys/${keyId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("Failed to revoke key.");
    const data = await res.json();
    showToast(data.message || "API key successfully revoked.", "success");
    loadAdminApiKeys();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
}

window.handleCreateApiKey = async function(event) {
  event.preventDefault();
  const nameInput = document.getElementById('apiKeyName');
  const name = nameInput.value.trim();
  const submitBtn = event.target.querySelector('button[type="submit"]');
  const displayBlock = document.getElementById('newlyGeneratedKeyBlock');
  const displayValue = document.getElementById('newlyGeneratedKeyValue');

  if (!name) return;

  submitBtn.disabled = true;
  submitBtn.innerHTML = `<i data-lucide="loader-2" class="spin" style="width: 16px; height: 16px; margin-right: 8px; vertical-align: middle;"></i> Generating...`;
  lucide.createIcons();

  try {
    const res = await fetch('/api/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.message || "Failed to generate key.");
    }

    const data = await res.json();
    showToast("Admin API key successfully generated!", "success");
    
    // Reset form
    nameInput.value = '';
    
    // Display the full raw key once
    displayValue.value = data.key.key;
    displayBlock.style.display = 'block';
    
    // Refresh table and counts
    loadAdminApiKeys();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<i data-lucide="key-round"></i> Generate API Key`;
    lucide.createIcons();
  }
};

window.copyGeneratedApiKey = function() {
  const displayValue = document.getElementById('newlyGeneratedKeyValue');
  if (!displayValue || !displayValue.value) return;

  displayValue.select();
  displayValue.setSelectionRange(0, 99999);

  navigator.clipboard.writeText(displayValue.value)
    .then(() => {
      showToast("API key copied to clipboard!", "success");
    })
    .catch(() => {
      showToast("Failed to copy key automatically.", "error");
    });
};

let discordUsers = [];

async function loadDiscordUsers() {
  try {
    const response = await fetch('/api/admin/discord/users');
    if (response.ok) {
      const data = await response.json();
      discordUsers = data.users || [];
      populateDiscordSelect('createDiscordUser');
      populateDiscordSelect('deployDiscordUser');
    } else {
      console.warn("Failed to fetch Discord users");
      fallbackToManualInput('createDiscordUser');
      fallbackToManualInput('deployDiscordUser');
    }
  } catch (err) {
    console.error("Error loading Discord users", err);
    fallbackToManualInput('createDiscordUser');
    fallbackToManualInput('deployDiscordUser');
  }
}
window.loadDiscordUsers = loadDiscordUsers;

function populateDiscordSelect(selectId) {
  let select = document.getElementById(selectId);
  if (!select) return;
  
  if (discordUsers.length === 0) {
    fallbackToManualInput(selectId);
    return;
  }
  
  if (select.tagName === 'INPUT') {
    const newSelect = document.createElement('select');
    newSelect.id = selectId;
    newSelect.className = 'form-input';
    select.parentNode.replaceChild(newSelect, select);
    select = newSelect;
  }
  
  select.innerHTML = '<option value="">No Discord notification</option>';
  
  discordUsers.forEach(user => {
    const opt = document.createElement('option');
    opt.value = user.id;
    opt.textContent = `${user.display_name} (@${user.username})`;
    select.appendChild(opt);
  });
}

function fallbackToManualInput(elementId) {
  const element = document.getElementById(elementId);
  if (!element) return;
  if (element.tagName === 'INPUT') return;
  
  const input = document.createElement('input');
  input.type = 'text';
  input.id = elementId;
  input.className = 'form-input';
  input.placeholder = 'Enter Discord User ID manually (Optional)';
  
  element.parentNode.replaceChild(input, element);
}

async function saveDiscordIntegration(event) {
  event.preventDefault();
  const token = document.getElementById('discordBotToken').value.trim();
  const guildId = document.getElementById('discordGuildId').value.trim();
  const webhookUrl = document.getElementById('discordWebhookUrl').value.trim();
  
  try {
    const response = await fetch('/api/admin/settings/discord', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        discord_bot_token: token,
        discord_guild_id: guildId,
        discord_webhook_url: webhookUrl
      })
    });
    const result = await window.handleFetchResponse(response);
    showToast(result.message || "Discord integration settings saved.", "success");
    // Reload users in case credentials were just configured
    loadDiscordUsers();
  } catch (err) {
    showToast(`Failed to save Discord settings: ${err.message}`, "error");
  }
}
window.saveDiscordIntegration = saveDiscordIntegration;


// ════════════════════════════════════════════════════════════════
// Windows Image Manager
// ════════════════════════════════════════════════════════════════

let _winBuildPollTimer = null;

async function loadWindowsImages() {
  const list = document.getElementById('windows-images-list');
  if (!list) return;
  try {
    const res = await fetch('/api/admin/windows/images');
    const data = await window.handleFetchResponse(res);
    if (!data.images || data.images.length === 0) {
      list.innerHTML = '<span style="color: var(--color-text-muted);">No Windows images installed yet. Build one below or upload a pre-made image.</span>';
      return;
    }
    list.innerHTML = data.images.map(alias =>
      `<span style="background-color: #0078D4; color: white; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600;">${alias}</span>`
    ).join(' ');
  } catch (err) {
    list.innerHTML = `<span style="color: var(--color-danger);">Failed to load: ${err.message}</span>`;
  }
}
window.loadWindowsImages = loadWindowsImages;

async function startWindowsBuild() {
  const alias = document.getElementById('winBuildAlias').value.trim() || 'windows/10';
  const isoPath = document.getElementById('winBuildIso').value.trim();
  const password = document.getElementById('winBuildPassword').value || 'MintyHost!2026';
  const btn = document.getElementById('winBuildBtn');
  const status = document.getElementById('winBuildStatus');
  btn.disabled = true;
  status.textContent = 'Starting build…';
  try {
    const res = await fetch('/api/admin/windows/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alias, iso_path: isoPath, default_password: password })
    });
    const result = await window.handleFetchResponse(res);
    status.textContent = result.message || 'Build started.';
    pollWindowsBuild();
  } catch (err) {
    status.textContent = `Failed: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}
window.startWindowsBuild = startWindowsBuild;

async function pollWindowsBuild() {
  if (_winBuildPollTimer) clearInterval(_winBuildPollTimer);
  _winBuildPollTimer = setInterval(async () => {
    try {
      const [statusRes, logRes] = await Promise.all([
        fetch('/api/admin/windows/build-status'),
        fetch('/api/admin/windows/build-log')
      ]);
      const statusData = await statusRes.json();
      const logData = await logRes.json();
      const status = document.getElementById('winBuildStatus');
      const logEl = document.getElementById('winBuildLog');
      if (logEl && logData.tail) {
        logEl.textContent = logData.content || '';
        logEl.scrollTop = logEl.scrollHeight;
      }
      if (statusData.finished) {
        clearInterval(_winBuildPollTimer);
        _winBuildPollTimer = null;
        status.textContent = statusData.ok
          ? '✅ Build finished successfully. Image ready to deploy.'
          : '❌ Build failed. See log below for details.';
        if (statusData.ok) {
          loadWindowsImages();
          showToast('Windows image built successfully!', 'success');
        } else {
          showToast('Windows image build failed.', 'error');
        }
      } else if (statusData.running) {
        const lastMsg = (statusData.progress && statusData.progress.length > 0)
          ? statusData.progress[statusData.progress.length - 1].msg
          : 'Build running…';
        status.textContent = '🔨 ' + lastMsg;
      }
    } catch (err) {
      // ignore transient errors
    }
  }, 4000);
}
window.pollWindowsBuild = pollWindowsBuild;

async function uploadWindowsImage() {
  const fileInput = document.getElementById('winUploadFile');
  const aliasInput = document.getElementById('winUploadAlias');
  const status = document.getElementById('winUploadStatus');
  if (!fileInput.files || fileInput.files.length === 0) {
    status.textContent = 'Please choose a file first.';
    return;
  }
  const file = fileInput.files[0];
  const alias = aliasInput.value.trim() || 'windows/10';
  status.textContent = `Uploading ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)…`;
  try {
    const fd = new FormData();
    fd.append('image', file);
    fd.append('alias', alias);
    fd.append('os', 'windows');
    const res = await fetch('/api/admin/windows/upload', { method: 'POST', body: fd });
    const result = await window.handleFetchResponse(res);
    status.textContent = `✅ ${result.message}`;
    showToast('Windows image imported!', 'success');
    loadWindowsImages();
    fileInput.value = '';
  } catch (err) {
    status.textContent = `Failed: ${err.message}`;
  }
}
window.uploadWindowsImage = uploadWindowsImage;

// Hook into panel switching
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-target="panel-windows"]').forEach(el => {
    el.addEventListener('click', () => {
      loadWindowsImages();
      fetch('/api/admin/windows/build-log').then(r => r.json()).then(d => {
        if (d && d.tail) {
          document.getElementById('winBuildLog').textContent = d.content || '';
        }
      });
      fetch('/api/admin/windows/build-status').then(r => r.json()).then(d => {
        if (d.running) pollWindowsBuild();
        if (d.finished) {
          const s = document.getElementById('winBuildStatus');
          if (s) s.textContent = d.ok ? '✅ Build finished successfully.' : '❌ Build failed.';
        }
      });
    });
  });
});

