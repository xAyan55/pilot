import { platform } from 'node:os';
import { spawn } from 'child_process';
import logger from '../logger';

// Auto-detect Mock Mode for non-Linux or LXC-less systems
let lxcPath: string | null = null;
try {
  // Simple check for lxc command presence
  const proc = Bun.spawnSync(['which', 'lxc']);
  if (proc.exitCode === 0) {
    lxcPath = proc.stdout.toString().trim();
  }
} catch {
  // ignore
}
if (!lxcPath) {
  // Check snap location
  const file = Bun.file('/snap/bin/lxc');
  if (file.size > 0) {
    lxcPath = '/snap/bin/lxc';
  }
}

export const IS_MOCK_LXC = platform() !== 'linux' || !lxcPath;
const LXC_BIN = lxcPath || 'lxc';

// CPU cache tracking for CPU usage delta calculations
const cpuCache = new Map<string, { time: number; seconds: number }>();

async function runCmd(cmd: string[], check = true): Promise<string> {
  if (IS_MOCK_LXC) return '';
  const finalCmd = cmd[0] === 'lxc' ? [LXC_BIN, ...cmd.slice(1)] : cmd;
  
  const proc = Bun.spawn(finalCmd);
  await proc.exited;
  
  const stdout = await new Response(proc.stdout).text();
  const stderr = await new Response(proc.stderr).text();
  
  if (check && proc.exitCode !== 0) {
    throw new Error(stderr.trim() || `Command failed with exit code ${proc.exitCode}`);
  }
  return stdout;
}

export class LXCManager {
  static async getContainerIp(name: string): Promise<string> {
    if (IS_MOCK_LXC) {
      const sum = [...name].reduce((acc, c) => acc + c.charCodeAt(0), 0);
      return `10.155.88.${(sum % 250) + 4}`;
    }
    try {
      const out = await runCmd(['lxc', 'list', name, '--format=json']);
      const data = JSON.parse(out);
      for (const container of data) {
        if (container.name === name) {
          const state = container.state || {};
          const network = state.network || {};
          for (const iface of Object.keys(network)) {
            if (iface === 'lo') continue;
            for (const addr of network[iface].addresses || []) {
              if (addr.family === 'inet') {
                return addr.address;
              }
            }
          }
        }
      }
      return 'N/A';
    } catch (e) {
      logger.error(`Error fetching IP for ${name}:`, e);
      return 'Pending';
    }
  }

  static async deployContainer(
    name: string,
    osImage: string,
    cpuCores: number,
    ramMb: number,
    diskGb: number,
    rootPassword: string,
    logCallback?: (msg: string) => void
  ): Promise<boolean> {
    const isWindows = osImage.toLowerCase().includes('windows') || osImage.toLowerCase().startsWith('win');

    if (IS_MOCK_LXC) {
      logCallback?.('[INFO] Downloading and launching container image...');
      await Bun.sleep(500);
      logCallback?.('[INFO] Setting CPU core limit...');
      await Bun.sleep(200);
      logCallback?.('[INFO] Setting RAM memory limit...');
      await Bun.sleep(200);
      logCallback?.('[INFO] Configuring root storage limit...');
      await Bun.sleep(200);
      if (!isWindows) {
        logCallback?.('[INFO] Setting root password...');
        await Bun.sleep(300);
      } else {
        logCallback?.('[INFO] Initializing Windows VM...');
        await Bun.sleep(300);
      }
      logCallback?.('[SUCCESS] Container deployed successfully!');
      return true;
    }

    const imageCandidates: string[] = [];
    if (isWindows) {
      logCallback?.('[INFO] Searching for locally-imported Windows VM image...');
      // Simplification: search local images
      let winAlias = 'windows/10';
      try {
        const out = await runCmd(['lxc', 'image', 'list', '--format=json']);
        if (out) {
          const images = JSON.parse(out);
          for (const img of images) {
            for (const alias of img.aliases || []) {
              const nameLower = alias.name.toLowerCase();
              if (nameLower.startsWith('windows/') || nameLower.startsWith('win')) {
                winAlias = alias.name;
                break;
              }
            }
          }
        }
      } catch (err) {
        logCallback?.(`[WARNING] Failed to query local images: ${err}`);
      }
      imageCandidates.push(winAlias);
    } else if (osImage.startsWith('ubuntu/')) {
      const ver = osImage.split('/')[1];
      imageCandidates.push(`images:ubuntu/${ver}/cloud`);
      imageCandidates.push(`images:ubuntu/${ver}`);
      imageCandidates.push(`ubuntu:${ver}`);
    } else if (osImage.startsWith('debian/')) {
      const ver = osImage.split('/')[1];
      imageCandidates.push(`images:debian/${ver}`);
      imageCandidates.push(`images:debian/${ver}/cloud`);
    } else if (osImage.startsWith('alpine/')) {
      const ver = osImage.split('/')[1];
      imageCandidates.push(`images:alpine/${ver}`);
    } else {
      imageCandidates.push(`images:${osImage}`);
      imageCandidates.push(`images:${osImage}/cloud`);
    }

    let launched = false;
    let lastError = '';
    for (const source of imageCandidates) {
      logCallback?.(`[INFO] Launching using image source: ${source}`);
      try {
        const args = ['lxc', 'launch', source, name];
        if (isWindows) args.push('--vm');
        await runCmd(args);
        launched = true;
        break;
      } catch (e: any) {
        lastError = e.message;
        logCallback?.(`[WARNING] Source ${source} failed: ${lastError}`);
      }
    }

    if (!launched) {
      throw new Error(`Deployment step failed: Launching container image. Details: ${lastError}`);
    }

    // Set resource limits
    logCallback?.('[INFO] Setting CPU core limit...');
    await runCmd(['lxc', 'config', 'set', name, 'limits.cpu', String(cpuCores)]);

    logCallback?.('[INFO] Setting RAM memory limit...');
    await runCmd(['lxc', 'config', 'set', name, 'limits.memory', `${ramMb}MB`]);

    logCallback?.('[INFO] Configuring root storage limit...');
    try {
      await runCmd(['lxc', 'config', 'device', 'override', name, 'root', `size=${diskGb}GB`]);
    } catch {
      // device override might fail if already overridden, ignore or set
      await runCmd(['lxc', 'config', 'device', 'set', name, 'root', 'size', `${diskGb}GB`], false);
    }

    if (!isWindows) {
      logCallback?.('[INFO] Setting root password...');
      await runCmd(['lxc', 'exec', name, '--', 'bash', '-c', `echo root:${rootPassword} | chpasswd`]);
    } else {
      logCallback?.('[INFO] Setting Windows Administrator password...');
      // Async setup password inside VM using net user / powershell
      await LXCManager.setWindowsPassword(name, rootPassword, logCallback);
    }

    logCallback?.('[SUCCESS] Container deployed successfully!');
    return true;
  }

  static async setWindowsPassword(name: string, pw: string, logCallback?: (msg: string) => void): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    const safePw = pw.replace(/'/g, "''").replace(/"/g, '\\"');
    const psScript = `
      $ErrorActionPreference = 'Stop';
      try {
        $pw = ConvertTo-SecureString '${safePw}' -AsPlainText -Force;
        Set-LocalUser -Name 'Administrator' -Password $pw -ErrorAction Stop;
      } catch {
        net user Administrator '${safePw}';
      }
      try { Set-LocalUser -Name 'Administrator' -PasswordNeverExpires $true -ErrorAction SilentlyContinue } catch {};
      try { Get-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Enable-NetFirewallRule } catch {};
      try { New-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -Direction Inbound -LocalPort 22 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue } catch {};
      try { Set-Service -Name sshd -StartupType 'Automatic' -ErrorAction SilentlyContinue; Start-Service -Name sshd -ErrorAction SilentlyContinue } catch {};
      try { Set-NetFirewallRule -DisplayGroup 'Remote Desktop' -Enabled True -ErrorAction SilentlyContinue } catch {};
      try { New-NetFirewallRule -DisplayName 'Allow RDP 3389' -Direction Inbound -LocalPort 3389 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue } catch {};
      try { Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name 'fDenyTSConnections' -Value 0 -ErrorAction SilentlyContinue } catch {};
      Write-Host 'WINDOWS_PASSWORD_OK'
    `.trim();

    for (let attempt = 1; attempt <= 10; attempt++) {
      logCallback?.(`[INFO] Setting password inside VM (attempt ${attempt}/10)...`);
      try {
        const out = await runCmd(['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive', '-Command', psScript], false);
        if (out.includes('WINDOWS_PASSWORD_OK')) {
          logCallback?.('[INFO] Windows VM password successfully configured.');
          return true;
        }
      } catch {
        // VM may still be booting
      }
      await Bun.sleep(10000);
    }
    return false;
  }

  static async destroyContainer(name: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    try {
      await runCmd(['lxc', 'stop', '-f', name], false);
    } catch {
      // ignore if already stopped
    }
    await runCmd(['lxc', 'delete', '-f', name]);
    return true;
  }

  static async executeAction(name: string, action: 'start' | 'stop' | 'restart' | 'suspend' | 'resume'): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    const map = {
      start: ['lxc', 'start', name],
      stop: ['lxc', 'stop', '-f', name],
      restart: ['lxc', 'restart', name],
      suspend: ['lxc', 'pause', name],
      resume: ['lxc', 'resume', name],
    };
    await runCmd(map[action]);
    return true;
  }

  static async changePassword(name: string, pw: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    const isWin = await LXCManager.isWindowsContainer(name);
    if (isWin) {
      return LXCManager.setWindowsPassword(name, pw);
    }
    await runCmd(['lxc', 'exec', name, '--', 'bash', '-c', `echo root:${pw} | chpasswd`]);
    return true;
  }

  static async isWindowsContainer(name: string): Promise<boolean> {
    if (IS_MOCK_LXC) return false;
    try {
      const out = await runCmd(['lxc', 'list', name, '--format=csv', '-c', 't'], false);
      return out.toLowerCase().includes('virtual-machine');
    } catch {
      return false;
    }
  }

  static async getContainerStats(
    name: string,
    planCpu: number,
    planRam: number,
    planDisk: number,
    dbStatus: string
  ): Promise<any> {
    if (IS_MOCK_LXC) {
      const ip = await LXCManager.getContainerIp(name);
      if (dbStatus !== 'running') {
        return {
          name, status: dbStatus, ip, cpu: 0, ram_used: 0, ram_limit: planRam,
          disk_used: 0, disk_limit: planDisk, net_in: 0, net_out: 0, uptime: 'Offline'
        };
      }
      return {
        name,
        status: 'running',
        ip,
        cpu: round(Math.random() * 5 + 1, 1),
        ram_used: Math.floor(planRam * 0.22),
        ram_limit: planRam,
        disk_used: round(planDisk * 0.15, 1),
        disk_limit: planDisk,
        net_in: 12.5,
        net_out: 4.8,
        uptime: '1 day, 2 hours'
      };
    }

    try {
      const infoOut = await runCmd(['lxc', 'info', name]);
      let status = 'stopped';
      let uptime = 'N/A';
      let currentRam = 0;
      let cpuSeconds = 0;
      let netIn = 0;
      let netOut = 0;

      for (const line of infoOut.split('\n')) {
        const lineS = line.trim();
        if (lineS.startsWith('Status:')) {
          const raw = lineS.split(':')[1].trim().toLowerCase();
          if (raw === 'running') status = 'running';
          else if (raw === 'frozen') status = 'suspended';
          else status = raw;
        } else if (lineS.startsWith('Uptime:')) {
          uptime = lineS.split(':')[1].trim();
        } else if (lineS.includes('Memory (current)')) {
          currentRam = parseMem(lineS.split(':')[1].trim());
        } else if (lineS.includes('CPU usage')) {
          const match = lineS.match(/([\d.]+)/);
          if (match) cpuSeconds = parseFloat(match[1]);
        } else if (lineS.includes('Bytes received')) {
          const match = lineS.match(/([\d.]+)/);
          if (match) netIn += parseFloat(match[1]);
        } else if (lineS.includes('Bytes sent')) {
          const match = lineS.match(/([\d.]+)/);
          if (match) netOut += parseFloat(match[1]);
        }
      }

      // CPU percentage delta calculation
      let cpuPct = 0.0;
      if (status === 'running' && cpuSeconds > 0) {
        const now = Date.now();
        const cached = cpuCache.get(name);
        if (cached) {
          const deltaTime = (now - cached.time) / 1000;
          const deltaCpu = cpuSeconds - cached.seconds;
          if (deltaTime > 0 && deltaCpu >= 0) {
            const cores = Math.max(1, planCpu);
            cpuPct = round(((deltaCpu / deltaTime) * 100) / cores, 1);
            if (cpuPct > 100) cpuPct = 100;
          }
        } else {
          cpuPct = 1.0;
        }
        cpuCache.set(name, { time: now, seconds: cpuSeconds });
      }

      // Disk usage
      let diskUsed = 0.0;
      if (status === 'running') {
        const isWin = await LXCManager.isWindowsContainer(name);
        if (isWin) {
          try {
            const psOut = await runCmd([
              'lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive',
              '-Command', "(Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | Measure-Object -Property Used -Sum).Sum / 1GB"
            ], false);
            const lines = psOut.trim().split('\n');
            const val = lines[lines.length - 1].replace(/[^0-9.]/g, '');
            if (val) diskUsed = round(parseFloat(val), 1);
          } catch {
            // ignore
          }
        } else {
          try {
            const dfOut = await runCmd(['lxc', 'exec', name, '--', 'df', '-BM', '/'], false);
            const lines = dfOut.trim().split('\n');
            if (lines.length > 1) {
              const parts = lines[1].split(/\s+/);
              const usedStr = parts[2] || '0';
              diskUsed = round(parseInt(usedStr.replace(/[^0-9]/g, '')) / 1024, 1);
            }
          } catch {
            // ignore
          }
        }
      }

      const ip = await LXCManager.getContainerIp(name);

      return {
        name,
        status,
        ip,
        cpu: cpuPct,
        ram_used: currentRam,
        ram_limit: planRam,
        disk_used: diskUsed,
        disk_limit: planDisk,
        net_in: round(netIn / (1024 * 1024), 1),
        net_out: round(netOut / (1024 * 1024), 1),
        uptime: status === 'running' ? uptime : 'Offline'
      };
    } catch {
      return {
        name, status: 'stopped', ip: 'N/A', cpu: 0, ram_used: 0, ram_limit: planRam,
        disk_used: 0, disk_limit: planDisk, net_in: 0, net_out: 0, uptime: 'Offline'
      };
    }
  }

  // Snapshots
  static async createSnapshot(name: string, snapName: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    await runCmd(['lxc', 'snapshot', name, snapName]);
    return true;
  }

  static async restoreSnapshot(name: string, snapName: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    await runCmd(['lxc', 'restore', name, snapName]);
    return true;
  }

  static async deleteSnapshot(name: string, snapName: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    await runCmd(['lxc', 'snapshot', 'delete', name, snapName]);
    return true;
  }

  // File system
  static async listFiles(name: string, path: string): Promise<any[]> {
    if (IS_MOCK_LXC) {
      return [
        { name: 'console.log', type: 'file', size: 2048, modified: Date.now() / 1000 },
        { name: 'config', type: 'directory', size: 4096, modified: Date.now() / 1000 }
      ];
    }
    const isWin = await LXCManager.isWindowsContainer(name);
    if (isWin) {
      const psScript = `
        $ErrorActionPreference = 'Stop';
        Get-ChildItem -Path '${path}' |
        Select-Object Name,
        @{Name='Type';Expression={if ($_.PSIsContainer) {'directory'} else {'file'}}},
        Length,
        @{Name='Modified';Expression={[int][double]::Parse((Get-Date $_.LastWriteTime -UFormat %s))}} |
        ConvertTo-Json -Compress
      `.trim();
      try {
        const out = await runCmd(['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive', '-Command', psScript]);
        if (!out.trim()) return [];
        const parsed = JSON.parse(out);
        const items = Array.isArray(parsed) ? parsed : [parsed];
        return items.map((item: any) => ({
          name: item.Name,
          type: item.Type,
          size: item.Length || 0,
          modified: item.Modified
        }));
      } catch {
        return [];
      }
    } else {
      try {
        // Output format: type|size|mtime|name
        const out = await runCmd(['lxc', 'exec', name, '--', 'find', path, '-mindepth', '1', '-maxdepth', '1', '-printf', '%y|%s|%T@|%f\\n']);
        const items = [];
        for (const line of out.split('\n')) {
          if (!line.trim()) continue;
          const parts = line.split('|');
          if (parts.length === 4) {
            const [ftype, fsize, fmtime, fname] = parts;
            items.push({
              name: fname,
              type: ftype === 'd' ? 'directory' : 'file',
              size: parseInt(fsize) || 0,
              modified: parseFloat(fmtime) || 0
            });
          }
        }
        return items;
      } catch {
        throw new Error('Directory not found or access denied');
      }
    }
  }

  static async readFile(name: string, path: string): Promise<string> {
    if (IS_MOCK_LXC) return `Mock file content of ${path}`;
    return runCmd(['lxc', 'file', 'pull', `${name}/${path}`, '-']);
  }

  static async writeFile(name: string, path: string, content: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    const finalCmd = [LXC_BIN, 'file', 'push', '-', `${name}/${path}`];
    const proc = Bun.spawn(finalCmd, { stdin: 'pipe' });
    if (!proc.stdin) {
      throw new Error('Failed to open stdin for container writing');
    }
    proc.stdin.write(content);
    proc.stdin.flush();
    proc.stdin.end();
    await proc.exited;
    if (proc.exitCode !== 0) {
      throw new Error(`Failed to write file ${path}`);
    }
    return true;
  }

  static async deleteFile(name: string, path: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    await runCmd(['lxc', 'file', 'delete', `${name}/${path}`]);
    return true;
  }

  static async createDirectory(name: string, path: string): Promise<boolean> {
    if (IS_MOCK_LXC) return true;
    const isWin = await LXCManager.isWindowsContainer(name);
    if (isWin) {
      const psScript = `New-Item -ItemType Directory -Force -Path '${path}'`;
      await runCmd(['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive', '-Command', psScript]);
    } else {
      await runCmd(['lxc', 'exec', name, '--', 'mkdir', '-p', path]);
    }
    return true;
  }
}

function parseMem(val: string): number {
  const clean = val.trim();
  try {
    const num = parseFloat(clean.replace(/[^0-9.]/g, ''));
    if (clean.includes('GiB') || clean.includes('GB')) return Math.floor(num * 1024);
    if (clean.includes('MiB') || clean.includes('MB')) return Math.floor(num);
    if (clean.includes('KiB') || clean.includes('KB')) return Math.floor(num / 1024);
    return Math.floor(num);
  } catch {
    return 0;
  }
}

function round(val: number, decimals: number): number {
  const p = Math.pow(10, decimals);
  return Math.round(val * p) / p;
}
