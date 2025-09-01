from flask import Flask, render_template, request, redirect, send_file, url_for
import sqlite3
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

# ====== ตั้งค่า ======
TZ = ZoneInfo("Asia/Bangkok")
CUTOFF_HOUR = 8
CUTOFF_MINUTE = 35
DB_PATH = "attendance.db"


def compute_status(checkin_dt: datetime) -> str:
    cutoff = checkin_dt.replace(hour=CUTOFF_HOUR, minute=CUTOFF_MINUTE,
                                second=0, microsecond=0)
    return "Present" if checkin_dt <= cutoff else "Late"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                student_name TEXT NOT NULL,
                checkin_iso TEXT,
                checkin_date TEXT,
                checkin_time TEXT,
                status TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ====== Routes ======
@app.route("/")
def index():
    cutoff_str = f"{CUTOFF_HOUR:02d}:{CUTOFF_MINUTE:02d}"
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "SELECT student_id, student_name, checkin_date, checkin_time, status "
            "FROM attendance ORDER BY id DESC LIMIT 20", conn)
    finally:
        conn.close()
    records = df.to_dict(orient="records") if not df.empty else []
    return render_template("index.html",
                           records=records,
                           cutoff_str=cutoff_str,
                           today=today,
                           server_origin=request.host_url.strip("/"))


@app.route("/checkin", methods=["POST"])
def checkin():
    student_id = request.form.get("student_id", "").strip()
    student_name = request.form.get("student_name", "").strip()
    if not student_id or not student_name:
        return redirect("/")

    now = datetime.now(TZ)
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO attendance
              (student_id, student_name, checkin_iso, checkin_date, checkin_time, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            student_id,
            student_name,
            now.isoformat(timespec="seconds"),
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            compute_status(now),
        ))
        conn.commit()
    finally:
        conn.close()
    return redirect("/")


@app.route("/export")
def export():
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("""
            SELECT student_id AS รหัสนักเรียน,
                   student_name AS ชื่อ_นามสกุล,
                   checkin_date AS วันที่,
                   checkin_time AS เวลา,
                   status AS สถานะ,
                   checkin_iso AS เวลาเต็ม_ISO8601
            FROM attendance
            ORDER BY id ASC
        """, conn)
    finally:
        conn.close()

    file_path = "attendance_export.xlsx"
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True)


# ====== ปุ่มลบข้อมูล ======
@app.route("/clear_today", methods=["POST"])
def clear_today():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM attendance WHERE checkin_date = ?", (today,))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("index"))


@app.route("/clear_all", methods=["POST"])
def clear_all():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM attendance")
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("index"))


# ====== Main ======
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
