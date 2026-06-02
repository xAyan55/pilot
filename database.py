import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mintyhost.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'client', -- 'admin' or 'client'
            pfp TEXT DEFAULT NULL
        )
    ''')

    # Migration to add pfp to users table if it does not exist
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN pfp TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # Nodes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            fqdn TEXT NOT NULL,
            port INTEGER DEFAULT 5001,
            location TEXT,
            api_key TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'offline',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # VPS Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            container_name TEXT UNIQUE NOT NULL,
            os TEXT NOT NULL,
            cpu INTEGER NOT NULL,
            ram INTEGER NOT NULL,
            disk INTEGER NOT NULL,
            root_password TEXT NOT NULL,
            status TEXT DEFAULT 'stopped',
            node_id INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE SET DEFAULT
        )
    ''')

    # Migration to add node_id to vps table if it does not exist
    try:
        cursor.execute("ALTER TABLE vps ADD COLUMN node_id INTEGER DEFAULT 1 REFERENCES nodes(id)")
    except sqlite3.OperationalError:
        pass

    # Migration to add tunnel_port to vps table if it does not exist
    try:
        cursor.execute("ALTER TABLE vps ADD COLUMN tunnel_port INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # Migration to add tunnel_host to vps table if it does not exist
    try:
        cursor.execute("ALTER TABLE vps ADD COLUMN tunnel_host TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # Logs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    ''')

    # Snapshots Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vps_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vps_id) REFERENCES vps(id) ON DELETE CASCADE
        )
    ''')

    # Backups Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vps_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            size TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vps_id) REFERENCES vps(id) ON DELETE CASCADE
        )
    ''')

    # Firewall Rules Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS firewall_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vps_id INTEGER NOT NULL,
            protocol TEXT NOT NULL, -- 'TCP', 'UDP', 'ICMP'
            port INTEGER NOT NULL,  -- 0 for all/ICMP
            action TEXT NOT NULL,   -- 'ALLOW' or 'DENY'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vps_id) REFERENCES vps(id) ON DELETE CASCADE
        )
    ''')

    # Settings Table (Branding and site-wide state variables)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # VPS Plans Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vps_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            price_credits INTEGER NOT NULL,
            ram TEXT NOT NULL,
            cpu TEXT NOT NULL,
            storage TEXT NOT NULL,
            bandwidth TEXT NOT NULL
        )
    ''')

    # FAQ Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL
        )
    ''')

    # Auto-seed settings if empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        default_settings = {
            'site_name': 'MintyHost LXC',
            'color_primary': '#ECF4E8',
            'color_secondary': '#CBF3BB',
            'color_accent': '#ABE7B2',
            'color_cool': '#93BFC7',
            'about_intro': 'MintyHost was founded in 2026 with a single, clear objective: to provide developers with lightning-fast, ultra-reliable virtualized instances without the bloat, complexity, and resource-overselling typical of large cloud providers. We believe in simplicity, performance, and complete developer control.',
            'about_mission': 'To democratize high-performance containerized VPS hosting by offering raw power, transparent pricing, and instant provisioning speeds on pure, dedicated hardware platforms.',
            'about_infra': 'Our hypervisors run on enterprise AMD EPYC processors, coupled with high-speed PCIe Gen4 NVMe storage arrays. We route traffic through multi-homed 10 Gbps uplinks directly to Tier III datacenters.',
            'about_why_trust': 'Every byte of RAM and CPU thread you allocate is dedicated to your container. We enforce zero overselling. Combined with our 24/7 hypervisor monitoring and automatic backup engines, your workloads remain secure and highly performant.',
            'tos_content': '<h3>1. Acceptance of Terms</h3><p>By deploying or using any Virtual Private Server (VPS) instance on MintyHost LXC, you agree to be bound by these Terms of Service. If you do not agree to these terms, you must not use our services.</p><h3>2. Dedicated Resource Allocation</h3><p>MintyHost guarantees that resources (CPU, RAM, storage) allocated to your VPS instances are dedicated solely to your use. Abuse of shared network pipes or attempting to disrupt host nodes will result in immediate suspension.</p><h3>3. Prohibited Activities</h3><p>You may not use MintyHost instances for illegal activities, including but not limited to: hosting malware, executing DDoS attacks, running unsolicited scanning tools, or mining cryptocurrencies without authorization.</p><h3>4. Limitation of Liability</h3><p>MintyHost is not liable for data loss or service interruptions. We strongly recommend configuring automatic snapshot rules and routine backups for production environments.</p>',
            'ssh_relay_enabled': '0',
            'ssh_relay_host': '',
            'ssh_relay_port': '22',
            'ssh_relay_user': '',
            'ssh_relay_password': '',
            'ssh_relay_ports': ''
        }
        for k, v in default_settings.items():
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
        print("Auto-seeded default settings.")

    # Auto-seed vps_plans if empty
    cursor.execute("SELECT COUNT(*) FROM vps_plans")
    if cursor.fetchone()[0] == 0:
        default_plans = [
            ('Starter VPS', 5.00, 500, '2 GB', '1 Core', '40 GB', '2 TB'),
            ('Pro VPS', 15.00, 1500, '4 GB', '2 Cores', '80 GB', '4 TB'),
            ('Elite VPS', 30.00, 3000, '8 GB', '4 Cores', '160 GB', '8 TB')
        ]
        for plan in default_plans:
            cursor.execute(
                "INSERT INTO vps_plans (name, price, price_credits, ram, cpu, storage, bandwidth) VALUES (?, ?, ?, ?, ?, ?, ?)",
                plan
            )
        print("Auto-seeded default plans.")

    # Auto-seed faqs if empty
    cursor.execute("SELECT COUNT(*) FROM faqs")
    if cursor.fetchone()[0] == 0:
        default_faqs = [
            ("What virtualization technology do you use?", "We leverage Linux Containers (LXC) and KVM technologies to ensure high-performance, isolated virtual environments with native-like execution speed."),
            ("Is the resource allocation dedicated or shared?", "All resource limits (RAM, CPU, and Disk space) specified in your plan are 100% dedicated to your container. We enforce a strict non-overselling policy."),
            ("How fast is container provisioning?", "Once a container is deployed by an administrator, it boots up and becomes accessible in less than 55 seconds."),
            ("Can I manage snapshots and backups?", "Yes, you can create on-demand snapshots, restore container states, and export full container tarball backups directly from your client control panel."),
            ("What operating systems are supported?", "We support Ubuntu 22.04/24.04 LTS, Debian 11/12, CentOS 9 Stream, Alpine 3.18, and Windows 10/11 (admin must pre-build a Windows image via the admin panel or by running bash /var/www/lxc/setup_windows_image.sh on the LXD host). You can reinstall or switch your OS at any time from the dashboard.")
        ]
        for faq in default_faqs:
            cursor.execute("INSERT INTO faqs (question, answer) VALUES (?, ?)", faq)
        print("Auto-seeded default FAQs.")

    # API Keys Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            key TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Migration: add last_used column if missing
    try:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN last_used TIMESTAMP DEFAULT NULL")
    except Exception:
        pass

    # Auto-seed default local node if empty
    cursor.execute("SELECT COUNT(*) FROM nodes")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO nodes (id, name, fqdn, port, location, api_key, status) VALUES (1, 'Local Node', '127.0.0.1', 5000, 'Local Panel Server', 'local-api-key', 'online')"
        )
        print("Auto-seeded default local node.")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("LXC Panel database schema initialized successfully.")
