"""ملف الطبيب بالأقسام الخمسة — الملف المهني · الجداول والصلاحيات · المالية · الأداء.

ملف مستقل عن test_doctors_section.py، ويعزل نفسه بوسوم فريدة (uid) ليعمل
على قاعدة الاختبار المشتركة بأمان.
"""
import uuid
from datetime import datetime, timedelta

from conftest import login


def uid():
    return uuid.uuid4().hex[:8]


def _mk_doctor(client, admin, **kw):
    """طبيب للاختبار — الحقول تمرّ كما هي (academic_rank و consultation_fee)."""
    body = {
        "full_name": "د. " + uid(),
        "specialty": "باطنة",
        "license_number": "DOC-" + uid(),
        "phone": "0555550000",
        "email": f"doc_{uid()}@test.com",
    }
    body.update(kw)
    r = client.post("/doctors/", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض ملف " + uid(), "date_of_birth": "1990-01-01",
        "gender": "ذكر", "phone": "0555000" + uid()[:4],
        "email": f"pt_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mk_user(client, role="doctor"):
    uname = "dr_" + uid()
    r = client.post("/auth/register", json={
        "username": uname, "email": f"{uname}@test.com",
        "full_name": "طبيب " + uid(), "role": role, "password": "Passw0rd!"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ══════════ 1. الملف الشخصي والمهني ══════════
def test_profile_fields_saved(client, admin):
    user_id = _mk_user(client)
    d = _mk_doctor(client, admin, academic_rank="استشاري",
                   sub_specialty="أمراض القلب", branch="فرع الرياض",
                   user_id=user_id, consultation_minutes=30,
                   consultation_fee=250, followup_fee=150)
    assert d["academic_rank"] == "استشاري"
    assert d["sub_specialty"] == "أمراض القلب"
    assert d["consultation_minutes"] == 30
    assert d["consultation_fee"] == 250

    r = client.put(f"/doctors/{d['id']}/profile", headers=admin, json={
        "academic_rank": "أخصائي", "consultation_fee": 300,
        "permissions": {"own_patients_only": True, "view_emergency": True,
                        "order_lab": True, "order_radiology": False,
                        "prescribe": True, "view_invoices": False,
                        "view_doctor_financials": False}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["academic_rank"] == "أخصائي"
    assert body["consultation_fee"] == 300
    assert body["permissions"]["view_emergency"] is True
    assert body["permissions"]["order_radiology"] is False


def test_profile_rejects_bad_values(client, admin):
    d = _mk_doctor(client, admin)
    # خارج النطاق ⇒ 422 من التحقق، وحساب مستخدم غير موجود ⇒ 404
    for bad, want in (({"academic_rank": "أستاذ"}, 422),
                      ({"consultation_minutes": 1}, 422),
                      ({"consultation_fee": -5}, 422),
                      ({"user_id": 999999}, 404)):
        r = client.put(f"/doctors/{d['id']}/profile", headers=admin, json=bad)
        assert r.status_code == want, f"{bad} ⇒ {r.status_code} {r.text}"


def test_create_with_rank_and_fees(client, admin):
    d = _mk_doctor(client, admin, academic_rank="طبيب مقيم",
                   consultation_minutes=20, consultation_fee=180)
    assert d["academic_rank"] == "طبيب مقيم"
    assert d["consultation_minutes"] == 20
    # درجة خارج القوائم المسموحة ⇒ 422
    r = client.post("/doctors/", headers=admin, json={
        "full_name": "د. " + uid(), "specialty": "جراحة",
        "license_number": "DOC-" + uid(), "phone": "0555000000",
        "email": f"doc_{uid()}@test.com", "academic_rank": "غير معروف"})
    assert r.status_code == 422, r.text


# ══════════ 2. المناوبات والإجازات وحظر الحجز ══════════
def test_shift_crud_and_validation(client, admin):
    d = _mk_doctor(client, admin)
    day = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT08:00:00")
    # نهاية قبل البداية ⇒ 400
    r = client.post(f"/doctors/{d['id']}/shifts", headers=admin, json={
        "shift_type": "emergency", "shift_date": day,
        "start_time": "20:00", "end_time": "08:00", "location": "الطوارئ"})
    assert r.status_code == 400, r.text

    r = client.post(f"/doctors/{d['id']}/shifts", headers=admin, json={
        "shift_type": "oncall", "shift_date": day,
        "start_time": "20:00", "end_time": "23:00"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    assert client.get(f"/doctors/{d['id']}/shifts", headers=admin).status_code == 200
    assert client.delete(f"/doctors/{d['id']}/shifts/{sid}",
                         headers=admin).status_code == 204
    assert client.delete(f"/doctors/{d['id']}/shifts/{sid}",
                         headers=admin).status_code == 404


def test_shift_type_validated(client, admin):
    d = _mk_doctor(client, admin)
    r = client.post(f"/doctors/{d['id']}/shifts", headers=admin, json={
        "shift_type": "urgery", "shift_date": "2030-01-01T08:00:00",
        "start_time": "08:00", "end_time": "16:00"})
    assert r.status_code == 422, r.text


def test_leave_range_and_crud(client, admin):
    d = _mk_doctor(client, admin)
    s = datetime(2030, 5, 1).isoformat()
    e = datetime(2030, 5, 5).isoformat()
    # نهاية قبل بداية ⇒ 400
    bad = client.post(f"/doctors/{d['id']}/leaves", headers=admin, json={
        "start_date": e, "end_date": s, "reason": "عكس"})
    assert bad.status_code == 400, bad.text

    r = client.post(f"/doctors/{d['id']}/leaves", headers=admin,
                    json={"start_date": s, "end_date": e, "reason": "سنوية"})
    assert r.status_code == 201, r.text
    assert client.delete(f"/doctors/{d['id']}/leaves/{r.json()['id']}",
                         headers=admin).status_code == 204


def test_block_time_requires_both_times(client, admin):
    d = _mk_doctor(client, admin)
    day = "2030-06-10"
    # وقت بداية بلا نهاية ⇒ رفض
    r = client.post(f"/doctors/{d['id']}/blocks", headers=admin,
                    json={"block_date": day, "start_time": "12:00"})
    assert r.status_code == 400, r.text
    # يوم كامل بلا أوقات ⇒ قبول
    r = client.post(f"/doctors/{d['id']}/blocks", headers=admin,
                    json={"block_date": day, "reason": "مؤتمر"})
    assert r.status_code == 201, r.text
    assert r.json()["start_time"] is None


# ══════════ 3. الصلاحيات والتوقيع والختم ══════════
def test_permissions_default_and_corrupt_json(client, admin):
    d = _mk_doctor(client, admin)
    ch = client.get(f"/doctors/{d['id']}/chart", headers=admin).json()
    assert ch["permissions"]["own_patients_only"] is True
    assert ch["permissions"]["view_emergency"] is False

    # الصلاحيات التالفة (JSON غير صالح) لا تُعطّل الطلب
    from app.database import SessionLocal
    from app.models import Doctor
    s = SessionLocal()
    try:
        row = s.query(Doctor).filter(Doctor.id == d["id"]).first()
        row.permissions = "{ليس JSON"
        s.commit()
    finally:
        s.close()
    ch2 = client.get(f"/doctors/{d['id']}/chart", headers=admin).json()
    assert ch2["permissions"]["own_patients_only"] is True


def test_stamp_upload_requires_image(client, admin):
    d = _mk_doctor(client, admin)
    r = client.post(f"/doctors/{d['id']}/signature", headers=admin,
                    files={"file": ("sig.txt", b"not an image", "text/plain")})
    assert r.status_code == 400, r.text

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    r = client.post(f"/doctors/{d['id']}/signature", headers=admin,
                    files={"file": ("sig.png", png, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["signature_path"]

    got = client.get(f"/doctors/{d['id']}/signature/image", headers=admin)
    assert got.status_code == 200
    assert got.content.startswith(b"\x89PNG")

    r = client.post(f"/doctors/{d['id']}/stamp", headers=admin,
                    files={"file": ("stamp.png", png, "image/png")})
    assert r.status_code == 200, r.text
    assert client.delete(f"/doctors/{d['id']}/signature",
                         headers=admin).status_code == 204
    assert client.get(f"/doctors/{d['id']}/signature/image",
                      headers=admin).status_code == 404


# ══════════ 4. العمولات وكشف الحساب ══════════
def test_commission_replaces_and_validates(client, admin):
    d = _mk_doctor(client, admin)
    r = client.put(f"/doctors/{d['id']}/commissions", headers=admin, json=[
        {"service_type": "consultation", "billing_type": "percent", "rate": 40},
        {"service_type": "surgery", "billing_type": "fixed", "rate": 1500}])
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    # نسبة خارج 0..100 ⇒ 422
    bad = client.put(f"/doctors/{d['id']}/commissions", headers=admin, json=[
        {"service_type": "consultation", "billing_type": "percent", "rate": 150}])
    assert bad.status_code == 422, bad.text

    # نوع خدمة مكرر في نفس الطلب ⇒ 400
    dup = client.put(f"/doctors/{d['id']}/commissions", headers=admin, json=[
        {"service_type": "consultation", "billing_type": "percent", "rate": 10},
        {"service_type": "consultation", "billing_type": "fixed", "rate": 20}])
    assert dup.status_code == 400, dup.text

    # الاستبدال يستبدل ولا يضيف
    left = client.get(f"/doctors/{d['id']}/commissions", headers=admin).json()
    assert len(left) == 2


def test_ledger_computed_from_invoices(client, admin):
    d = _mk_doctor(client, admin)
    pid = _mk_patient(client, admin)
    month = datetime.now().strftime("%Y-%m")
    when = datetime.now().strftime("%Y-%m-%dT10:00:00")
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"], "appointment_date": when,
        "reason": "كشف"})
    assert r.status_code == 200, r.text
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 1000, "description": "كشفية"})
    assert r.status_code == 200, r.text

    client.put(f"/doctors/{d['id']}/commissions", headers=admin, json=[
        {"service_type": "consultation", "billing_type": "percent", "rate": 30}])
    led = client.get(f"/doctors/{d['id']}/ledger?month={month}", headers=admin)
    assert led.status_code == 200, led.text
    body = led.json()
    assert body["revenue"] == 1000
    assert body["earned"] == 300
    assert body["balance"] == 300
    assert body["by_commission"][0]["label"] == "كشفية"


def test_payout_cannot_exceed_balance(client, admin):
    d = _mk_doctor(client, admin)
    pid = _mk_patient(client, admin)
    month = datetime.now().strftime("%Y-%m")
    when = datetime.now().strftime("%Y-%m-%dT10:00:00")
    client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"], "appointment_date": when})
    client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 100, "description": "كشف"})
    client.put(f"/doctors/{d['id']}/commissions", headers=admin, json=[
        {"service_type": "consultation", "billing_type": "fixed", "rate": 10}])

    over = client.post(f"/doctors/{d['id']}/payouts", headers=admin, json={
        "amount": 500, "period": month, "paid_at": datetime.now().isoformat()})
    assert over.status_code == 400, "المبلغ يتجاوز الرصيد ⇒ 400"

    ok = client.post(f"/doctors/{d['id']}/payouts", headers=admin, json={
        "amount": 10, "period": month, "paid_at": datetime.now().isoformat()})
    assert ok.status_code == 201, ok.text

    bad = client.post(f"/doctors/{d['id']}/payouts", headers=admin, json={
        "amount": 5, "period": "2030/01", "paid_at": datetime.now().isoformat()})
    assert bad.status_code == 400, bad.text


def test_financials_admin_only(client, admin):
    d = _mk_doctor(client, admin)
    uname = "rec_" + uid()
    r = client.post("/auth/register", json={
        "username": uname, "email": f"{uname}@test.com",
        "full_name": "موظف استقبال", "role": "موظف استقبال",
        "password": "Passw0rd!"})
    rec = login(client, r.json()["username"], "Passw0rd!")
    out = client.post(f"/doctors/{d['id']}/payouts", headers=rec, json={
        "amount": 10, "period": "2030-01", "paid_at": datetime.now().isoformat()})
    assert out.status_code == 403, out.text
    assert client.get(f"/doctors/{d['id']}/ledger", headers=rec).status_code == 403
    assert client.get(f"/doctors/{d['id']}/payouts", headers=rec).status_code == 403


# ══════════ 5. تقارير الأداء والإحصائيات ══════════
def test_visit_stats_new_returning_emergency(client, admin):
    d = _mk_doctor(client, admin)
    now = datetime.now()
    p_new = _mk_patient(client, admin)
    p_back = _mk_patient(client, admin)

    # موعد قديم (لوقت مختلف) ⇒ المريض يصبح «عائدًا»؛ لا يمكن حجز موعدين
    # للطبيب في نفس اللحظة (قاعدة منع التعارض في appointments).
    client.post("/appointments/", headers=admin, json={
        "patient_id": p_back, "doctor_id": d["id"],
        "appointment_date": (now - timedelta(days=40)).isoformat()})
    client.post("/appointments/", headers=admin, json={
        "patient_id": p_back, "doctor_id": d["id"],
        "appointment_date": (now + timedelta(days=1)).isoformat()})
    client.post("/appointments/", headers=admin, json={
        "patient_id": p_new, "doctor_id": d["id"],
        "appointment_date": (now + timedelta(days=2)).isoformat(),
        "reason": "طوارئ ليلي"})
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": _mk_patient(client, admin), "doctor_id": d["id"],
        "appointment_date": (now + timedelta(days=3)).isoformat()})
    assert r.status_code == 200, r.text
    client.put(f"/appointments/{r.json()['id']}", headers=admin,
               json={"status": "cancelled"})

    v = client.get(f"/doctors/{d['id']}/chart", headers=admin).json()["visits"]
    assert v["new_patients"] == 2, v        # المريض الجديد + الملغي
    assert v["returning_patients"] == 1, v
    assert v["emergency_visits"] == 1, v
    assert v["cancelled"] == 1
    assert 0 < v["cancel_rate"] < 1


def test_top_orders_and_chart_shape(client, admin):
    d = _mk_doctor(client, admin)
    pid = _mk_patient(client, admin)
    med = client.post("/medications/", headers=admin, json={
        "code": "M" + uid(), "name": "دواء " + uid(),
        "quantity": 50, "price": 10}).json()
    rx = client.post("/prescriptions/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"], "items": [
            {"medication_id": med["id"], "quantity": 3}]})
    assert rx.status_code in (200, 201), rx.text
    client.post("/lab-orders/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"], "test_name": "صورة دم"})

    ch = client.get(f"/doctors/{d['id']}/chart", headers=admin).json()
    o = ch["orders"]
    assert o["prescriptions_count"] >= 1
    assert o["lab_orders_count"] >= 1
    assert any(m["name"].startswith("دواء") for m in o["top_medications"])
    assert any(t["name"] == "صورة دم" for t in o["top_lab_tests"])
    for key in ("schedules", "shifts", "leaves", "blocks",
                "commissions", "payouts", "visits", "orders", "ledger"):
        assert key in ch, key


def test_chart_guards(client, admin):
    d = _mk_doctor(client, admin)
    assert client.get(f"/doctors/{d['id']}/chart?month=2030-13",
                      headers=admin).status_code == 400
    assert client.get("/doctors/999999/chart", headers=admin).status_code == 404
    assert client.get(f"/doctors/{d['id']}/chart").status_code == 401


# ══════════ الإجازات والحظر تمنع الحجز فعليًا ══════════
def test_leave_blocks_appointment_booking(client, admin):
    d = _mk_doctor(client, admin)
    pid = _mk_patient(client, admin)
    r = client.post(f"/doctors/{d['id']}/leaves", headers=admin, json={
        "start_date": "2031-04-06T00:00:00", "end_date": "2031-04-08T00:00:00",
        "reason": "سفر"})
    assert r.status_code == 201, r.text
    out = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"],
        "appointment_date": "2031-04-07T10:00:00"})
    assert out.status_code == 400, out.text
    assert "إجازة" in out.json()["detail"]


def test_block_day_and_partial_window(client, admin):
    d = _mk_doctor(client, admin)
    pid = _mk_patient(client, admin)
    r = client.post(f"/doctors/{d['id']}/blocks", headers=admin, json={
        "block_date": "2031-05-11", "reason": "مؤتمر"})
    assert r.status_code == 201, r.text
    out = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"],
        "appointment_date": "2031-05-11T10:00:00"})
    assert out.status_code == 400 and "محظور" in out.json()["detail"], out.text

    # حظر فترة جزئية: قبلها مسموح، داخلها ممنوع
    r = client.post(f"/doctors/{d['id']}/blocks", headers=admin, json={
        "block_date": "2031-05-12", "start_time": "12:00", "end_time": "14:00",
        "reason": "عملية"})
    assert r.status_code == 201, r.text
    ok = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"],
        "appointment_date": "2031-05-12T09:00:00"})
    assert ok.status_code == 200, ok.text
    blocked = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"],
        "appointment_date": "2031-05-12T13:00:00"})
    assert blocked.status_code == 400, blocked.text


def test_rescheduling_into_blocked_day_rejected(client, admin):
    d = _mk_doctor(client, admin)
    pid = _mk_patient(client, admin)
    r = client.post(f"/doctors/{d['id']}/blocks", headers=admin, json={
        "block_date": "2031-06-08", "reason": "ظرف طارئ"})
    assert r.status_code == 201, r.text
    appt = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": d["id"],
        "appointment_date": "2031-06-09T10:00:00"})
    assert appt.status_code == 200, appt.text
    mv = client.put(f"/appointments/{appt.json()['id']}", headers=admin, json={
        "appointment_date": "2031-06-08T10:00:00"})
    assert mv.status_code == 400, mv.text