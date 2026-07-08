"""
server.py — VMC Attendance System Backend
Flask API server for RFID-based student attendance tracking.

Key fixes applied (2026-07):
  1. All DB rows converted to dicts via make_dict() which works for both
     sqlite3.Row and psycopg2 RealDictRow.
  2. delete_student now deletes child rows (attendance, sms_logs) BEFORE the
     parent (students) to satisfy the FK constraint and prevent delete failures.
  3. Error reporting in add_student passes the real server-side error message
     back to the client instead of a hard-coded RFID conflict message.
  4. ON DELETE CASCADE is already defined in database.py so the manual child
     deletes are a safety net only (they are kept for explicitness).
  5. PostgreSQL uses %s placeholders handled transparently via database._execute.
"""

import os
import json
from datetime import datetime

# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from database import get_db, init_db, USE_POSTGRES, _execute, _fetchone_dict, _fetchall_dict

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# Always ensure DB tables exist (uses CREATE TABLE IF NOT EXISTS — safe)
init_db()


# ── Row → dict helper ─────────────────────────────────────────────────────────

def make_dict(row):
    """Convert a DB row to a plain dict regardless of backend."""
    if row is None:
        return None
    return dict(row)


# ── Static / Frontend ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


@app.route('/api/debug/db', methods=['GET'])
def debug_db():
    conn = get_db()
    c = conn.cursor()
    try:
        # Check if we are running Postgres or SQLite
        if USE_POSTGRES:
            c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            tables = [r[0] for r in c.fetchall()]
            schemas = {}
            for t in tables:
                c.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{t}'")
                schemas[t] = [dict(name=r[0], type=r[1]) for r in c.fetchall()]
            return jsonify({"backend": "PostgreSQL", "tables": tables, "schemas": schemas})
        else:
            c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
            tables = [dict(r) for r in c.fetchall()]
            # Also get row counts for debugging
            counts = {}
            for t in tables:
                name = t['name']
                c.execute(f"SELECT COUNT(*) FROM {name}")
                counts[name] = c.fetchone()[0]
            return jsonify({"backend": "SQLite", "tables": tables, "counts": counts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/debug/delete/<id>', methods=['GET'])
def debug_delete(id):
    conn = get_db()
    c = conn.cursor()
    log = []
    sms_rows = []
    att_rows = []
    student_row = None
    try:
        if USE_POSTGRES:
            c.execute("SELECT * FROM sms_logs WHERE student_id=%s", (id,))
            sms_rows = [make_dict(r) for r in c.fetchall()]
            c.execute("SELECT * FROM attendance WHERE student_id=%s", (id,))
            att_rows = [make_dict(r) for r in c.fetchall()]
            c.execute("SELECT * FROM students WHERE id=%s", (id,))
            student_row = make_dict(c.fetchone())
            
            log.append("Deleting from sms_logs...")
            c.execute("DELETE FROM sms_logs WHERE student_id=%s", (id,))
            log.append("Deleting from attendance...")
            c.execute("DELETE FROM attendance WHERE student_id=%s", (id,))
            log.append("Deleting from students...")
            c.execute("DELETE FROM students WHERE id=%s", (id,))
        else:
            c.execute("SELECT * FROM sms_logs WHERE student_id=?", (id,))
            sms_rows = [make_dict(r) for r in c.fetchall()]
            c.execute("SELECT * FROM attendance WHERE student_id=?", (id,))
            att_rows = [make_dict(r) for r in c.fetchall()]
            c.execute("SELECT * FROM students WHERE id=?", (id,))
            student_row = make_dict(c.fetchone())
            
            log.append("Deleting from sms_logs...")
            c.execute("DELETE FROM sms_logs WHERE student_id=?", (id,))
            log.append("Deleting from attendance...")
            c.execute("DELETE FROM attendance WHERE student_id=?", (id,))
            log.append("Deleting from students...")
            c.execute("DELETE FROM students WHERE id=?", (id,))
            
        conn.commit()
        return jsonify({
            "success": True, 
            "log": log, 
            "student": student_row,
            "sms_rows": sms_rows, 
            "att_rows": att_rows
        })
    except Exception as e:
        conn.rollback()
        return jsonify({
            "success": False, 
            "log": log, 
            "error": str(e),
            "student": student_row,
            "sms_rows": sms_rows, 
            "att_rows": att_rows
        }), 500
    finally:
        conn.close()



# ── AUTH API ──────────────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    try:
        if USE_POSTGRES:
            c.execute('SELECT * FROM admin WHERE username=%s', (data.get('username'),))
        else:
            c.execute('SELECT * FROM admin WHERE username=?', (data.get('username'),))
        admin = make_dict(c.fetchone())
    finally:
        conn.close()

    if admin and admin['password'] == data.get('password'):
        return jsonify({"success": True, "token": "dummy-token-123", "role": "admin"})
    return jsonify({"success": False, "message": "Invalid credentials"}), 401


# ── STUDENTS API ──────────────────────────────────────────────────────────────

@app.route('/api/students', methods=['GET'])
def get_students():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('SELECT * FROM students')
        students = [make_dict(r) for r in c.fetchall()]
    finally:
        conn.close()

    for s in students:
        s['parentName']    = s.get('parent_name', '')
        s['parentContact'] = s.get('parent_contact', '')
    return jsonify(students)


@app.route('/api/students', methods=['POST'])
def add_student():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    required_fields = ['id', 'rfid', 'name', 'grade', 'section', 'parentName', 'parentContact']
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {missing}"}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        _execute(c, '''
            INSERT INTO students (id, rfid, name, grade, section, parent_name, parent_contact)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['id'], data['rfid'], data['name'],
            data['grade'], data['section'],
            data['parentName'], data['parentContact']
        ))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        error_str = str(e)
        print(f"[ERROR] add_student: {error_str}")
        # Provide a meaningful message for duplicate RFID vs other errors
        if 'unique' in error_str.lower() and 'rfid' in error_str.lower():
            user_msg = "An student with that RFID already exists. Please use a different RFID tag."
        elif 'unique' in error_str.lower() and 'id' in error_str.lower():
            user_msg = "A student with that ID already exists."
        else:
            user_msg = f"Database error: {error_str}"
        return jsonify({"success": False, "error": user_msg}), 400
    finally:
        conn.close()


@app.route('/api/students/<id>', methods=['PUT'])
def update_student(id):
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    try:
        _execute(c, '''
            UPDATE students
               SET rfid=?, name=?, grade=?, section=?, parent_name=?, parent_contact=?
             WHERE id=?
        ''', (
            data['rfid'], data['name'], data['grade'],
            data['section'], data['parentName'], data['parentContact'], id
        ))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        error_str = str(e)
        print(f"[ERROR] update_student: {error_str}")
        if 'unique' in error_str.lower() and 'rfid' in error_str.lower():
            user_msg = "That RFID tag is already assigned to another student."
        else:
            user_msg = f"Database error: {error_str}"
        return jsonify({"success": False, "error": user_msg}), 400
    finally:
        conn.close()


@app.route('/api/students/<id>', methods=['DELETE', 'OPTIONS'])
def delete_student(id):
    if request.method == 'OPTIONS':
        return jsonify({"success": True})

    print(f"[INFO] DELETE student id={id}")
    conn = get_db()
    c = conn.cursor()
    try:
        # ── CRITICAL FIX: delete child rows FIRST, then the parent ──────────
        # Deleting the parent row before children violates the FK constraint
        # (even with ON DELETE CASCADE, explicit ordering avoids race conditions).
        _execute(c, 'DELETE FROM sms_logs  WHERE student_id=?', (id,))
        _execute(c, 'DELETE FROM attendance WHERE student_id=?', (id,))
        _execute(c, 'DELETE FROM students  WHERE id=?',          (id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] delete_student: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/students/seed', methods=['POST'])
def seed_students():
    data = request.json
    if not data or not isinstance(data, list):
        return jsonify({"success": False, "error": "Expected a list of students"}), 400

    conn = get_db()
    c = conn.cursor()
    count = 0
    try:
        for s in data:
            try:
                _execute(c, '''
                    INSERT INTO students (id, rfid, name, grade, section, parent_name, parent_contact)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    s['id'], s['rfid'], s['name'],
                    s['grade'], s['section'],
                    s['parentName'], s['parentContact']
                ))
                count += 1
            except Exception as e:
                print(f"[SEED] Skipping duplicate: {e}")
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"success": True, "inserted": count})


# ── ATTENDANCE API ────────────────────────────────────────────────────────────

@app.route('/api/attendance', methods=['GET'])
def get_attendance():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('SELECT * FROM attendance ORDER BY timestamp DESC')
        records = [make_dict(r) for r in c.fetchall()]
    finally:
        conn.close()

    for r in records:
        r['studentId']   = r.get('student_id', '')
        r['studentName'] = r.get('student_name', '')
    return jsonify(records)


@app.route('/api/attendance/scan', methods=['POST'])
def create_scan():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    required = ['id', 'studentId', 'rfid', 'studentName', 'grade', 'section',
                'type', 'status', 'timestamp', 'date', 'smsMessage']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {missing}"}), 400

    if data['type'] not in ('IN', 'OUT'):
        return jsonify({"success": False, "error": "type must be IN or OUT"}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        # Insert attendance record
        _execute(c, '''
            INSERT INTO attendance
                (id, student_id, rfid, student_name, grade, section, type, status, timestamp, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['id'], data['studentId'], data['rfid'], data['studentName'],
            data['grade'], data['section'], data['type'], data['status'],
            data['timestamp'], data['date']
        ))

        # Insert SMS log
        sms_id = 'SMS' + str(int(datetime.now().timestamp() * 1000))
        _execute(c, '''
            INSERT INTO sms_logs
                (id, student_id, student_name, parent_contact, message, type, status, timestamp, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sms_id, data['studentId'], data['studentName'],
            data.get('parentContact', ''), data['smsMessage'],
            data['type'], data.get('smsStatus', 'Sent'),
            data['timestamp'], data['date']
        ))

        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] create_scan: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


# ── SMS API ───────────────────────────────────────────────────────────────────

@app.route('/api/sms', methods=['GET'])
def get_sms():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('SELECT * FROM sms_logs ORDER BY timestamp DESC')
        logs = [make_dict(r) for r in c.fetchall()]
    finally:
        conn.close()

    for l in logs:
        l['studentId']     = l.get('student_id', '')
        l['studentName']   = l.get('student_name', '')
        l['parentContact'] = l.get('parent_contact', '')
    return jsonify(logs)


@app.route('/api/sms/<id>/resend', methods=['POST'])
def resend_sms(id):
    conn = get_db()
    c = conn.cursor()
    try:
        new_timestamp = datetime.now().isoformat() + "Z"
        _execute(c,
            'UPDATE sms_logs SET status=?, timestamp=? WHERE id=?',
            ('Sent', new_timestamp, id))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


# ── SETTINGS API ──────────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('SELECT * FROM settings')
        settings = {row['key']: row['value'] for row in (make_dict(r) for r in c.fetchall())}
    finally:
        conn.close()
    return jsonify(settings)


@app.route('/api/settings', methods=['PUT'])
def update_settings():
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    try:
        for k, v in data.items():
            if USE_POSTGRES:
                # PostgreSQL upsert
                c.execute('''
                    INSERT INTO settings (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                ''', (k, str(v)))
            else:
                c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (k, str(v)))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/settings/password', methods=['POST'])
def change_password():
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    try:
        if USE_POSTGRES:
            c.execute('SELECT password FROM admin WHERE username=%s', ('admin',))
        else:
            c.execute('SELECT password FROM admin WHERE username=?', ('admin',))
        row = c.fetchone()

        if row is None:
            return jsonify({"success": False, "message": "Admin user not found"}), 404

        current_pass = row[0] if not USE_POSTGRES else row['password']

        if current_pass != data.get('current'):
            return jsonify({"success": False, "message": "Current password incorrect"}), 400

        _execute(c,
            'UPDATE admin SET password=? WHERE username=?',
            (data.get('new'), 'admin'))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/clear', methods=['POST'])
def clear_data():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('DELETE FROM sms_logs')
        c.execute('DELETE FROM attendance')
        c.execute('DELETE FROM students')
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] clear_data: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


# ── PARENT PORTAL API ─────────────────────────────────────────────────────────

@app.route('/api/parent/portal/<student_id>', methods=['GET'])
def parent_portal_data(student_id):
    conn = get_db()
    c = conn.cursor()
    try:
        if USE_POSTGRES:
            c.execute('SELECT * FROM students WHERE id=%s', (student_id,))
        else:
            c.execute('SELECT * FROM students WHERE id=?', (student_id,))
        student = make_dict(c.fetchone())
        if not student:
            return jsonify({"success": False, "error": "Student not found"}), 404

        student['parentName']    = student.get('parent_name', '')
        student['parentContact'] = student.get('parent_contact', '')

        if USE_POSTGRES:
            c.execute('SELECT * FROM attendance WHERE student_id=%s ORDER BY timestamp DESC', (student_id,))
        else:
            c.execute('SELECT * FROM attendance WHERE student_id=? ORDER BY timestamp DESC', (student_id,))
        attendance = [make_dict(r) for r in c.fetchall()]
    finally:
        conn.close()

    for r in attendance:
        r['studentId']   = r.get('student_id', '')
        r['studentName'] = r.get('student_name', '')

    return jsonify({"success": True, "student": student, "attendance": attendance})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
