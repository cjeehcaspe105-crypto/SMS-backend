import os
import json
from datetime import datetime
# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from database import get_db, init_db

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# Always ensure DB tables exist (init_db uses CREATE TABLE IF NOT EXISTS, safe to call always)
init_db()

def make_dict(row):
    return dict(row)

# Serve Frontend Files
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# --- AUTH API ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM admin WHERE username=?', (data.get('username'),))
    admin = c.fetchone()
    conn.close()
    
    if admin and admin['password'] == data.get('password'):
        return jsonify({"success": True, "token": "dummy-token-123", "role": "admin"})
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

# --- STUDENTS API ---
@app.route('/api/students', methods=['GET'])
def get_students():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM students')
    students = [make_dict(r) for r in c.fetchall()]
    conn.close()
    
    for s in students:
        s['parentName'] = s['parent_name']
        s['parentContact'] = s['parent_contact']
        
    return jsonify(students)

@app.route('/api/students', methods=['POST'])
def add_student():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400
    conn = get_db()
    c = conn.cursor()
    error_msg = None
    try:
        c.execute('''
            INSERT INTO students (id, rfid, name, grade, section, parent_name, parent_contact)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (data['id'], data['rfid'], data['name'], data['grade'], data['section'], data['parentName'], data['parentContact']))
        conn.commit()
        success = True
    except Exception as e:
        success = False
        error_msg = str(e)
        print(f"Error adding student: {e}")
    finally:
        conn.close()
    if not success:
        return jsonify({"success": False, "error": error_msg}), 400
    return jsonify({"success": True})

@app.route('/api/students/<id>', methods=['PUT'])
def update_student(id):
    data = request.json
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''
            UPDATE students SET rfid=?, name=?, grade=?, section=?, parent_name=?, parent_contact=?
            WHERE id=?
        ''', (data['rfid'], data['name'], data['grade'], data['section'], data['parentName'], data['parentContact'], id))
        conn.commit()
        success = True
        error_msg = None
    except Exception as e:
        success = False
        error_msg = str(e)
    finally:
        conn.close()
    if not success:
        return jsonify({"success": False, "error": error_msg}), 400
    return jsonify({"success": True})

@app.route('/api/students/<id>', methods=['DELETE', 'OPTIONS'])
def delete_student(id):
    if request.method == 'OPTIONS':
        return jsonify({"success": True})
    print(f"DELETE STUDENT HIT FOR ID: {id}")
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM students WHERE id=?', (id,))
        # Also cascade delete
        c.execute('DELETE FROM attendance WHERE student_id=?', (id,))
        c.execute('DELETE FROM sms_logs WHERE student_id=?', (id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"success": True})

@app.route('/api/students/seed', methods=['POST'])
def seed_students():
    data = request.json
    if not data or not isinstance(data, list):
        return jsonify({"success": False, "error": "Expected a list of students"}), 400
    conn = get_db()
    c = conn.cursor()
    count = 0
    for s in data:
        try:
            c.execute('''
                INSERT INTO students (id, rfid, name, grade, section, parent_name, parent_contact)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (s['id'], s['rfid'], s['name'], s['grade'], s['section'], s['parentName'], s['parentContact']))
            count += 1
        except Exception as e:
            print(f"Seed skip (duplicate?): {e}")
    conn.commit()
    conn.close()
    return jsonify({"success": True, "inserted": count})

# --- ATTENDANCE & SMS API ---
@app.route('/api/attendance', methods=['GET'])
def get_attendance():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM attendance ORDER BY timestamp DESC')
    records = [make_dict(r) for r in c.fetchall()]
    conn.close()
    # rename fields to match JS expectations if needed
    for r in records:
        r['studentId'] = r['student_id']
        r['studentName'] = r['student_name']
    return jsonify(records)

@app.route('/api/attendance/scan', methods=['POST'])
def create_scan():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    # Validate required fields
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
        # Insert Attendance
        c.execute('''
            INSERT INTO attendance (id, student_id, rfid, student_name, grade, section, type, status, timestamp, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['id'], data['studentId'], data['rfid'], data['studentName'],
            data['grade'], data['section'], data['type'], data['status'],
            data['timestamp'], data['date']
        ))

        # Insert SMS Log
        sms_id = 'SMS' + str(int(datetime.now().timestamp() * 1000))
        c.execute('''
            INSERT INTO sms_logs (id, student_id, student_name, parent_contact, message, type, status, timestamp, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sms_id, data['studentId'], data['studentName'], data.get('parentContact', ''),
            data['smsMessage'], data['type'], data.get('smsStatus', 'Sent'),
            data['timestamp'], data['date']
        ))

        conn.commit()
    except Exception as e:
        print(f"Error in create_scan: {e}")
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"success": True})

@app.route('/api/sms', methods=['GET'])
def get_sms():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM sms_logs ORDER BY timestamp DESC')
    logs = [make_dict(r) for r in c.fetchall()]
    conn.close()
    for l in logs:
        l['studentId'] = l['student_id']
        l['studentName'] = l['student_name']
        l['parentContact'] = l['parent_contact']
    return jsonify(logs)

@app.route('/api/sms/<id>/resend', methods=['POST'])
def resend_sms(id):
    conn = get_db()
    c = conn.cursor()
    new_timestamp = datetime.now().isoformat() + "Z"
    c.execute('UPDATE sms_logs SET status=?, timestamp=? WHERE id=?', ('Sent', new_timestamp, id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# --- SETTINGS API ---
@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM settings')
    settings = {r['key']: r['value'] for r in c.fetchall()}
    conn.close()
    return jsonify(settings)

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    for k, v in data.items():
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (k, str(v)))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/settings/password', methods=['POST'])
def change_password():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT password FROM admin WHERE username=?', ('admin',))
    row = c.fetchone()

    if row is None:
        conn.close()
        return jsonify({"success": False, "message": "Admin user not found"}), 404

    current_pass = row[0]

    if current_pass != data.get('current'):
        conn.close()
        return jsonify({"success": False, "message": "Current password incorrect"}), 400

    c.execute('UPDATE admin SET password=? WHERE username=?', (data.get('new'), 'admin'))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/clear', methods=['POST'])
def clear_data():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('DELETE FROM sms_logs')
        c.execute('DELETE FROM attendance')
        c.execute('DELETE FROM students')
        conn.commit()
    except Exception as e:
        print(f"Error clearing data: {e}")
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 500
    conn.close()
    return jsonify({"success": True})

# --- PARENT PORTAL API ---
@app.route('/api/parent/portal/<student_id>', methods=['GET'])
def parent_portal_data(student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM students WHERE id=?', (student_id,))
    student_row = c.fetchone()
    if not student_row:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404
        
    student = make_dict(student_row)
    student['parentName'] = student['parent_name']
    student['parentContact'] = student['parent_contact']
    
    c.execute('SELECT * FROM attendance WHERE student_id=? ORDER BY timestamp DESC', (student_id,))
    attendance = [make_dict(r) for r in c.fetchall()]
    conn.close()
    
    for r in attendance:
        r['studentId'] = r['student_id']
        r['studentName'] = r['student_name']
        
    return jsonify({
        "success": True,
        "student": student,
        "attendance": attendance
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
