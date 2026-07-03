import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        db_url = os.environ.get('LOCAL_DATABASE_URL')
    if not db_url:
        raise ValueError("Database URL not found.")
        
    if "postgres.render.com" in db_url and "?sslmode=require" not in db_url:
        db_url += "?sslmode=require"
        
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Admin Table (Using Postgres-native SERIAL primary key)
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # Students Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            rfid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            grade TEXT NOT NULL,
            section TEXT NOT NULL,
            parent_name TEXT NOT NULL,
            parent_contact TEXT NOT NULL
        )
    ''')

    # Attendance Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            rfid TEXT NOT NULL,
            student_name TEXT NOT NULL,
            grade TEXT NOT NULL,
            section TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    ''')

    # SMS Logs Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sms_logs (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            parent_contact TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    ''')

    # Settings Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Seed Admin if not exists (Postgres always uses %s placeholders)
    c.execute('SELECT COUNT(*) FROM admin')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO admin (username, password) VALUES (%s, %s)', ('admin', 'admin123'))

    # Seed default settings if empty
    c.execute('SELECT COUNT(*) FROM settings')
    if c.fetchone()[0] == 0:
        default_settings = [
            ('adminName', 'System Administrator'),
            ('adminEmail', 'admin@vmc.edu.ph'),
            ('smsSenderName', 'VMC ALERT'),
            ('smsTemplateIn', 'Good day! Your child {name} has arrived at Villagers Montessori College at {time}. Thank you.'),
            ('smsTemplateOut', 'Good day! Your child {name} has left Villagers Montessori College at {time}. Thank you.'),
            ('scanCooldown', '30'),
            ('lateThreshold', '07:30'),
            ('schoolStart', '06:00'),
            ('schoolEnd', '18:00')
        ]
        c.executemany('INSERT INTO settings (key, value) VALUES (%s, %s)', default_settings)

    conn.commit()
    c.close()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
