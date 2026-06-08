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
    def _resolve_windows_image(cls, os_image='windows/10'):
        """Auto-detects any local image matching the requested Windows variant.

        Supports the following os_image values:
            windows/10, win10, win11, windows/11, windows/server/2022,
            windows/server/2019, windows/8, win8

        Unlike Linux distros (Ubuntu, Debian, Alpine, etc.), Windows images are NOT
        available on any standard LXD remote image server. The administrator must
        manually import a Windows ISO/disk image into LXD before Windows VPS can
        be deployed. This method searches for such a locally-imported image.

        Raises WindowsImageNotFoundError if no local Windows image is found.
        """
        if IS_MOCK_LXC:
            return os_image if os_image else "windows/10"

        alias_hints = {
            'windows/10':   ['windows/10', 'win10', 'windows-10', 'windows10'],
            'win10':        ['windows/10', 'win10', 'windows-10', 'windows10'],
            'windows/11':   ['windows/11', 'win11', 'windows-11', 'windows11'],
            'win11':        ['windows/11', 'win11', 'windows-11', 'windows11'],
            'windows/server/2022': ['windows/server/2022', 'win2022', 'server2022'],
            'win2022':      ['windows/server/2022', 'win2022', 'server2022'],
            'windows/server/2019': ['windows/server/2019', 'win2019', 'server2019'],
            'win2019':      ['windows/server/2019', 'win2019', 'server2019'],
            'windows/8':    ['windows/8', 'win8', 'windows-8', 'windows8'],
        }
        preferred = alias_hints.get(os_image.lower(), None)
        try:
            out = cls._run(['lxc', 'image', 'list', '--format=json'])
            if not out:
                pass
            else:
                images = json.loads(out)
                # 1. Preferred exact alias match
                if preferred:
                    for img in images:
                        for alias in img.get('aliases', []):
                            if alias.get('name', '').lower() in preferred:
                                return alias.get('name')
                # 2. Generic prefix match (any windows image)
                for img in images:
                    for alias in img.get('aliases', []):
                        name = alias.get('name', '').lower()
                        if name.startswith('windows/') or name.startswith('win'):
                            return alias.get('name')
                # 3. Property check (os=windows)
                for img in images:
                    props = img.get('properties', {})
                    if 'windows' in str(props.get('os', '')).lower():
                        aliases = img.get('aliases', [])
                        if aliases:
                            return aliases[0].get('name')
                        return img.get('fingerprint')
        except Exception as e:
            print(f"[WARNING] Failed to query local image list for Windows: {e}")

        raise WindowsImageNotFoundError(
            f"No Windows VM image matching '{os_image}' found in LXD. "
            "Windows images are not available on standard LXD remotes. "
            "You must import a Windows image manually before deploying Windows VPS instances. "
            "Options:\n"
            "  • Run: bash /var/www/lxc/setup_windows_image.sh\n"
            "  • Upload a .vhd/.vhdx/.qcow2/.img/.iso via the admin panel: Admin → Windows → Upload Image\n"
            "  • Import a pre-built cloud image: lxc image import <file> --alias <name>"
        )

    @classmethod
    def deploy_container(cls, name, os_image, cpu_cores, ram_mb, disk_gb, root_password, log_callback=None):
        """Launches a real LXC container/VM and configures resource limits."""
        is_windows = 'windows' in os_image.lower() or 'win' == os_image.lower()[:3]

        if IS_MOCK_LXC:
            steps = [
                ('Downloading and launching container image...', 0.5),
                ('Setting CPU core limit...', 0.2),
                ('Setting RAM memory limit...', 0.2),
                ('Configuring root storage limit...', 0.2),
            ]
            if not is_windows:
                steps.append(('Setting root password...', 0.3))
            else:
                steps.append(('Initializing Windows VM...', 0.3))
            for desc, delay in steps:
                if log_callback:
                    log_callback(f'[INFO] {desc}')
                time.sleep(delay)
            if log_callback:
                log_callback('[SUCCESS] Container deployed successfully!')
            return True

        if is_windows:
            cpu_cores = max(int(cpu_cores), 2)
            ram_mb = max(int(ram_mb), 2048)
            disk_gb = max(int(disk_gb), 32)
            if log_callback:
                log_callback(f'[INFO] Windows VM minimums applied: {cpu_cores} vCPU, {ram_mb}MB RAM, {disk_gb}GB disk')

        # Define image candidates
        image_candidates = []
        if is_windows:
            if log_callback:
                log_callback('[INFO] Searching for locally-imported Windows VM image...')
            resolved_win = cls._resolve_windows_image(os_image)
            image_candidates.append(resolved_win)
            if log_callback:
                log_callback(f'[INFO] Found Windows image: {resolved_win}')
        elif os_image.startswith('ubuntu/'):
            version = os_image.split('/', 1)[1]
            image_candidates.append(f"ubuntu:{version}")
            image_candidates.append(f"images:ubuntu/{version}")
            # Codenames mapping
            codenames = {'22.04': 'jammy', '24.04': 'noble', '20.04': 'focal'}
            if version in codenames:
                image_candidates.append(f"ubuntu:{codenames[version]}")
                image_candidates.append(f"images:ubuntu/{codenames[version]}")
        else:
            image_candidates.append(f"images:{os_image}")
            if '/' in os_image:
                distro, version = os_image.split('/', 1)
                codenames = {
                    'debian/11': 'debian/bullseye',
                    'debian/12': 'debian/bookworm',
                    'centos/9-stream': 'centos/9-stream',
                    'alpine/3.18': 'alpine/3.18',
                }
                if os_image in codenames:
                    image_candidates.append(f"images:{codenames[os_image]}")

        # Try launching using candidate list
        launched = False
        last_error = ""
        for idx, source in enumerate(image_candidates):
            launch_cmd = ['lxc', 'launch', source, name]
            if is_windows:
                launch_cmd.append('--vm')
            
            if log_callback:
                log_callback(f'[INFO] Launching using image source: {source} (Attempt {idx+1}/{len(image_candidates)})')
            try:
                cls._run(launch_cmd)
                launched = True
                if log_callback:
                    log_callback(f'[SUCCESS] Successfully launched container using: {source}')
                break
            except subprocess.CalledProcessError as e:
                last_error = e.stderr.strip() if e.stderr else str(e)
                if log_callback:
                    log_callback(f'[WARNING] Source {source} failed: {last_error}')

        # Self-healing fallback: if launch failed, try to fix/update the remote URL in case images remote is blocked or misconfigured
        if not launched and not is_windows:
            if log_callback:
                log_callback('[INFO] Attempting auto-fix: Updating remote URL of images server...')
            try:
                cls._run(['lxc', 'remote', 'set-url', 'images', 'https://images.lxd.canonical.com/'])
                if log_callback:
                    log_callback('[INFO] Remote URL updated. Retrying launch candidates...')
                for source in image_candidates:
                    launch_cmd = ['lxc', 'launch', source, name]
                    try:
                        cls._run(launch_cmd)
                        launched = True
                        if log_callback:
                            log_callback(f'[SUCCESS] Launch succeeded after remote auto-fix using: {source}')
                        break
                    except subprocess.CalledProcessError as e2:
                        last_error = e2.stderr.strip() if e2.stderr else str(e2)
            except Exception as ex:
                if log_callback:
                    log_callback(f'[WARNING] Remote set-url auto-fix failed: {ex}')

        if not launched:
            raise Exception(f'Deployment step failed: Downloading and launching container image. Details: {last_error}')

        steps = [
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

        if is_windows:
            try:
                cls.set_windows_password(name, root_password, log_callback)
            except Exception as e:
                if log_callback:
                    log_callback(f'[WARNING] Could not pre-set Windows password (will be the build default): {e}')

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
                log_callback('[INFO] Configuring Windows VM (Administrator password, RDP, OpenSSH firewall)...')
            cls.set_windows_password(name, root_password, log_callback)
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
        """Sets root password inside the container. Uses PowerShell on Windows VMs."""
        if IS_MOCK_LXC:
            return True
        if cls._is_windows_container(name):
            return cls.set_windows_password(name, new_password)
        cls._run(['lxc', 'exec', name, '--', 'bash', '-c', f'echo root:{new_password} | chpasswd'])
        return True

    @classmethod
    def _is_windows_container(cls, name):
        """Detects whether a given container/VM is a Windows instance."""
        if IS_MOCK_LXC:
            return False
        try:
            out = cls._run(['lxc', 'list', name, '--format=csv', '-c', 't'])
            first_line = (out.splitlines() or [''])[0].strip().lower()
            return 'virtual-machine' in first_line
        except Exception:
            try:
                out = cls._run(['lxc', 'config', 'get', name, 'image.os'])
                return 'windows' in out.lower() or 'win' in out.lower()
            except Exception:
                return False

    @classmethod
    def set_windows_password(cls, name, new_password, log_callback=None):
        """Sets the Administrator password on a Windows VM using net user.

        Falls back to a Set-LocalUser PowerShell call. Re-enables Administrator
        and opens the OpenSSH/RDP firewall rules in the process.
        """
        if IS_MOCK_LXC:
            return True

        safe_pw = new_password.replace("'", "''").replace('"', '\\"')
        ps_script = (
            "$ErrorActionPreference = 'Stop'; "
            "try { "
            f"  $pw = ConvertTo-SecureString '{safe_pw}' -AsPlainText -Force; "
            "  Set-LocalUser -Name 'Administrator' -Password $pw -ErrorAction Stop; "
            "} catch { "
            f"  net user Administrator '{safe_pw}'; "
            "}; "
            "try { Set-LocalUser -Name 'Administrator' -PasswordNeverExpires $true -ErrorAction SilentlyContinue } catch {}; "
            "try { Get-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Enable-NetFirewallRule } catch {}; "
            "try { New-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -Direction Inbound -LocalPort 22 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue } catch {}; "
            "try { Set-Service -Name sshd -StartupType 'Automatic' -ErrorAction SilentlyContinue; Start-Service -Name sshd -ErrorAction SilentlyContinue } catch {}; "
            "try { Set-NetFirewallRule -DisplayGroup 'Remote Desktop' -Enabled True -ErrorAction SilentlyContinue } catch {}; "
            "try { New-NetFirewallRule -DisplayName 'Allow RDP 3389' -Direction Inbound -LocalPort 3389 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue } catch {}; "
            "try { Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name 'fDenyTSConnections' -Value 0 -ErrorAction SilentlyContinue } catch {}; "
            "Write-Host 'WINDOWS_PASSWORD_OK'"
        )
        max_attempts = 18
        for attempt in range(1, max_attempts + 1):
            try:
                if log_callback:
                    log_callback(f'[INFO] Configuring Windows VM (attempt {attempt}/{max_attempts})...')
                out = cls._run(
                    ['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
                    check=False
                )
                if 'WINDOWS_PASSWORD_OK' in out:
                    if log_callback:
                        log_callback('[INFO] Windows password set and firewall rules configured.')
                    return True
            except Exception as e:
                if log_callback:
                    log_callback(f'[INFO] Windows not ready yet ({e})')
            time.sleep(10)
        if log_callback:
            log_callback('[WARNING] Could not set Windows password automatically. Use the panel to retry, or RDP and run: net user Administrator <newpw>')
        return False

    @classmethod
    def import_windows_disk_image(cls, file_path, alias='windows/10', description=None,
                                  os_property='windows', progress_callback=None):
        """Imports a .vhd/.vhdx/.qcow2/.img/.iso file as a LXD image.

        Detects file format and uses the appropriate `lxc image import` command.
        For .iso, runs the unattended Windows installer build flow internally.

        Returns the imported alias name on success.
        """
        if IS_MOCK_LXC:
            return alias

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Image file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ('.vhd', '.vhdx', '.qcow2', '.img', '.raw', '.iso'):
            raise ValueError(f"Unsupported Windows image format: {ext}. Use .vhd, .vhdx, .qcow2, .img, .raw, or .iso")

        if progress_callback:
            progress_callback(f'Importing {os.path.basename(file_path)} as LXD image...')

        cmd = [LXC_BIN, 'image', 'import', file_path, '--alias', alias]
        if description:
            cmd.append(f'description={description}')
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1800)
        if result.returncode != 0:
            raise Exception(f"lxc image import failed: {result.stderr.strip() or result.stdout.strip()}")

        subprocess.run(
            [LXC_BIN, 'image', 'set-property', alias, 'os', os_property],
            capture_output=True, text=True, check=False
        )
        if progress_callback:
            progress_callback(f'Image imported and tagged with alias "{alias}".')
        return alias

    @classmethod
    def list_windows_images(cls):
        """Returns a list of available Windows image aliases."""
        if IS_MOCK_LXC:
            return ['windows/10', 'win10']
        out = []
        try:
            result = subprocess.run(
                [LXC_BIN, 'image', 'list', '--format=json'],
                capture_output=True, text=True, check=True, timeout=10
            )
            for img in json.loads(result.stdout):
                for alias in img.get('aliases', []):
                    name = alias.get('name', '').lower()
                    if name.startswith('windows') or name.startswith('win'):
                        out.append(alias.get('name'))
                        break
        except Exception as e:
            print(f"[!] list_windows_images error: {e}")
        return out

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

        # Disk usage via df inside container (Linux) or Get-PSDrive (Windows)
        used_disk = 0.0
        is_win = cls._is_windows_container(name)
        if status == 'running':
            if is_win:
                try:
                    ps_out = cls._run(
                        ['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive',
                         '-Command', "(Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | Measure-Object -Property Used -Sum).Sum / 1GB"],
                        check=False
                    )
                    val = re.sub(r'[^0-9.]', '', ps_out.strip().splitlines()[-1] if ps_out.strip() else '0')
                    if val:
                        used_disk = round(float(val), 1)
                except Exception:
                    pass
            else:
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

    # ─── FILE MANAGEMENT ─────────────────────────────────────────────────────────

    @classmethod
    def list_files(cls, name, path):
        """Lists files and directories at the given path inside the container."""
        if IS_MOCK_LXC:
            # Return dummy data for mock mode
            return [
                {"name": "test.txt", "type": "file", "size": 1024, "modified": time.time()},
                {"name": "folder", "type": "directory", "size": 4096, "modified": time.time()}
            ]
        
        is_win = cls._is_windows_container(name)
        if is_win:
            # Windows file listing
            ps_script = (
                f"$ErrorActionPreference = 'Stop'; "
                f"Get-ChildItem -Path '{path}' | "
                f"Select-Object Name, "
                f"@{{Name='Type';Expression={{if ($_.PSIsContainer) {{'directory'}} else {{'file'}} }}}}, "
                f"Length, "
                f"@{{Name='Modified';Expression={{[int][double]::Parse((Get-Date $_.LastWriteTime -UFormat %s))}} }} | "
                f"ConvertTo-Json -Compress"
            )
            try:
                out = cls._run(['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script])
                if out.strip():
                    items = json.loads(out)
                    if isinstance(items, dict):
                        items = [items]
                    res = []
                    for item in items:
                        res.append({
                            "name": item.get("Name"),
                            "type": item.get("Type"),
                            "size": item.get("Length") or 0,
                            "modified": item.get("Modified")
                        })
                    return res
                return []
            except Exception as e:
                raise Exception(f"Failed to list directory: {e}")
        else:
            # Linux file listing
            # Using find to get a parseable list: type|size|mtime|name
            # Maxdepth 1 ensures we only get the immediate children
            cmd = ['lxc', 'exec', name, '--', 'find', path, '-mindepth', '1', '-maxdepth', '1', '-printf', '%y|%s|%T@|%f\\n']
            try:
                out = cls._run(cmd)
                items = []
                for line in out.splitlines():
                    if not line.strip(): continue
                    parts = line.split('|', 3)
                    if len(parts) == 4:
                        ftype, fsize, fmtime, fname = parts
                        type_str = 'directory' if ftype == 'd' else 'file'
                        items.append({
                            "name": fname,
                            "type": type_str,
                            "size": int(fsize) if fsize.isdigit() else 0,
                            "modified": float(fmtime) if fmtime.replace('.', '', 1).isdigit() else 0
                        })
                return items
            except subprocess.CalledProcessError as e:
                # find command might fail if path doesn't exist
                raise Exception(f"Directory not found or access denied.")
            except Exception as e:
                raise Exception(f"Failed to list directory: {e}")

    @classmethod
    def read_file(cls, name, path):
        """Reads a file from the container."""
        if IS_MOCK_LXC:
            return "Mock file content for " + path
        try:
            # lxc file pull <container>/path -
            cmd = ['lxc', 'file', 'pull', f"{name}/{path}", '-']
            if IS_MOCK_LXC:
                return "Mock content"
            if cmd[0] == 'lxc':
                cmd = [LXC_BIN] + cmd[1:]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to read file: {e.stderr.strip() if e.stderr else 'Unknown error'}")

    @classmethod
    def write_file(cls, name, path, content):
        """Writes content to a file in the container."""
        if IS_MOCK_LXC:
            return True
        try:
            cmd = [LXC_BIN, 'file', 'push', '-', f"{name}/{path}"]
            # We need to pass content via stdin
            subprocess.run(cmd, input=content, text=True, capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to write file: {e.stderr.strip() if e.stderr else 'Unknown error'}")

    @classmethod
    def delete_file(cls, name, path):
        """Deletes a file or directory in the container."""
        if IS_MOCK_LXC:
            return True
        try:
            # lxc file delete supports both files and directories
            cmd = [LXC_BIN, 'file', 'delete', f"{name}/{path}"]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to delete: {e.stderr.strip() if e.stderr else 'Unknown error'}")

    @classmethod
    def create_directory(cls, name, path):
        """Creates a directory in the container."""
        if IS_MOCK_LXC:
            return True
        is_win = cls._is_windows_container(name)
        try:
            if is_win:
                ps_script = f"New-Item -ItemType Directory -Force -Path '{path}'"
                cls._run(['lxc', 'exec', name, '--', 'powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script])
            else:
                cls._run(['lxc', 'exec', name, '--', 'mkdir', '-p', path])
            return True
        except Exception as e:
            raise Exception(f"Failed to create directory: {e}")


