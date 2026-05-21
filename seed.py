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
        'color_cool': '#93BFC7'
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
