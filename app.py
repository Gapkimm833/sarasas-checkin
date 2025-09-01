import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, send_file, abort
from datetime import datetime
import pandas as pd

app = Flask(__name__)

# ===== RENDER/DEPLOY CONFIG =====
# Render จะยิงเข้ามาที่ตัวแปรแวดล้อม PORT
PORT = int(os.environ.get("PORT", 10000))

# ไฟล์ที่เซฟชั่วคราว (เช่น .xlsx) ให้ใช้ /tmp บนเซิร์ฟเวอร์
TMP_DIR = "/tmp"

# ===== DB CONFIG =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

def get_conn():
    # check_same_thread=False เพื่อให้ SQLite ใช้ได้ในสภาพ multi-threads ของเซิร์ฟเวอร์
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """สร้างตาราง attendance ถ้ายังไม่มี (แก้ปัญหา no such table: attendance)"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT NOT NULL
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_sid ON attendance(student_id);")
    conn.commit()
    conn.close()

# เรียกทันทีเมื่อเริ่มแอป (ทั้งตอนรันในเครื่องและบนเซิร์ฟเวอร์)
init_db()

# ===== ROUTES =====
@app.route("/", methods=["GET", "POST"])
def home():
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    # เมื่อกดบันทึกชื่อ
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        name = request.form.get("name", "").strip()
        if student_id and name:
            now = datetime.now()
            cur.execute(
                "INSERT INTO attendance (student_id, name, date, time, status) VALUES (?, ?, ?, ?, ?)",
                (student_id, name, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), "มาเรียน"),
            )
            conn.commit()

    # ดึงข้อมูลของวันนี้
    cur.execute(
        "SELECT student_id, name, date, time, status FROM attendance WHERE date=? ORDER BY time DESC",
        (today,),
    )
    rows = cur.fetchall()
    conn.close()

    return render_template("index.html", rows=rows, today=today)

@app.route("/delete_today")
def delete_today():
    """ลบข้อมูลเฉพาะวันนี้"""
    conn = get_conn()
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("DELETE FROM attendance WHERE date=?", (today,))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))

@app.route("/delete_all")
def delete_all():
    """ลบข้อมูลทั้งหมด"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    return redirect(url_for("home"))

@app.route("/export_excel")
def export_excel():
    """ดาวน์โหลดข้อมูลทั้งหมดเป็น Excel (บันทึกไฟล์ชั่วคราวที่ /tmp)"""
    try:
        conn = get_conn()
        df = pd.read_sql_query("SELECT * FROM attendance", conn)
        conn.close()

        os.makedirs(TMP_DIR, exist_ok=True)
        file_path = os.path.join(TMP_DIR, "students.xlsx")
        # ต้องติดตั้ง openpyxl ด้วย (อยู่ใน requirements.txt ข้างล่าง)
        df.to_excel(file_path, index=False)

        return send_file(file_path, as_attachment=True, download_name="students.xlsx")
    except Exception as e:
        # ป้องกันกรณีส่งไฟล์ไม่สำเร็จ
        return abort(500, description=str(e))

# health check สำหรับ Render (ไม่บังคับ แต่ช่วยดูสถานะได้)
@app.route("/healthz")
def healthz():
    return "ok", 200

# ===== START APP (สำหรับรันในเครื่อง) =====
if __name__ == "__main__":
    # บน Render จะใช้ gunicorn จาก Procfile ด้านล่าง ไม่เข้าบล็อคนี้
    app.run(host="0.0.0.0", port=PORT, debug=True)
