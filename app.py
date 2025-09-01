import datetime as dt
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, send_file
import qrcode
from openpyxl import Workbook

app = Flask(__name__)

# ====== ตั้งค่าเวลาตัดสาย ======
# เช่น 08:35 -> ถ้าเช็คหลังเวลานี้ สถานะจะเป็น "สาย" อัตโนมัติ
CUTOFF_HOUR = 8
CUTOFF_MINUTE = 35

# ====== เก็บข้อมูลในหน่วยความจำ (เดโม) ======
# รายการเช็คชื่อทั้งหมด (ข้ามวันได้) -> list[ dict ]
# dict = {date, time, student_id, name, status}
records = []

def today_date_str():
    return dt.date.today().isoformat()

def now_time_str():
    return dt.datetime.now().strftime("%H:%M:%S")

def is_late(now=None):
    if now is None:
        now = dt.datetime.now().time()
    cutoff = dt.time(CUTOFF_HOUR, CUTOFF_MINUTE, 0)
    return now > cutoff

# ====== หน้าแรก / ตาราง ======
@app.route("/")
def index():
    scope = request.args.get("scope", "today")  # today | all
    today = today_date_str()

    if scope == "all":
        view_rows = records
    else:
        view_rows = [r for r in records if r["date"] == today]

    # ทำ badge สีสำหรับสถานะ
    for r in view_rows:
        r["_badge"] = "success" if r["status"] == "มา" else ("warning" if r["status"] == "สาย" else "secondary")

    # URL สำหรับรูป QR (จะชี้กลับมาหน้า / พร้อมพารามิเตอร์วัน)
    qr_url = url_for("qr_image", _external=True)

    return render_template(
        "index.html",
        rows=view_rows,
        scope=scope,
        today=today,
        cutoff=f"{CUTOFF_HOUR:02d}:{CUTOFF_MINUTE:02d}",
        qr_image_url=qr_url
    )

# ====== สร้างรูป QR แบบไดนามิก ======
@app.route("/qr.png")
def qr_image():
    # ให้ QR พาไปหน้าเว็บนี้เอง (ใส่พารามิเตอร์วันที่ไว้เฉยๆ)
    link = request.url_root.rstrip("/") + "/?s=" + dt.datetime.now().strftime("%Y%m%d")
    img = qrcode.make(link)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# ====== บันทึกเช็คชื่อแบบกรอกทีละคน ======
@app.route("/checkin", methods=["POST"])
def checkin():
    sid = (request.form.get("student_id") or "").strip()
    name = (request.form.get("name") or "").strip()

    if not sid or not name:
        return redirect(url_for("index"))

    now = dt.datetime.now()
    status = "สาย" if is_late(now.time()) else "มา"

    records.append({
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "student_id": sid,
        "name": name,
        "status": status
    })
    return redirect(url_for("index"))

# ====== ปุ่มควบคุม ======
@app.route("/reset_today", methods=["POST"])
def reset_today():
    today = today_date_str()
    global records
    records = [r for r in records if r["date"] != today]
    return redirect(url_for("index"))

@app.route("/reset_all", methods=["POST"])
def reset_all():
    records.clear()
    return redirect(url_for("index"))

# ====== ดาวน์โหลดเป็น Excel (xlsx) ======
@app.route("/export_xlsx")
def export_xlsx():
    scope = request.args.get("scope", "today")
    today = today_date_str()
    if scope == "all":
        rows = records
        filename = "attendance_all.xlsx"
    else:
        rows = [r for r in records if r["date"] == today]
        filename = f"attendance_{today}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    ws.append(["วันที่", "เวลา", "รหัสนักเรียน", "ชื่อ - นามสกุล", "สถานะ"])
    for r in rows:
        ws.append([r["date"], r["time"], r["student_id"], r["name"], r["status"]])

    mem = BytesIO()
    wb.save(mem)
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
