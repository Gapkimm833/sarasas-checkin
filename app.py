import os, io, sqlite3
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, abort, make_response, flash, session
)
import pandas as pd
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")  # สำหรับ session/flash

# ===== CONFIG =====
PORT = int(os.environ.get("PORT", 10000))
TMP_DIR = "/tmp"

# เวลาตัด "มาสาย" (ตั้งได้ด้วย ENV: CUT_OFF)
CUT_OFF = os.environ.get("CUT_OFF", "08:35")
CUTOFF_H, CUTOFF_M = [int(x) for x in CUT_OFF.split(":")]

# รหัสครู (ตั้งได้ด้วย ENV: ADMIN_CODE)
ADMIN_CODE = os.environ.get("ADMIN_CODE", "beer1501")

# DB (ถ้าใช้ Render Disk: ตั้ง ENV DB_DIR=/var/data + ผูก Disk ที่ /var/data)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.environ.get("DB_DIR", BASE_DIR)
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "attendance.db")


# ===== DB =====
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # --- attendance (เดิม) ---
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
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_attend_sid_date
                   ON attendance(student_id, date);""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);""")

    # --- grades (ผลการเรียน) ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            name TEXT NOT NULL,
            level TEXT NOT NULL,          -- ระดับชั้น
            subject_name TEXT NOT NULL,   -- ชื่อวิชา
            subject_code TEXT NOT NULL,   -- รหัสวิชา
            result TEXT NOT NULL,         -- 0/ร/มส
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            CHECK (result in ('0','ร','มส'))
        );
    """)
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_grades_date ON grades(date);""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_grades_sid  ON grades(student_id);""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_grades_code ON grades(subject_code);""")

    # กัน “กดซ้ำวิชาเดิมในวันเดียวกัน” (student_id อาจว่าง ให้ใช้ COALESCE)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_grades_sid_code_day
        ON grades(COALESCE(student_id,''), subject_code, date);
    """)

    conn.commit()
    conn.close()


# เรียกทันที (รองรับ gunicorn/Render)
init_db()


# ===== HELPERS =====
def today_str(): return datetime.now().strftime("%Y-%m-%d")
def today_token(): return datetime.now().strftime("%Y%m%d")
def calc_status(now: datetime) -> str:
    return "มาสาย" if (now.hour, now.minute) > (CUTOFF_H, CUTOFF_M) else "มาเรียน"

def _make_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf.read()


# ===== TEMPLATE CONTEXT =====
@app.context_processor
def inject_is_admin():
    return {"is_admin": bool(session.get("is_admin"))}


# ===== WEB: เช็คชื่อ =====
@app.route("/", methods=["GET","POST"])
def home():
    conn = get_conn(); cur = conn.cursor()
    t = today_str()

    if request.method == "POST":
        sid = request.form.get("student_id","").strip()
        name = request.form.get("name","").strip()
        if sid and name:
            now = datetime.now()
            cur.execute(
                "INSERT OR IGNORE INTO attendance (student_id,name,date,time,status) VALUES (?,?,?,?,?)",
                (sid, name, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), calc_status(now))
            )
            conn.commit()
            flash("บันทึกสำเร็จ" if cur.rowcount == 1 else "นักเรียนคนนี้เช็คชื่อไปแล้ววันนี้",
                  "success" if cur.rowcount == 1 else "warning")

    cur.execute("SELECT student_id,name,date,time,status FROM attendance WHERE date=? ORDER BY time DESC", (t,))
    rows = cur.fetchall(); conn.close()
    return render_template("index.html", rows=rows, today=t, token=today_token(), cutoff=CUT_OFF)

@app.route("/delete_today")
def delete_today():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM attendance WHERE date=?", (today_str(),))
    conn.commit(); conn.close()
    flash("ลบข้อมูลของวันนี้แล้ว", "success")
    return redirect(url_for("home"))

@app.route("/delete_all")
def delete_all():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    conn.commit(); conn.close()
    flash("ลบข้อมูลทั้งหมดแล้ว", "success")
    return redirect(url_for("home"))


# ===== ADMIN (พิมพ์รหัสบนหน้าแรก) =====
@app.route("/admin_code", methods=["POST"])
def admin_code():
    code = request.form.get("code", "")
    next_url = request.form.get("next") or url_for("home")
    if code == ADMIN_CODE:
        session["is_admin"] = True
        flash("ยืนยันรหัสครูสำเร็จ ✔", "success")
        return redirect(next_url)
    flash("รหัสครูไม่ถูกต้อง", "danger")
    return redirect(url_for("home"))

@app.route("/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("ออกจากระบบแล้ว", "success")
    return redirect(url_for("home"))


# ===== EXPORT (ADMIN ONLY) =====
@app.route("/export_excel")
def export_excel():
    if not session.get("is_admin"):
        flash("ต้องยืนยันรหัสครูก่อนจึงจะดาวน์โหลด Excel ได้", "danger")
        return redirect(url_for("home"))
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


# ===== QR + MOBILE CHECK-IN =====
@app.route("/qr")
def qr_code():
    default_checkin = f"{request.url_root}checkin?t={today_token()}"
    text = request.args.get("text", default_checkin)
    png = _make_qr_png(text)
    resp = make_response(png)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

@app.route("/checkin", methods=["GET","POST"])
def checkin():
    token = request.values.get("t","")
    today_tok = today_token()
    token_valid = (token == today_tok)

    if request.method == "POST":
        if not token_valid:
            return render_template("checkin.html", ok=False, msg="QR หมดอายุหรือไม่ถูกต้อง",
                                   cutoff=CUT_OFF, today_token=today_tok, token=token)
        sid = request.form.get("student_id","").strip()
        name = request.form.get("name","").strip()
        now = datetime.now()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO attendance (student_id,name,date,time,status) VALUES (?,?,?,?,?)",
            (sid, name, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), calc_status(now))
        )
        conn.commit(); conn.close()
        return render_template("checkin.html", ok=True, name=name, sid=sid,
                               time=now.strftime("%H:%M:%S"), status=calc_status(now),
                               cutoff=CUT_OFF, today_token=today_tok, token=token)

    # GET
    return render_template("checkin.html", ok=None,
                           msg=None if token_valid else "QR หมดอายุหรือไม่ถูกต้อง",
                           cutoff=CUT_OFF, today_token=today_tok, token=token)


# ===== GRADES (ถ้าคุณใช้หน้า /grades) =====
@app.route("/grades", methods=["GET","POST"])
def grades():
    conn = get_conn(); cur = conn.cursor()
    t = today_str()

    if request.method == "POST":
        sid = request.form.get("student_id","").strip()
        name = request.form.get("name","").strip()
        level = request.form.get("level","").strip()
        sname = request.form.get("subject_name","").strip()
        scode = request.form.get("subject_code","").strip()
        result = request.form.get("result","").strip()  # 0/ร/มส
        if name and level and sname and scode and result in ("0","ร"):
            now = datetime.now()
            cur.execute(
                "INSERT INTO grades (student_id,name,level,subject_name,subject_code,result,date,time) VALUES (?,?,?,?,?,?,?,?)",
                (sid or None, name, level, sname, scode, result, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"))
            )
            conn.commit()
            flash("บันทึกผลการเรียนสำเร็จ", "success")
        else:
            flash("กรอกข้อมูลไม่ครบ หรือผลการเรียนต้องเป็น 0/ร/มส", "danger")

    cur.execute("""
        SELECT student_id,name,level,subject_name,subject_code,result,date,time
        FROM grades
        WHERE date=?
        ORDER BY time DESC
    """, (t,))
    rows = cur.fetchall(); conn.close()
    return render_template("grades.html", rows=rows, today=t)

@app.route("/export_grades")
def export_grades():
    if not session.get("is_admin"):
        flash("ต้องยืนยันรหัสครูก่อนจึงจะดาวน์โหลด Excel ได้", "danger")
        return redirect(url_for("grades"))
    try:
        conn = get_conn()
        df = pd.read_sql_query("SELECT * FROM grades", conn)
        conn.close()
        os.makedirs(TMP_DIR, exist_ok=True)
        file_path = os.path.join(TMP_DIR, "grades.xlsx")
        df.to_excel(file_path, index=False)
        return send_file(file_path, as_attachment=True, download_name="grades.xlsx")
    except Exception as e:
        return abort(500, description=str(e))

@app.route("/grades_delete_today")
def grades_delete_today():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM grades WHERE date=?", (today_str(),))
    conn.commit(); conn.close()
    flash("ลบผลการเรียนของวันนี้แล้ว", "success")
    return redirect(url_for("grades"))

@app.route("/grades_delete_all")
def grades_delete_all():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM grades")
    conn.commit(); conn.close()
    flash("ลบผลการเรียนทั้งหมดแล้ว", "success")
    return redirect(url_for("grades"))


@app.route("/healthz")
def healthz():
    return "ok", 200


# ===== LOCAL RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
