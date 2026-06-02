import subprocess
import shutil
import json
import re
import os
import sys
import time

# Auto-detect if we should run in mock mode
# True if on non-Linux platform, or if lxc command is not found
LXC_BIN = shutil.which('lxc') or '/snap/bin/lxc'
IS_MOCK_LXC = (sys.platform != 'linux') or (shutil.which('lxc') is None and not os.path.exists('/snap/bin/lxc'))

if not os.path.exists(LXC_BIN):
    LXC_BIN = 'lxc'  # fallback


class WindowsImageNotFoundError(Exception):
    """Raised when no locally-imported Windows VM image is found in LXD."""
    pass


class LXCManager:
    _cpu_cache = {}  # Tracks {container_name: (timestamp, cpu_seconds)}

    @staticmethod
    def _run(cmd, check=True):
        """Execute a shell command and return stdout. Replaces 'lxc' with full path."""
        if IS_MOCK_LXC:
            return ""
        if cmd and cmd[0] == 'lxc':
            cmd = [LXC_BIN] + cmd[1:]
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        return result.stdout

    @classmethod
    def get_container_ip(cls, name):
        """Retrieves the IPv4 address of the LXC container from lxc list."""
        if IS_MOCK_LXC:
            ip_suffix = sum(ord(c) for c in name) % 250 + 4
            return f"10.155.88.{ip_suffix}"
        try:
            out = cls._run(['lxc', 'list', name, '--format=json'])
            data = json.loads(out)
            for container in data:
                if container['name'] == name:
                    state = container.get('state') or {}
                    network = state.get('network') or {}
                    for iface_name, iface_info in network.items():
                        if iface_name == 'lo':
                            continue
                        for addr in iface_info.get('addresses', []):
                            if addr.get('family') == 'inet':
                                return addr.get('address')
            return 'N/A'
        except Exception as e:
            print(f'[!] Error fetching IP for {name}: {e}')
            return 'Pending'

    @classmethod
    def _resolve_windows_image(cls):
        """Auto-detects any local image matching Windows in the aliases list.
        
        Unlike Linux distros (Ubuntu, Debian, Alpine, etc.), Windows images are NOT
        available on any standard LXD remote image server. The administrator must
        manually import a Windows ISO/disk image into LXD before Windows VPS can
        be deployed. This method searches for such a locally-imported image.
        
        Raises WindowsImageNotFoundError if no local Windows image is found.
        """
        if IS_MOCK_LXC:
            return "windows/10"
        try:
            out = cls._run(['lxc', 'image', 'list', '--format=json'])
            if out:
                images = json.loads(out)
                # 1. Exact matches in aliases list
                for img in images:
                    aliases = img.get('aliases', [])
                    for alias in aliases:
                        name = alias.get('name', '').lower()
                        if name in ['windows/10', 'win10', 'windows-10', 'windows10']:
                            return alias.get('name')
                
                # 2. Broad checks on aliases containing windows/win10
                for img in images:
                    aliases = img.get('aliases', [])
                    for alias in aliases:
                        name = alias.get('name', '').lower()
                        if 'windows' in name or 'win10' in name:
                            return alias.get('name')
                            
                # 3. Property check (os=windows)
                for img in images:
                    properties = img.get('properties', {})
                    os_prop = str(properties.get('os', '')).lower()
                    if 'windows' in os_prop or 'win' in os_prop:
                        aliases = img.get('aliases', [])
                        if aliases:
                            return aliases[0].get('name')
                        return img.get('fingerprint')
        except Exception as e:
            print(f"[WARNING] Failed to query local image list for Windows: {e}")
        
        raise WindowsImageNotFoundError(
            "No Windows VM image found in LXD. Windows images are not available on standard LXD remotes. "
            "You must import a Windows image manually before deploying Windows VPS instances. "
            "Run: bash /var/www/lxc/setup_windows_image.sh  (or see install.sh for instructions)"
        )

    @classmethod
    def deploy_container(cls, name, os_image, cpu_cores, ram_mb, disk_gb, root_password, log_callback=None):
        """Launches a real LXC container/VM and configures resource limits."""
        if IS_MOCK_LXC:
            is_windows = 'windows' in os_image.lower()
            steps = [
                ('Downloading and launching container image...', 0.5),
                ('Setting CPU core limit...', 0.2),
                ('Setting RAM memory limit...', 0.2),
                ('Configuring root storage limit...', 0.2),
            ]
            if not is_windows:
                steps.append(('Setting root password...', 0.3))
            else:
                steps.append(('Initializing Windows VM (password must be set via RDP/console)...', 0.3))
            for desc, delay in steps:
                if log_callback:
                    log_callback(f'[INFO] {desc}')
                time.sleep(delay)
            if log_callback:
                log_callback('[SUCCESS] Container deployed successfully!')
            return True

        # Resolve the image source
        if os_image.startswith('ubuntu/'):
            image_source = f"ubuntu:{os_image.split('/', 1)[1]}"
        elif 'windows' in os_image.lower():
            # Windows images must be pre-imported locally by the admin.
            # _resolve_windows_image() will raise WindowsImageNotFoundError if missing.
            if log_callback:
                log_callback('[INFO] Searching for locally-imported Windows VM image...')
            image_source = cls._resolve_windows_image()
            if log_callback:
                log_callback(f'[INFO] Found Windows image: {image_source}')
        else:
            image_source = f"images:{os_image}"

        is_windows = 'windows' in os_image.lower()
        launch_cmd = ['lxc', 'launch', image_source, name]
        if is_windows:
            launch_cmd.append('--vm')

        steps = [
            ('Downloading and launching container image...', launch_cmd),
            ('Setting CPU core limit...', ['lxc', 'config', 'set', name, 'limits.cpu', str(cpu_cores)]),
            ('Setting RAM memory limit...', ['lxc', 'config', 'set', name, 'limits.memory', f'{ram_mb}MB']),
            ('Configuring root storage limit...', ['lxc', 'config', 'device', 'override', name, 'root', f'size={disk_gb}GB']),
        ]

        if not is_windows:
            steps.append(('Setting root password...', ['lxc', 'exec', name, '--', 'bash', '-c', f'echo root:{root_password} | chpasswd']))

        for desc, cmd in steps:
            if log_callback:
                log_callback(f'[INFO] {desc}')
            try:
                cls._run(cmd)
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.strip() if e.stderr else str(e)
                if log_callback:
                    log_callback(f'[ERROR] {desc} Failed: {error_msg}')
                raise Exception(f'Deployment step failed: {desc}. Details: {error_msg}')

        if log_callback:
            log_callback('[SUCCESS] Container deployed successfully!')

    @classmethod
    def reinstall_os(cls, name, os_image, root_password, cpu_cores, ram_mb, disk_gb, log_callback=None):
        """Reinstalls OS by destroying and redeploying the container/VM."""
        cls.destroy_container(name)
        cls.deploy_container(name, os_image, cpu_cores, ram_mb, disk_gb, root_password, log_callback)

    @classmethod
    def ensure_ssh_port_forward(cls, name, vps_id=None):
        """No-op: port forwarding is managed by the daemon via iptables.
        This method exists only for backward compatibility."""
        return True

    @classmethod
    def post_deploy_setup(cls, name, vps_id, root_password, site_name=None, log_callback=None,
                          ssh_relay_enabled=None, ssh_relay_host=None, ssh_relay_port=None,
                          ssh_relay_user=None, ssh_relay_password=None, tunnel_port=None):
        """Pre-installs curl, sudo, git, wget, htop, openssh-server, configures SSH root access.
        Port forwarding is managed by the daemon via iptables — no Pinggy/Bore/SSH-relay needed."""
        is_windows = False
        if vps_id:
            try:
                from database import get_db_connection
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT os FROM vps WHERE id = ?", (vps_id,))
                row = cursor.fetchone()
                if row and 'windows' in row['os'].lower():
                    is_windows = True
                conn.close()
            except Exception:
                pass

        if is_windows:
            if log_callback:
                log_callback('[INFO] Windows VM post-deployment configuration complete (automated package installation skipped for Windows OS).')
            return True

        if IS_MOCK_LXC:
            return True

        if not site_name:
            site_name = "MintyHost LXC"

        motd_content = f"""
=====================================================================
 Welcome to {site_name}!
 Access your server via SSH on the forwarded port shown in the panel.
=====================================================================
"""

        steps = [
            ('Updating container package repositories...',
             ['lxc', 'exec', name, '--', 'apt-get', 'update']),
            ('Pre-installing system packages (curl, sudo, git, wget, htop, openssh-server)...',
             ['lxc', 'exec', name, '--', 'apt-get', 'install', '-y', 'curl', 'sudo', 'git', 'wget', 'htop', 'openssh-server']),
            ('Configuring SSH server to permit password-based root login...',
             ['lxc', 'exec', name, '--', 'bash', '-c', (
                 "sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; "
                 "sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; "
                 "sed -i 's/PermitRootLogin prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; "
                 "sed -i 's/PermitRootLogin no/PermitRootLogin yes/g' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; "
                 "sed -i 's/#PermitRootLogin yes/PermitRootLogin yes/g' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; "
                 "grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config; "
                 "grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config; "
                 "sed -i 's/session.*required.*pam_loginuid.so/session optional pam_loginuid.so/g' /etc/pam.d/sshd 2>/dev/null; "
                 "service ssh restart || systemctl restart ssh || systemctl restart sshd"
             )]),
            ('Configuring Message of the Day (MOTD)...',
             ['lxc', 'exec', name, '--', 'bash', '-c', (
                 f"cat << 'EOF' > /etc/motd\n{motd_content.strip()}\nEOF\n"
                 f"if [ -d /etc/update-motd.d ]; then\n"
                 f"  printf '#!/bin/sh\\n[ -f /etc/motd ] && cat /etc/motd\\n' > /etc/update-motd.d/00-custom-motd\n"
                 f"  chmod +x /etc/update-motd.d/00-custom-motd\n"
                 f"  if [ -x /usr/sbin/update-motd ]; then /usr/sbin/update-motd; fi\n"
                 f"fi"
             )]),
        ]

        for desc, cmd in steps:
            if log_callback:
                log_callback(f'[INFO] {desc}')
            try:
                cls._run(cmd)
            except Exception as e:
                print(f'[WARNING] post_deploy_setup step failed: {desc}. Error: {e}')
                if log_callback:
                    log_callback(f'[WARNING] {desc} failed: {str(e)}')

        return True

    @classmethod
    def destroy_container(cls, name):
        """Force-stops and deletes a container."""
        if IS_MOCK_LXC:
            return True
        subprocess.run([LXC_BIN, 'stop', '-f', name], capture_output=True)
        subprocess.run([LXC_BIN, 'delete', '-f', name], capture_output=True, check=True)
        return True

    @classmethod
    def execute_action(cls, name, action):
        """Power state controls: start, stop, restart, suspend, resume."""
        if IS_MOCK_LXC:
            return True
        action_map = {
            'start': ['lxc', 'start', name],
            'stop': ['lxc', 'stop', '-f', name],
            'restart': ['lxc', 'restart', name],
            'suspend': ['lxc', 'pause', name],
            'resume': ['lxc', 'resume', name],
        }
        if action not in action_map:
            raise ValueError(f'Invalid action: {action}')
        try:
            cls._run(action_map[action])
        except subprocess.CalledProcessError as e:
            raise Exception(f"Action '{action}' failed: {e.stderr.strip()}")
        return True

    @classmethod
    def change_password(cls, name, new_password):
        """Sets root password inside the container."""
        if IS_MOCK_LXC:
            return True
        cls._run(['lxc', 'exec', name, '--', 'bash', '-c', f'echo root:{new_password} | chpasswd'])
        return True

    @classmethod
    def get_container_stats(cls, name, plan_cpu=1, plan_ram=512, plan_disk=10, db_status='running', vps_id=None):
        """Retrieves real container stats from lxc info and lxc exec."""
        if IS_MOCK_LXC:
            import random
            status = db_status
            if status == 'running':
                cpu_pct = round(random.uniform(2.0, 12.0), 1)
                used_ram = int(plan_ram * random.uniform(0.18, 0.32))
                used_disk = round(plan_disk * 0.12, 1)
                now = time.time()
                net_in_mb = round((now % 1000) * 0.5 + 45.2, 1)
                net_out_mb = round((now % 1000) * 0.3 + 12.1, 1)
                ip_suffix = sum(ord(c) for c in name) % 250 + 4
                ip_addr = f"10.155.88.{ip_suffix}"
                uptime_str = "2 days 4 hours 12 minutes"
            elif status == 'suspended':
                cpu_pct = 0.0
                used_ram = int(plan_ram * 0.22)
                used_disk = round(plan_disk * 0.12, 1)
                net_in_mb = 45.2
                net_out_mb = 12.1
                ip_suffix = sum(ord(c) for c in name) % 250 + 4
                ip_addr = f"10.155.88.{ip_suffix}"
                uptime_str = "Suspended"
            else:
                status = 'stopped'
                cpu_pct = 0.0
                used_ram = 0
                used_disk = round(plan_disk * 0.12, 1)
                net_in_mb = 0.0
                net_out_mb = 0.0
                ip_addr = 'N/A'
                uptime_str = 'Offline'

            return {
                'name': name,
                'status': status,
                'ip': ip_addr,
                'cpu': cpu_pct,
                'ram_used': used_ram,
                'ram_limit': plan_ram,
                'disk_used': used_disk,
                'disk_limit': plan_disk,
                'net_in': net_in_mb,
                'net_out': net_out_mb,
                'uptime': uptime_str,
                'tunnel_host': None,
                'tunnel_port': None
            }

        try:
            info_out = cls._run(['lxc', 'info', name])
        except Exception:
            return {
                'name': name, 'status': 'stopped', 'ip': 'N/A',
                'cpu': 0.0, 'ram_used': 0, 'ram_limit': plan_ram,
                'disk_used': 0.0, 'disk_limit': plan_disk,
                'net_in': 0.0, 'net_out': 0.0, 'uptime': 'Offline',
                'tunnel_host': None,
                'tunnel_port': None
            }

        status = 'stopped'
        uptime_str = 'N/A'
        cpu_seconds = 0
        used_ram = 0
        net_in = 0.0
        net_out = 0.0

        for line in info_out.splitlines():
            line_s = line.strip()
            if line_s.startswith('Status:'):
                raw = line_s.split(':', 1)[1].strip().lower()
                if raw == 'running':
                    status = 'running'
                elif raw == 'stopped':
                    status = 'stopped'
                elif raw in ('frozen',):
                    status = 'suspended'
                else:
                    status = raw
            elif line_s.startswith('Uptime:'):
                uptime_str = line_s.split(':', 1)[1].strip() or 'N/A'
            elif 'Memory (current)' in line_s:
                val = line_s.split(':', 1)[1].strip()
                used_ram = cls._parse_mem(val)
            elif 'CPU usage' in line_s:
                val = line_s.split(':', 1)[1].strip()
                m = re.search(r'([\d.]+)', val)
                if m:
                    cpu_seconds = float(m.group(1))
            elif 'Bytes received' in line_s:
                m = re.search(r'([\d.]+)', line_s)
                if m:
                    net_in += float(m.group(1))
            elif 'Bytes sent' in line_s:
                m = re.search(r'([\d.]+)', line_s)
                if m:
                    net_out += float(m.group(1))

        # Convert network bytes to MB
        net_in_mb = round(net_in / (1024 * 1024), 1)
        net_out_mb = round(net_out / (1024 * 1024), 1)

        # Real CPU usage calculation using delta from cache
        cpu_pct = 0.0
        if status == 'running' and cpu_seconds > 0:
            now = time.time()
            if name in cls._cpu_cache:
                last_time, last_cpu_seconds = cls._cpu_cache[name]
                delta_time = now - last_time
                delta_cpu = cpu_seconds - last_cpu_seconds
                if delta_time > 0 and delta_cpu >= 0:
                    cores = max(1, plan_cpu)
                    raw_pct = (delta_cpu / delta_time) * 100.0
                    cpu_pct = round(max(0.0, min(100.0, raw_pct / cores)), 1)
            else:
                cpu_pct = 1.5  # default baseline on first poll
            # Update cache
            cls._cpu_cache[name] = (now, cpu_seconds)

        # Disk usage via df inside container
        used_disk = 0.0
        if status == 'running':
            try:
                df_out = subprocess.run(
                    [LXC_BIN, 'exec', name, '--', 'df', '-BM', '/'],
                    capture_output=True, text=True, timeout=5
                )
                if df_out.returncode == 0:
                    lines = df_out.stdout.strip().splitlines()
                    if len(lines) > 1:
                        parts = lines[1].split()
                        used_str = parts[2] if len(parts) > 2 else '0'
                        used_disk = round(int(re.sub(r'[^0-9]', '', used_str)) / 1024, 1)
            except Exception:
                pass

        ip_addr = cls.get_container_ip(name)

        # Port forwarding is managed by the daemon via iptables.
        # tunnel_host and tunnel_port will be populated from the daemon's _allocated_ports
        # or from the vps row in the database.
        tunnel_host = None
        tunnel_port = None
        if not IS_MOCK_LXC:
            import json as _json
            try:
                daemon_port_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'port_forwards.json')
                if os.path.exists(daemon_port_path):
                    with open(daemon_port_path) as _f:
                        _forwards = _json.load(_f)
                    if name in _forwards:
                        tunnel_port = _forwards[name]
                        tunnel_host = '0.0.0.0'
            except Exception:
                pass

        return {
            'name': name,
            'status': status,
            'ip': ip_addr,
            'cpu': cpu_pct,
            'ram_used': used_ram,
            'ram_limit': plan_ram,
            'disk_used': used_disk,
            'disk_limit': plan_disk,
            'net_in': net_in_mb,
            'net_out': net_out_mb,
            'uptime': uptime_str if status == 'running' else 'Offline',
            'tunnel_host': tunnel_host,
            'tunnel_port': tunnel_port
        }

    @staticmethod
    def _parse_mem(val):
        """Parse memory strings like '112.54MiB', '1.2GiB', '54321KiB'."""
        val = val.strip()
        try:
            if 'GiB' in val or 'GB' in val:
                return int(float(re.sub(r'[^\d.]', '', val)) * 1024)
            elif 'MiB' in val or 'MB' in val:
                return int(float(re.sub(r'[^\d.]', '', val)))
            elif 'KiB' in val or 'KB' in val:
                return max(1, int(float(re.sub(r'[^\d.]', '', val)) / 1024))
            elif 'B' in val:
                return max(1, int(float(re.sub(r'[^\d.]', '', val)) / (1024 * 1024)))
            else:
                return int(float(val))
        except Exception:
            return 0

    @classmethod
    def create_snapshot(cls, container_name, snap_name):
        if IS_MOCK_LXC:
            return True
        cls._run(['lxc', 'snapshot', container_name, snap_name])
        return True

    @classmethod
    def restore_snapshot(cls, container_name, snap_name):
        if IS_MOCK_LXC:
            return True
        cls._run(['lxc', 'restore', container_name, snap_name])
        return True

    @classmethod
    def delete_snapshot(cls, container_name, snap_name):
        if IS_MOCK_LXC:
            return True
        cls._run(['lxc', 'snapshot', 'delete', container_name, snap_name])
        return True

