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
    def deploy_container(cls, name, os_image, cpu_cores, ram_mb, disk_gb, root_password, log_callback=None):
        """Launches a real LXC container and configures resource limits."""
        if IS_MOCK_LXC:
            steps = [
                ('Downloading and launching container image...', 0.5),
                ('Setting CPU core limit...', 0.2),
                ('Setting RAM memory limit...', 0.2),
                ('Configuring root storage limit...', 0.2),
                ('Setting root password...', 0.3),
            ]
            for desc, delay in steps:
                if log_callback:
                    log_callback(f'[INFO] {desc}')
                time.sleep(delay)
            if log_callback:
                log_callback('[SUCCESS] Container deployed successfully!')
            return True

        # Use official ubuntu: remote for Ubuntu, fallback to images: remote for community distros
        if os_image.startswith('ubuntu/'):
            image_source = f"ubuntu:{os_image.split('/', 1)[1]}"
        else:
            image_source = f"images:{os_image}"

        steps = [
            ('Downloading and launching container image...', ['lxc', 'launch', image_source, name]),
            ('Setting CPU core limit...', ['lxc', 'config', 'set', name, 'limits.cpu', str(cpu_cores)]),
            ('Setting RAM memory limit...', ['lxc', 'config', 'set', name, 'limits.memory', f'{ram_mb}MB']),
            ('Configuring root storage limit...', ['lxc', 'config', 'device', 'override', name, 'root', f'size={disk_gb}GB']),
            ('Setting root password...', ['lxc', 'exec', name, '--', 'bash', '-c', f'echo root:{root_password} | chpasswd']),
        ]

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
    def post_deploy_setup(cls, name, vps_id, root_password, log_callback=None):
        """Pre-installs curl, sudo, git, wget, htop, openssh-server, configures SSH root access, and installs/starts Bore tunnel."""
        if IS_MOCK_LXC:
            return True

        import base64
        tunnel_port = 40000 + vps_id
        bore_service_content = f"""[Unit]
Description=Bore TCP Tunnel
After=network.target

[Service]
ExecStart=/usr/local/bin/bore local 22 --to bore.pub --port {tunnel_port}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"""

        encoded_service = base64.b64encode(bore_service_content.encode('utf-8')).decode('utf-8')

        steps = [
            ('Updating container package repositories...',
             ['lxc', 'exec', name, '--', 'apt-get', 'update']),
            ('Pre-installing system packages (curl, sudo, git, wget, htop, openssh-server)...',
             ['lxc', 'exec', name, '--', 'apt-get', 'install', '-y', 'curl', 'sudo', 'git', 'wget', 'htop', 'openssh-server']),
            ('Configuring SSH server to permit password-based root login...',
             ['lxc', 'exec', name, '--', 'bash', '-c', "sed -i 's/prohibit-password/yes/g' /etc/ssh/sshd_config; sed -i 's/#PermitRootLogin/PermitRootLogin/g' /etc/ssh/sshd_config; service ssh restart || systemctl restart ssh || systemctl restart sshd"]),
            ('Downloading and installing Bore TCP tunneling client...',
             ['lxc', 'exec', name, '--', 'bash', '-c', "curl -Ls https://github.com/ekzhang/bore/releases/download/v0.5.1/bore-v0.5.1-x86_64-unknown-linux-musl.tar.gz | tar -xz -C /usr/local/bin"]),
            ('Registering Bore systemd background service configuration...',
             ['lxc', 'exec', name, '--', 'bash', '-c', f"echo {encoded_service} | base64 -d > /etc/systemd/system/bore.service"]),
            ('Enabling and starting Bore tunnel service...',
             ['lxc', 'exec', name, '--', 'bash', '-c', "systemctl daemon-reload && systemctl enable bore && systemctl start bore"]),
        ]

        for desc, cmd in steps:
            if log_callback:
                log_callback(f'[INFO] {desc}')
            try:
                cls._run(cmd)
            except Exception as e:
                # Log warning but do not crash the deployment flow if post-install tunnel fails
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
    def get_container_stats(cls, name, plan_cpu=1, plan_ram=512, plan_disk=10, db_status='running'):
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
                'uptime': uptime_str
            }

        try:
            info_out = cls._run(['lxc', 'info', name])
        except Exception:
            return {
                'name': name, 'status': 'stopped', 'ip': 'N/A',
                'cpu': 0.0, 'ram_used': 0, 'ram_limit': plan_ram,
                'disk_used': 0.0, 'disk_limit': plan_disk,
                'net_in': 0.0, 'net_out': 0.0, 'uptime': 'Offline'
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
            'uptime': uptime_str if status == 'running' else 'Offline'
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

