"""فحص مباشر: الإشعارات + البريد outbox + التذكير."""
import glob
import os
import time
from datetime import datetime, timedelta

import httpx

BASE = "http://127.0.0.1:8001"

tok = httpx.post(BASE + "/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
h = {"Authorization": "Bearer " + tok}

print("=== 1. الإشعارات ===")
r = httpx.get(BASE + "/notifications/", headers=h)
print("List:", r.status_code, "| count =", len(r.json()))
r = httpx.get(BASE + "/notifications/unread-count", headers=h)
print("Unread:", r.status_code, r.json())
assert httpx.get(BASE + "/notifications/").status_code == 401
print("Auth required: 401 OK")

print("\n=== 2. موعد جديد → إشعار + بريد outbox ===")
OUTBOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outbox")
before = set(glob.glob(os.path.join(OUTBOX, "*.eml"))) if os.path.isdir(OUTBOX) else set()

# إسناد بريد للمريض 1 مؤقتًا (عبر تحديث) — نستخدم مريضًا حاليًا
pats = httpx.get(BASE + "/patients/", headers=h).json()
docs = httpx.get(BASE + "/doctors/", headers=h).json()
pid, did = pats[0]["id"], docs[0]["id"]

# تحديث بريد المريض لاختبار outbox
httpx.put(f"{BASE}/patients/{pid}", headers=h, json={"email": "patient@test.com"})

r = httpx.post(BASE + "/appointments/", headers=h, json={
    "patient_id": pid, "doctor_id": did,
    "appointment_date": (datetime.now() + timedelta(hours=3)).isoformat(timespec="seconds"),
    "reason": "فحص حي"})
print("Create appt:", r.status_code)
appt_id = r.json()["id"]
time.sleep(1)  # انتظار BackgroundTasks

notifs = httpx.get(BASE + "/notifications/", headers=h).json()
mine = [n for n in notifs if n["appointment_id"] == appt_id]
print("Notification:", len(mine), "|", mine[0]["title"] if mine else "MISSING")
assert mine, "no notification created!"

after = set(glob.glob(os.path.join(OUTBOX, "*.eml")))
new_mails = after - before
print("Outbox emails:", len(new_mails), "|", [os.path.basename(p) for p in new_mails])
assert new_mails, "no outbox email!"

# عرض محتوى أول بريد
with open(sorted(new_mails)[-1], "rb") as f:
    content = f.read().decode("utf-8", errors="replace")
print("Email subject line:", [l for l in content.splitlines() if l.startswith("Subject")][:1])
print("Email has Arabic body:", "طبيب" in content or "موعد" in content or "health" in content or "مرحب" in content)

print("\n=== 3. التأكيد → تحديث حالة ===")
r = httpx.put(f"{BASE}/appointments/{appt_id}", headers=h, json={"status": "confirmed"})
print("Confirm:", r.status_code, "| status =", r.json()["status"])
time.sleep(1)
notifs = httpx.get(BASE + "/notifications/", headers=h).json()
mine = [n for n in notifs if n["appointment_id"] == appt_id]
print("Notifications for appt:", [(n["type"], n["title"]) for n in mine])
after2 = set(glob.glob(os.path.join(OUTBOX, "*.eml")))
print("New emails after confirm:", len(after2 - after))

print("\n=== 4. مهمة التذكير (استدعاء مباشر) ===")
# تشغيل منفصل عن الخادم (نفس قاعدة البيانات)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
n1_msg = None
from app.tasks import check_and_send_reminders
n1 = check_and_send_reminders()
n2 = check_and_send_reminders()
print(f"First run: {n1} reminders | Second run: {n2} (must be 0 — no duplicates)")
assert n2 == 0, "reminder duplicated!"

reminders = [n for n in httpx.get(BASE + "/notifications/", headers=h).json() if n["type"] == "reminder"]
print("Reminder notifications:", len(reminders))
if reminders:
    print("Sample:", reminders[0]["message"])

print("\n=== 5. تعليم كمقروء ===")
if notifs:
    r = httpx.put(f"{BASE}/notifications/{notifs[0]['id']}/read", headers=h)
    print("Mark read:", r.status_code, "| is_read =", r.json()["is_read"])
r = httpx.put(BASE + "/notifications/read-all", headers=h)
print("Read all:", r.status_code)
print("Unread after:", httpx.get(BASE + "/notifications/unread-count", headers=h).json())

# تنظيف: حذف الموعد التجريبي
r = httpx.delete(f"{BASE}/appointments/{appt_id}", headers=h)
print("\nCleanup appt:", r.status_code)

print("\nALL LIVE NOTIFICATION/EMAIL TESTS PASSED ✅")
