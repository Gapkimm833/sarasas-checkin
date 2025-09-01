from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)

# -------------------------
# ฟังก์ชันช่วยเชื่อม DB
# -------------------------
def init_db():
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT,
                    name TEXT,
                    date TEXT,
                    time TEXT,
                    status TEXT
                )''')
    conn.commit()
    conn.close()

# -------------------------
# หน้าแรก
# -------------------------
@app.route("/")
def home():
    today = datetime.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("SELECT student_id, name, date, time, status FROM attendance WHERE date=?", (today,))
    records = c.fetchall()
    conn.close()
    return render_template("index.html", today=today, records=records)

# -------------------------
# เช็คชื่อ (จากฟอร์ม)
# -------------------------
@app.route("/checkin", methods=["POST"])
def checkin():
    student_id = request.form["student_id"]
    name = request.form["name"]

    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M:%S")

    # เช็คว่าสายหรือไม่
    status = "มาเรียน"
    if now.strftime("%H:%M") > "08:35":
        status = "สาย"

    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("INSERT INTO attendance (student_id, name, date, time, status) VALUES (?,?,?,?,?)",
              (student_id, name, date, time, status))
    conn.commit()
    conn.close()

    return redirect(url_for("home"))

# -------------------------
# ลบข้อมูลทั้งหมดวันนี้
# -------------------------
@app.route("/reset")
def reset():
    today = datetime.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("DELETE FROM attendance WHERE date=?", (today,))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
