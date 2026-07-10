"""
database.py — VMC Attendance System
Dual-mode database layer:
  • Production (Render/cloud): PostgreSQL via DATABASE_URL environment variable.
  • Development (local):        SQLite fallback (vmc.db in the same directory).

All public helpers return a connection object whose cursor supports dict-like
row access (sqlite3.Row / RealDictCursor).
"""

import os
import sqlite3

# ── Try to import psycopg2; it's optional for local dev ──────────────────────
try:
    import psycopg2
    import psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

# ── Resolve which backend to use ─────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Render (and Heroku) may provide "postgres://…" — psycopg2 needs "postgresql://…"
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

USE_POSTGRES = HAS_PG and bool(DATABASE_URL)

# Local SQLite path (only used when USE_POSTGRES is False)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vmc.db')


# ── Public helpers ────────────────────────────────────────────────────────────

def get_db():
    """
    Return an open database connection.

    PostgreSQL: every call opens a fresh connection from the pool-less
    psycopg2 driver (Render's connection limit is generous enough for this
    small-scale app; swap for psycopg2.pool if needed).

    SQLite: opens the local vmc.db with WAL journal mode and FK enforcement.
    """
    if USE_POSTGRES:
        # RealDictCursor makes every fetchone/fetchall return a dict-like
        # RealDictRow (has .keys() + row[col_name]) instead of a plain tuple.
        conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        conn.autocommit = False          # explicit transaction control
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')   # enforce FK constraints
        conn.execute('PRAGMA journal_mode = WAL')   # better concurrent access
        return conn


def _placeholder():
    """Return the correct parameter placeholder for the active backend."""
    return '%s' if USE_POSTGRES else '?'


def _execute(cursor, sql, params=()):
    """
    Execute *sql* with *params*, adapting the placeholder style
    (%s for PostgreSQL, ? for SQLite) automatically.
    """
    if USE_POSTGRES:
        sql = sql.replace('?', '%s')
    cursor.execute(sql, params)


def _executemany(cursor, sql, params_list):
    if USE_POSTGRES:
        sql = sql.replace('?', '%s')
    cursor.executemany(sql, params_list)



def _row_to_dict(row):
    """Safely convert any DB row to a plain dict regardless of Python version."""
    if row is None:
        return None
    # sqlite3.Row and psycopg2 RealDictRow both expose .keys()
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    # Plain tuple (psycopg2 default cursor) — fall back
    return dict(row)


def _fetchone_dict(cursor):
    """Return the next row as a plain dict (works for both backends)."""
    return _row_to_dict(cursor.fetchone())


def _fetchall_dict(cursor):
    return [_row_to_dict(r) for r in cursor.fetchall()]


# ── Schema initialisation ─────────────────────────────────────────────────────

def _get_count(row):
    """
    Safely extract a count from a database row.
    Supports both Postgres (RealDictRow) and SQLite (Row/tuple).
    Expects the SQL query to use 'as count'.
    """
    if row is None:
        return 0
    if hasattr(row, 'keys'):
        if 'count' in row.keys():
            return row['count']
        return row[0] if len(row) > 0 else 0
    return row[0] if len(row) > 0 else 0


def init_db():
    conn = get_db()
    c = conn.cursor()

    if USE_POSTGRES:
        # ── Admin ────────────────────────────────────────────────────────────
        c.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id       SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        # ── Students ─────────────────────────────────────────────────────────
        c.execute('''
            CREATE TABLE IF NOT EXISTS students (
                id             TEXT PRIMARY KEY,
                rfid           TEXT UNIQUE NOT NULL,
                name           TEXT NOT NULL,
                grade          TEXT NOT NULL,
                section        TEXT NOT NULL,
                parent_name    TEXT NOT NULL,
                parent_contact TEXT NOT NULL
            )
        ''')

        # ── Attendance ───────────────────────────────────────────────────────
        # ON DELETE CASCADE so deleting a student auto-removes their logs.
        c.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id           TEXT PRIMARY KEY,
                student_id   TEXT NOT NULL,
                rfid         TEXT NOT NULL,
                student_name TEXT NOT NULL,
                grade        TEXT NOT NULL,
                section      TEXT NOT NULL,
                type         TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                status       TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                date         TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')

        # ── SMS Logs ─────────────────────────────────────────────────────────
        c.execute('''
            CREATE TABLE IF NOT EXISTS sms_logs (
                id             TEXT PRIMARY KEY,
                student_id     TEXT NOT NULL,
                student_name   TEXT NOT NULL,
                parent_contact TEXT NOT NULL,
                message        TEXT NOT NULL,
                type           TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                status         TEXT NOT NULL,
                timestamp      TEXT NOT NULL,
                date           TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')

        # ── Settings ─────────────────────────────────────────────────────────
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

    else:
        # SQLite schema (identical structure, different serial syntax)
        c.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS students (
                id             TEXT PRIMARY KEY,
                rfid           TEXT UNIQUE NOT NULL,
                name           TEXT NOT NULL,
                grade          TEXT NOT NULL,
                section        TEXT NOT NULL,
                parent_name    TEXT NOT NULL,
                parent_contact TEXT NOT NULL
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id           TEXT PRIMARY KEY,
                student_id   TEXT NOT NULL,
                rfid         TEXT NOT NULL,
                student_name TEXT NOT NULL,
                grade        TEXT NOT NULL,
                section      TEXT NOT NULL,
                type         TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                status       TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                date         TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS sms_logs (
                id             TEXT PRIMARY KEY,
                student_id     TEXT NOT NULL,
                student_name   TEXT NOT NULL,
                parent_contact TEXT NOT NULL,
                message        TEXT NOT NULL,
                type           TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                status         TEXT NOT NULL,
                timestamp      TEXT NOT NULL,
                date           TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

    # ── Seed admin ───────────────────────────────────────────────────────────
    _execute(c, 'SELECT COUNT(*) as count FROM admin')
    row = c.fetchone()
    count = _get_count(row)
    if count == 0:
        _execute(c,
            'INSERT INTO admin (username, password) VALUES (?, ?)',
            ('admin', 'admin123'))

    # ── Seed default settings ────────────────────────────────────────────────
    _execute(c, 'SELECT COUNT(*) as count FROM settings')
    row = c.fetchone()
    count = _get_count(row)
    if count == 0:
        default_settings = [
            ('adminName',       'System Administrator'),
            ('adminEmail',      'admin@vmc.edu.ph'),
            ('smsSenderName',   'VMC ALERT'),
            ('smsTemplateIn',   'Good day! Your child {name} has arrived at Villagers Montessori College at {time}. Thank you.'),
            ('smsTemplateOut',  'Good day! Your child {name} has left Villagers Montessori College at {time}. Thank you.'),
            ('scanCooldown',    '30'),
            ('lateThreshold',   '07:30'),
            ('schoolStart',     '06:00'),
            ('schoolEnd',       '18:00'),
        ]
        _executemany(c,
            'INSERT INTO settings (key, value) VALUES (?, ?)',
            default_settings)

    conn.commit()
    conn.close()
    print(f"[DB] Initialised — backend: {'PostgreSQL' if USE_POSTGRES else 'SQLite'}")

