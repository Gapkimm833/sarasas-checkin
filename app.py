import os
import io
import sqlite3
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, abort, make_response, flash
)
import pandas as pd
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")  # สำหรับ flash message

# ===== CONFIG =====
PORT = int(os.environ.get("PORT", 10000))
TMP_DIR = "/tmp"

# เวลา “ตัดมาสาย” (ชั่วโมง:นาที) ปรับได้ผ่าน ENV: CUT_OFF="08:35"
CUT_OFF = os.environ.get("CUT_OFF", "08:35")
CUTOFF_H, CUTOFF_M = [int(x) for x in CUT_OFF.split(":")]

# DB (ถ้าใช้ Render Disk ให้ตั้ง ENV: DB_DIR=/var/data)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.environ.get("DB_DIR", BASE_DIR)
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "attendance.db")


# ===== DB UTILS =====
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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

# สำคัญ: ให้สร้างตารางทุกครั้งที่แอปเริ่ม (รองรับ gunicorn/Render)
init_db()


# ===== HELPERS =====
def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_today_token():
    # ใช้ใน QR เป็นโทเค็นของวันนั้น (YYYYMMDD)
    return datetime.now().strftime("%Y%m%d")

def calc_status(now: datetime) -> str:
    # คืนค่า "มาเรียน" หรือ "มาสาย"
    if (now.hour, now.minute) > (CUTOFF_H, CUTOFF_M):
        return "มาสาย"
    return "มาเรียน"

def _make_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ===== ROUTES: WEB UI =====
@app.route("/", methods=["GET", "POST"])
def home():
    conn = get_conn()
    cur = conn.cursor()

    today = get_today_str()

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        name = request.form.get("name", "").strip()
        if student_id and name:
            now = datetime.now()
            cur.execute(
                "INSERT INTO attendance (student_id, name, date, time, status) VALUES (?, ?, ?, ?, ?)",
                (student_id, name, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), calc_status(now)),
            )
            conn.commit()
            flash("บันทึกสำเร็จ", "success")

    cur.execute(
        "SELECT student_id, name, date, time, status FROM attendance WHERE date=? ORDER BY time DESC",
        (today,),
    )
    rows = cur.fetchall()
    conn.close()

    # token ของวันนี้ (ใช้ฝังใน QR)
    token = get_today_token()
    return render_template("index.html", rows=rows, today=today, token=token, cutoff=CUT_OFF)

@app.route("/delete_today")
def delete_today():
    conn = get_conn()
    cur = conn.cursor()
    today = get_today_str()
    cur.execute("DELETE FROM attendance WHERE date=?", (today,))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))

@app.route("/delete_all")
def delete_all():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    return redirect(url_for("home"))

@app.route("/export_excel")
def export_excel():
    try:
        conn = get_conn()
        df = pd.read_sql_query("SELECT * FROM attendance", conn)
        conn.close()

        os.makedirs(TMP_DIR, exist_ok=True)
        file_path = os.path.join(TMP_DIR, "students.xlsx")
        df.to_excel(file_path, index=False)

        return send_file(file_path, as_attachment=True, download_name="students.xlsx")
    except Exception as e:
        return abort(500, description=str(e))

@app.route("/healthz")
def healthz():
    return "ok", 200


# ===== ROUTES: QR + MOBILE CHECK-IN =====
@app.route("/qr")
def qr_code():
    """
    ส่งภาพ PNG เป็น QR
    - ถ้าไม่มีพารามิเตอร์ text จะสร้าง QR ชี้ไปที่ /checkin?t=<YYYYMMDD>
    - ถ้าใส่ text=... จะ encode ตามนั้น (ยืดหยุ่น)
    """
    default_checkin = f"{request.url_root}checkin?t={get_today_token()}"
    text = request.args.get("text", default_checkin)
    png = _make_qr_png(text)
    resp = make_response(png)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    """
    หน้าเช็คอินแบบมือถือ:
    - GET: แสดงฟอร์ม (ต้องมี t=YYYYMMDD) ถ้าวันไม่ตรง/หมดอายุจะแจ้งเตือน
    - POST: รับ student_id, name + token แล้วบันทึก พร้อมคำนวณ 'มาสาย' อัตโนมัติ
    """
    token = request.values.get("t", "")
    today_token = get_today_token()
    token_valid = (token == today_token)

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        name = request.form.get("name", "").strip()
        if not token_valid:
            msg = "QR หมดอายุหรือไม่ถูกต้อง"
            return render_template("checkin.html", ok=False, msg=msg, token=token, today_token=today_token, cutoff=CUT_OFF)

        if not (student_id and name):
            msg = "กรุณากรอกข้อมูลให้ครบ"
            return render_template("checkin.html", ok=False, msg=msg, token=token, today_token=today_token, cutoff=CUT_OFF)

        now = datetime.now()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO attendance (student_id, name, date, time, status) VALUES (?, ?, ?, ?, ?)",
            (student_id, name, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), calc_status(now)),
        )
        conn.commit()
        conn.close()

        return render_template("checkin.html", ok=True, name=name, sid=student_id,
                               time=now.strftime("%H:%M:%S"), status=calc_status(now),
                               token=token, today_token=today_token, cutoff=CUT_OFF)

    # GET: แสดงฟอร์ม
    msg = None if token_valid else "QR หมดอายุหรือไม่ถูกต้อง"
    return render_template("checkin.html", ok=None, msg=msg, token=token, today_token=today_token, cutoff=CUT_OFF)


# ===== LOCAL RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
