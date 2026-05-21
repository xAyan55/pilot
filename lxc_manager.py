import subprocess
import json
import re


class LXCManager:
    @staticmethod
    def _run(cmd, check=True):
        """Execute a shell command and return stdout."""
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        return result.stdout

    @classmethod
    def get_container_ip(cls, name):
        """Retrieves the IPv4 address of the LXC container from lxc list."""
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
        steps = [
            ('Downloading and launching container image...', ['lxc', 'launch', f'images:{os_image}', name]),
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
    def destroy_container(cls, name):
        """Force-stops and deletes a container."""
        subprocess.run(['lxc', 'stop', '-f', name], capture_output=True)
        subprocess.run(['lxc', 'delete', '-f', name], capture_output=True, check=True)
        return True

    @classmethod
    def execute_action(cls, name, action):
        """Power state controls: start, stop, restart, suspend, resume."""
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
        cls._run(['lxc', 'exec', name, '--', 'bash', '-c', f'echo root:{new_password} | chpasswd'])
        return True

    @classmethod
    def get_container_stats(cls, name, plan_cpu=1, plan_ram=512, plan_disk=10):
        """Retrieves real container stats from lxc info and lxc exec."""
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

        # CPU usage as a simple percentage approximation
        cpu_pct = round(cpu_seconds % 100, 1) if status == 'running' else 0.0

        # Disk usage via df inside container
        used_disk = 0.0
        if status == 'running':
            try:
                df_out = subprocess.run(
                    ['lxc', 'exec', name, '--', 'df', '-BM', '/'],
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
        cls._run(['lxc', 'snapshot', container_name, snap_name])
        return True

    @classmethod
    def restore_snapshot(cls, container_name, snap_name):
        cls._run(['lxc', 'restore', container_name, snap_name])
        return True

    @classmethod
    def delete_snapshot(cls, container_name, snap_name):
        cls._run(['lxc', 'snapshot', 'delete', container_name, snap_name])
        return True
