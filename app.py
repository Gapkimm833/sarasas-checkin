import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, send_file
from datetime import datetime
import pandas as pd

app = Flask(__name__)

# ===== DB CONFIG =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """สร้างตาราง attendance ถ้ายังไม่มี"""
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


# เรียกทันทีเมื่อเริ่มแอป
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
    """ดาวน์โหลดข้อมูลทั้งหมดเป็น Excel"""
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM attendance", conn)
    conn.close()
    file_path = os.path.join(BASE_DIR, "students.xlsx")
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True)


# ===== START APP =====
if __name__ == "__main__":
    app.run(debug=True)
