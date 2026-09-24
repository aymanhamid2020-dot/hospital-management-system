"""اختبارات الفواتير (ربط/دفع) والملف الشامل للمريض PDF + الترحيل."""
from conftest import login
from test_api import uid, _make_doctor, _make_patient


# ========== الترحيل الخفيف (ensure_columns) ==========
def test_ensure_columns_idempotent():
    from app.database import ensure_columns, engine
    from sqlalchemy import inspect

    ensure_columns()
    ensure_columns()  # مرة ثانية — لا يجب أن يفشل

    cols = {c["name"] for c in inspect(engine).get_columns("invoices")}
    assert {"appointment_id", "record_id", "payment_method", "paid_at"} <= cols


# ========== ربط الفواتير ==========
def _make_appt(client, admin, when="2030-05-05T11:00:00"):
    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")
    pat_id = _make_patient(client, admin)
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id,
        "appointment_date": when, "reason": "ربط"})
    assert r.status_code == 200, r.text
    return pat_id, doc_id, r.json()["id"]


def test_invoice_link_to_appointment(client, admin):
    pat_id, doc_id, appt_id = _make_appt(client, admin)

    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "appointment_id": appt_id,
        "amount": 250, "description": "كشف مرتبط بالموعد"})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["appointment_id"] == appt_id
    assert inv["paid_at"] is None and inv["payment_method"] is None

    # فلترة حسب الموعد
    r = client.get("/invoices/", headers=admin, params={"appointment_id": appt_id})
    assert r.status_code == 200
    assert any(i["id"] == inv["id"] for i in r.json())

    # ربط بموعد مريض آخر → 400
    other_pat = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": other_pat, "appointment_id": appt_id,
        "amount": 100, "description": "خطأ"})
    assert r.status_code == 400
    assert "لا ينتمي" in r.json()["detail"]

    # موعد غير موجود → 404
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "appointment_id": 999999,
        "amount": 100, "description": "خطأ"})
    assert r.status_code == 404

    # تنظيف
    client.delete(f"/invoices/{inv['id']}", headers=admin)
    client.delete(f"/appointments/{appt_id}", headers=admin)


def test_invoice_payment_flow(client, admin):
    pat_id = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 300, "description": "دفع"})
    inv_id = r.json()["id"]

    # طريقة دفع ممنوعة
    r = client.post(f"/invoices/{inv_id}/pay", headers=admin, json={"method": "bitcoin"})
    assert r.status_code == 400
    assert "مسموحة" in r.json()["detail"]

    # دفع نقدي
    r = client.post(f"/invoices/{inv_id}/pay", headers=admin, json={"method": "cash"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "paid"
    assert data["payment_method"] == "cash"
    assert data["paid_at"] is not None

    # دفع مكرر → 400
    r = client.post(f"/invoices/{inv_id}/pay", headers=admin, json={"method": "cash"})
    assert r.status_code == 400
    assert "بالفعل" in r.json()["detail"]

    # فلترة paid
    r = client.get("/invoices/", headers=admin, params={"patient_id": pat_id, "status": "paid"})
    assert r.status_code == 200
    assert any(i["id"] == inv_id for i in r.json())

    # بدون توكن
    assert client.post(f"/invoices/{inv_id}/pay", json={"method": "cash"}).status_code == 401

    client.delete(f"/invoices/{inv_id}", headers=admin)


def test_invoice_pdf_includes_payment_details(client, admin):
    pat_id = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 500, "description": "PDF دفع"})
    inv_id = r.json()["id"]
    client.post(f"/invoices/{inv_id}/pay", headers=admin, json={"method": "card"})

    r = client.get(f"/invoices/{inv_id}/pdf", headers=admin)
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"

    client.delete(f"/invoices/{inv_id}", headers=admin)


# ========== الملف الشامل للمريض PDF ==========
def test_patient_full_file_pdf(client, admin):
    pat_id = _make_patient(client, admin)
    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")

    # سجل طبي
    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id,
        "diagnosis": "التهاب حلق", "prescription": "مضاد حيوي ٣ أيام"})
    assert r.status_code == 200

    # فاتورة
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 150, "description": "كشف"})
    assert r.status_code == 200

    # مرفق
    r = client.post("/attachments/", headers=admin,
                    data={"patient_id": str(pat_id)},
                    files={"file": ("xray.png",
                                    b"\x89PNG\r\n\x1a\nfakepngdata",
                                    "image/png")})
    assert r.status_code == 200

    # توليد PDF
    r = client.get(f"/patients/{pat_id}/pdf", headers=admin)
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 5000  # ملف شامل لا بد أن يكون كبيرًا

    # بدون توكن
    assert client.get(f"/patients/{pat_id}/pdf").status_code == 401

    # مريض غير موجود
    r = client.get("/patients/999999/pdf", headers=admin)
    assert r.status_code == 404

    # تنظيف
    client.delete(f"/patients/{pat_id}", headers=admin)


def test_doctor_cannot_read_unrelated_patient_file(client, admin):
    # طبيب لا علاقة له بالمريض
    doc_email = f"dr_{uid()}@test.com"
    _make_doctor(client, admin, doc_email)
    pat_id = _make_patient(client, admin)  # بلا سجلات لهذا الطبيب

    un = "docuser_" + uid()
    client.post("/auth/register", json={
        "username": un, "email": doc_email, "full_name": "طبيب",
        "password": "secret123", "role": "doctor"})
    h = login(client, un, "secret123")

    r = client.get(f"/patients/{pat_id}/pdf", headers=h)
    assert r.status_code == 403
