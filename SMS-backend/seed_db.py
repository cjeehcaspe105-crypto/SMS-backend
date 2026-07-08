"""
seed_db.py — VMC Attendance System
Seeds the vmc.db SQLite database with:
  - Initialised tables (via database.init_db)
  - 10 sample students (Grade 7-10, multiple sections)
  - 3 sample attendance/scan records per student
  - Linked SMS log entries for each scan

Run with:
  python seed_db.py
"""

import sys
import os
from datetime import datetime

# Ensure we can import database.py from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import init_db, get_db

# ─────────────────────────────────────────────
# 1. Ensure all tables exist + seed admin/settings
# ─────────────────────────────────────────────
init_db()
print("[OK] Tables initialized.")

# ─────────────────────────────────────────────
# 2. Sample Students
# ─────────────────────────────────────────────
STUDENTS = [
    {"id": "STU001", "rfid": "0007540001", "name": "Juan Dela Cruz",       "grade": "Grade 7",  "section": "St. Mark",   "parentName": "Maria Dela Cruz",    "parentContact": "09171234567"},
    {"id": "STU002", "rfid": "0007540002", "name": "Ana Reyes",            "grade": "Grade 7",  "section": "St. Mark",   "parentName": "Pedro Reyes",         "parentContact": "09181234568"},
    {"id": "STU003", "rfid": "0007540003", "name": "Carlos Santos",        "grade": "Grade 8",  "section": "St. Luke",   "parentName": "Elena Santos",        "parentContact": "09191234569"},
    {"id": "STU004", "rfid": "0007540004", "name": "Maria Garcia",         "grade": "Grade 8",  "section": "St. Luke",   "parentName": "Jose Garcia",         "parentContact": "09201234570"},
    {"id": "STU005", "rfid": "0007540005", "name": "Jose Mendoza",         "grade": "Grade 9",  "section": "St. John",   "parentName": "Rosa Mendoza",        "parentContact": "09211234571"},
    {"id": "STU006", "rfid": "0007540006", "name": "Luisa Torres",         "grade": "Grade 9",  "section": "St. John",   "parentName": "Ricardo Torres",      "parentContact": "09221234572"},
    {"id": "STU007", "rfid": "0007540007", "name": "Roberto Aquino",       "grade": "Grade 10", "section": "St. Matthew","parentName": "Carmen Aquino",       "parentContact": "09231234573"},
    {"id": "STU008", "rfid": "0007540008", "name": "Isabella Ramos",       "grade": "Grade 10", "section": "St. Matthew","parentName": "Fernando Ramos",      "parentContact": "09241234574"},
    {"id": "STU009", "rfid": "0007540009", "name": "Miguel Bautista",      "grade": "Grade 7",  "section": "St. Peter",  "parentName": "Clara Bautista",      "parentContact": "09251234575"},
    {"id": "STU010", "rfid": "0007540010", "name": "Sofia Villanueva",     "grade": "Grade 10", "section": "St. Peter",  "parentName": "Antonio Villanueva",  "parentContact": "09261234576"},
]

conn = get_db()
c = conn.cursor()

inserted_students = 0
for s in STUDENTS:
    try:
        c.execute(
            "INSERT INTO students (id, rfid, name, grade, section, parent_name, parent_contact) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (s["id"], s["rfid"], s["name"], s["grade"], s["section"], s["parentName"], s["parentContact"])
        )
        inserted_students += 1
    except Exception:
        pass  # Skip duplicates silently

conn.commit()
print(f"[OK] Students seeded: {inserted_students} new records added (duplicates skipped).")

# ─────────────────────────────────────────────
# 3. Sample Attendance Records + SMS Logs
# ─────────────────────────────────────────────
ATTENDANCE = []
SMS_LOGS   = []

base_dates = ["2026-03-15", "2026-03-16", "2026-03-17"]

for date in base_dates:
    for s in STUDENTS:
        ts_in  = f"{date}T06:45:00Z"
        ts_out = f"{date}T17:15:00Z"

        att_in_id  = f"ATT-{s['id']}-{date}-IN"
        att_out_id = f"ATT-{s['id']}-{date}-OUT"

        ATTENDANCE.append((
            att_in_id, s["id"], s["rfid"], s["name"], s["grade"], s["section"],
            "IN", "On Time", ts_in, date
        ))
        ATTENDANCE.append((
            att_out_id, s["id"], s["rfid"], s["name"], s["grade"], s["section"],
            "OUT", "Departed", ts_out, date
        ))

        sms_msg_in  = f"Good day! Your child {s['name']} has arrived at Villagers Montessori College at 06:45 AM. Thank you."
        sms_msg_out = f"Good day! Your child {s['name']} has left Villagers Montessori College at 05:15 PM. Thank you."

        SMS_LOGS.append((
            f"SMS-{s['id']}-{date}-IN",  s["id"], s["name"], s["parentContact"],
            sms_msg_in,  "IN",  "Sent", ts_in,  date
        ))
        SMS_LOGS.append((
            f"SMS-{s['id']}-{date}-OUT", s["id"], s["name"], s["parentContact"],
            sms_msg_out, "OUT", "Sent", ts_out, date
        ))

inserted_att = 0
for row in ATTENDANCE:
    try:
        c.execute(
            "INSERT INTO attendance (id, student_id, rfid, student_name, grade, section, type, status, timestamp, date) VALUES (?,?,?,?,?,?,?,?,?,?)",
            row
        )
        inserted_att += 1
    except Exception:
        pass

inserted_sms = 0
for row in SMS_LOGS:
    try:
        c.execute(
            "INSERT INTO sms_logs (id, student_id, student_name, parent_contact, message, type, status, timestamp, date) VALUES (?,?,?,?,?,?,?,?,?)",
            row
        )
        inserted_sms += 1
    except Exception:
        pass

conn.commit()
conn.close()

print(f"[OK] Attendance records seeded: {inserted_att} (duplicates skipped).")
print(f"[OK] SMS log records seeded:    {inserted_sms} (duplicates skipped).")
print("")
print("=" * 50)
print("  Database seeded successfully!")
print(f"  DB file: {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vmc.db')}")
print("=" * 50)
