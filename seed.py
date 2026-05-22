from werkzeug.security import generate_password_hash
from database import get_db_connection, init_db

def seed_database():
    # Make sure tables exist
    init_db()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Seed Admin User
    admin_username = 'admin'
    admin_email = 'admin@mintyhost.local'
    admin_pw = 'admin123'
    
    cursor.execute('SELECT * FROM users WHERE username = ?', (admin_username,))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash(admin_pw)
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)',
            (admin_username, admin_email, hashed_pw, 'admin')
        )
        print("Seeded default admin user.")
        
    # 2. Seed Client User
    client_username = 'client1'
    client_email = 'client1@mintyhost.local'
    client_pw = 'password123'
    
    cursor.execute('SELECT * FROM users WHERE username = ?', (client_username,))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash(client_pw)
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)',
            (client_username, client_email, hashed_pw, 'client')
        )
        print("Seeded default client user.")
        
    # 3. Seed Settings
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
        'tos_content': '<h3>1. Acceptance of Terms</h3><p>By deploying or using any Virtual Private Server (VPS) instance on MintyHost LXC, you agree to be bound by these Terms of Service. If you do not agree to these terms, you must not use our services.</p><h3>2. Dedicated Resource Allocation</h3><p>MintyHost guarantees that resources (CPU, RAM, storage) allocated to your VPS instances are dedicated solely to your use. Abuse of shared network pipes or attempting to disrupt host nodes will result in immediate suspension.</p><h3>3. Prohibited Activities</h3><p>You may not use MintyHost instances for illegal activities, including but not limited to: hosting malware, executing DDoS attacks, running unsolicited scanning tools, or mining cryptocurrencies without authorization.</p><h3>4. Limitation of Liability</h3><p>MintyHost is not liable for data loss or service interruptions. We strongly recommend configuring automatic snapshot rules and routine backups for production environments.</p>'
    }
    
    for key, value in default_settings.items():
        cursor.execute('SELECT * FROM settings WHERE key = ?', (key,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (key, value))
            print(f"Seeded setting: {key}")
            
    # 4. Seed initial audit log
    cursor.execute('SELECT COUNT(*) FROM logs')
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO logs (user_id, action) VALUES (1, 'System database initialized and seeded')"
        )
        print("Seeded initial audit log.")
        
    conn.commit()
    conn.close()
    print("Database seeding completed.")

if __name__ == '__main__':
    seed_database()
