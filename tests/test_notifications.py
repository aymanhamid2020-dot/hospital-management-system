"""اختبارات الإشعارات، البريد (outbox)، ومهمة التذكير."""
import glob
import os

from conftest import login
from test_api import uid, _make_doctor, _make_patient


# ========== الإشعارات ==========
def test_notifications_list_and_read(client, admin):
    r = client.get("/notifications/", headers=admin)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r = client.get("/notifications/unread-count", headers=admin)
    assert r.status_code == 200
    assert "unread" in r.json()


def test_appointment_creates_notification_and_outbox_email(client, admin):
    from app.email_utils import OUTBOX_DIR
    before = set(glob.glob(os.path.join(OUTBOX_DIR, "*.eml"))) if os.path.isdir(OUTBOX_DIR) else set()

    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")
    pat_id = _make_patient(client, admin)

    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id,
        "appointment_date": "2030-03-10T09:00:00", "reason": "اختبار بريد"})
    assert r.status_code == 200
    appt_id = r.json()["id"]

    # إشعار داخلي موجود
    notifs = client.get("/notifications/", headers=admin).json()
    match = [n for n in notifs if n["appointment_id"] == appt_id and n["type"] == "appointment"]
    assert len(match) == 1
    assert "موعد" in match[0]["title"]

    # بريد outbox أُنشئ (BackgroundTasks يعمل قبل عودة TestClient)
    after = set(glob.glob(os.path.join(OUTBOX_DIR, "*.eml")))
    assert len(after - before) >= 1

    # تنظيف
    client.delete(f"/appointments/{appt_id}", headers=admin)


def test_mark_notification_read_and_all(client, admin):
    notifs = client.get("/notifications/", headers=admin).json()
    unread = [n for n in notifs if not n["is_read"]]
    if unread:
        r = client.put(f"/notifications/{unread[0]['id']}/read", headers=admin)
        assert r.status_code == 200
        assert r.json()["is_read"] is True

    r = client.put("/notifications/read-all", headers=admin)
    assert r.status_code == 200
    assert client.get("/notifications/unread-count", headers=admin).json()["unread"] == 0

    # 404 لرقم غير موجود
    assert client.put("/notifications/999999/read", headers=admin).status_code == 404
    assert client.delete("/notifications/999999", headers=admin).status_code == 404


def test_notifications_require_auth(client):
    assert client.get("/notifications/").status_code == 401
    assert client.get("/notifications/unread-count").status_code == 401


def test_delete_notification(client, admin):
    notifs = client.get("/notifications/", headers=admin).json()
    if notifs:
        nid = notifs[0]["id"]
        assert client.delete(f"/notifications/{nid}", headers=admin).status_code == 204
        assert client.get("/notifications/", headers=admin).status_code == 200


# ========== التذكير الخلفي ==========
def test_reminder_task_runs_once_per_appointment(client, admin):
    from datetime import datetime, timedelta
    from app.database import SessionLocal
    from app.models import Appointment, Notification
    from app.tasks import check_and_send_reminders

    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")
    pat_id = _make_patient(client, admin)

    soon = datetime.now() + timedelta(hours=2)
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id,
        "appointment_date": soon.isoformat(), "reason": "تذكير"})
    assert r.status_code == 200
    appt_id = r.json()["id"]

    # أول تشغيل — ينشئ تذكير
    n1 = check_and_send_reminders()
    assert n1 >= 1

    # تشغيل ثانٍ — لا تكرار لنفس الموعد
    n2 = check_and_send_reminders()
    assert n2 == 0

    db = SessionLocal()
    try:
        reminders = db.query(Notification).filter(
            Notification.appointment_id == appt_id,
            Notification.type == "reminder").all()
        assert len(reminders) == 1
    finally:
        db.close()

    client.delete(f"/appointments/{appt_id}", headers=admin)


# ========== وحدة البريد ==========
def test_send_email_outbox_mode(tmp_path):
    from app.email_utils import send_email, _build_message, _save_to_outbox

    # وضع outbox (MAIL_ENABLED=false افتراضيًا)
    res = send_email("test@example.com", "اختبار", "مرحبًا")
    assert res["success"] is True
    assert res["mode"] == "outbox"
    assert os.path.isfile(res["path"])

    # حذف الملف المؤقت
    os.remove(res["path"])

    # بريد بدون مستلم
    res = send_email("", "اختبار", "مرحبًا")
    assert res["success"] is False


def test_email_templates():
    from app.email_utils import appointment_created_email, appointment_reminder_email

    s, b = appointment_created_email("أحمد", "د. سارة", "2030-01-01 10:00")
    assert "أحمد" in b and "د. سارة" in b and "2030-01-01" in b
    assert "تأكيد" in s

    s, b = appointment_reminder_email("أحمد", "د. سارة", "2030-01-01 10:00")
    assert "تذكير" in s and "أحمد" in b
