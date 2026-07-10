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

# Always ensure DB tables exist (idempotent) (uses CREATE TABLE IF NOT EXISTS — safe)
init_db()


# ── Row → dict helper ─────────────────────────────────────────────────────────

def make_dict(row):
    """
    Convert a DB row to a plain dict regardless of backend.
    sqlite3.Row: use .keys() — 'dict(row)' is unreliable across Python versions.
    psycopg2 row / plain dict: fall back to dict().
    """
    if row is None:
        return None
    # sqlite3.Row exposes .keys(); use explicit comprehension for safety
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    # psycopg2 RealDictRow or plain mapping
    return dict(row)


# ── Static / Frontend ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


# ── AUTH API ──────────────────────────────────────────────────────────────────


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    conn = get_db()
    c = conn.cursor()
    try:
        # ── 1. Try admin login ────────────────────────────────────────────────
        _execute(c, 'SELECT * FROM admin WHERE username=?', (username,))
        admin = make_dict(c.fetchone())
        if admin and admin.get('password') == password:
            conn.close()
            return jsonify({"success": True, "token": "dummy-token-123", "role": "admin"})

        # ── 2. Try parent login (Student ID + parent contact number) ──────────
        _execute(c, 'SELECT * FROM students WHERE id=?', (username,))
        student = make_dict(c.fetchone())
        if student and student.get('parent_contact') == password:
            conn.close()
            return jsonify({
                "success": True,
                "token": "parent-token-123",
                "role": "parent",
                "studentId": student['id']
            })

        conn.close()
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        print(f"[ERROR] login: {e}")
        return jsonify({"success": False, "error": str(e)}), 500



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


# ── SMART RFID SCAN (page-agnostic) ──────────────────────────────────────────
@app.route('/api/attendance/scan/rfid', methods=['POST'])
def smart_rfid_scan():
    """
    Accept a raw RFID code and perform ALL scan logic server-side:
      1. Look up student by rfid
      2. Determine IN vs OUT from today's attendance rows
      3. Compute status (On Time / Late) using settings.lateThreshold
      4. Build SMS message from settings template
      5. Insert attendance + sms_logs rows in one transaction
    Returns a rich result so the frontend can display feedback without
    needing students[], settings{}, or todayScans[] arrays in memory.
    """
    data = request.json or {}
    rfid_code = (data.get('rfid') or '').strip()
    if not rfid_code:
        return jsonify({"success": False, "error": "rfid is required"}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        # ── 1. Look up the student ────────────────────────────────────────────
        _execute(c, 'SELECT * FROM students WHERE rfid=?', (rfid_code,))
        student = make_dict(c.fetchone())
        if not student:
            return jsonify({
                "success": False,
                "error": "unknown_rfid",
                "message": f"No student registered for RFID: {rfid_code}"
            }), 404

        student_id   = student['id']
        student_name = student['name']
        grade        = student['grade']
        section      = student['section']
        parent_contact = student.get('parent_contact') or student.get('parentContact', '')

        # ── 2. Read settings (lateThreshold, templates, cooldown) ────────────
        c.execute('SELECT * FROM settings')
        raw_settings = {row['key']: row['value'] for row in (make_dict(r) for r in c.fetchall())}
        late_threshold  = raw_settings.get('lateThreshold',  '07:30')
        scan_cooldown_s = int(raw_settings.get('scanCooldown', '30'))
        tpl_in  = raw_settings.get('smsTemplateIn',  'Your child {name} has arrived at {time}.')
        tpl_out = raw_settings.get('smsTemplateOut', 'Your child {name} has left at {time}.')

        # ── 3. Determine IN vs OUT from today's records ───────────────────────
        now   = datetime.now(datetime.UTC).replace(tzinfo=None)   # naive UTC
        today = now.strftime('%Y-%m-%d')

        _execute(c,
            "SELECT type, timestamp FROM attendance WHERE student_id=? AND date=? ORDER BY timestamp DESC",
            (student_id, today))
        today_rows = [make_dict(r) for r in c.fetchall()]

        has_in  = any(r['type'] == 'IN'  for r in today_rows)
        has_out = any(r['type'] == 'OUT' for r in today_rows)

        if has_in and has_out:
            return jsonify({
                "success": False,
                "error": "already_recorded",
                "message": f"{student_name} has already scanned IN and OUT today."
            }), 409

        # ── 4. Cooldown guard (server-side) ───────────────────────────────────
        if today_rows:
            last_ts_str = today_rows[0]['timestamp']
            try:
                # Handle both 'Z' suffix and offset-naive ISO strings
                last_ts = datetime.fromisoformat(last_ts_str.replace('Z', '+00:00'))
                last_ts = last_ts.replace(tzinfo=None)   # compare naive
                elapsed = (now - last_ts).total_seconds()
                if elapsed < scan_cooldown_s:
                    remaining = int(scan_cooldown_s - elapsed)
                    return jsonify({
                        "success": False,
                        "error": "cooldown",
                        "message": f"Cooldown active. Please wait {remaining}s before scanning again."
                    }), 429
            except Exception:
                pass  # if parsing fails, skip cooldown check

        scan_type = 'OUT' if has_in else 'IN'

        # ── 5. Compute arrival status ─────────────────────────────────────────
        if scan_type == 'IN':
            lh, lm = map(int, late_threshold.split(':'))
            status = 'Late' if (now.hour > lh or (now.hour == lh and now.minute > lm)) else 'On Time'
        else:
            status = 'Departed'

        # ── 6. Build SMS message ──────────────────────────────────────────────
        time_str    = now.strftime('%I:%M %p')
        template    = tpl_in if scan_type == 'IN' else tpl_out
        sms_message = template.replace('{name}', student_name).replace('{time}', time_str)

        # ── 7. Insert records ─────────────────────────────────────────────────
        att_id  = 'ATT' + str(int(now.timestamp() * 1000))
        sms_id  = 'SMS' + str(int(now.timestamp() * 1000) + 1)
        ts_iso  = now.strftime('%Y-%m-%dT%H:%M:%SZ')

        _execute(c, '''
            INSERT INTO attendance
                (id, student_id, rfid, student_name, grade, section, type, status, timestamp, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (att_id, student_id, rfid_code, student_name, grade, section,
              scan_type, status, ts_iso, today))

        _execute(c, '''
            INSERT INTO sms_logs
                (id, student_id, student_name, parent_contact, message, type, status, timestamp, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (sms_id, student_id, student_name, parent_contact,
              sms_message, scan_type, 'Sent', ts_iso, today))

        conn.commit()
        print(f"[SCAN] {scan_type} — {student_name} ({rfid_code}) @ {ts_iso} [{status}]")

        return jsonify({
            "success":  True,
            "type":     scan_type,
            "status":   status,
            "student":  {
                "id":      student_id,
                "name":    student_name,
                "grade":   grade,
                "section": section,
                "rfid":    rfid_code,
            },
            "timestamp": ts_iso,
            "smsMessage": sms_message
        })

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] smart_rfid_scan: {e}")
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

        if USE_POSTGRES:
            c.execute('SELECT * FROM sms_logs WHERE student_id=%s ORDER BY timestamp DESC', (student_id,))
        else:
            c.execute('SELECT * FROM sms_logs WHERE student_id=? ORDER BY timestamp DESC', (student_id,))
        sms_logs = [make_dict(r) for r in c.fetchall()]
    finally:
        conn.close()

    for r in attendance:
        r['studentId']   = r.get('student_id', '')
        r['studentName'] = r.get('student_name', '')

    for l in sms_logs:
        l['studentId']   = l.get('student_id', '')
        l['studentName'] = l.get('student_name', '')

    return jsonify({
        "success": True,
        "student": student,
        "attendance": attendance,
        "sms_logs": sms_logs
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
