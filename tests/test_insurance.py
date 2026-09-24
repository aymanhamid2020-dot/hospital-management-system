"""اختبارات التأمين + عرض المرفقات داخل السجلات + seed_demo."""
from conftest import login
from test_api import uid, _make_doctor, _make_patient


# ========== التأمين ==========
def test_insurance_invoice_and_payment(client, admin):
    pat_id = _make_patient(client, admin)

    # إنشاء فاتورة ببيانات تأمين
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 800, "description": "كشف تأمين",
        "insurer": "بوبا العربية", "policy_number": "POL-" + uid(),
    })
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["insurer"] == "بوبا العربية"
    assert inv["policy_number"].startswith("POL-")

    # دفع بالتأمين بدون شركة تأمين → 400
    r2 = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 100, "description": "بدون تأمين"})
    r = client.post(f"/invoices/{r2.json()['id']}/pay", headers=admin, json={"method": "insurance"})
    assert r.status_code == 400
    assert "شركة التأمين" in r.json()["detail"]

    # دفع بالتأمين مع بيانات التأمين → 200
    r = client.post(f"/invoices/{inv['id']}/pay", headers=admin, json={"method": "insurance"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["payment_method"] == "insurance"
    assert data["insurer"] == "بوبا العربية"

    # تحديث بيانات التأمين
    r = client.put(f"/invoices/{inv['id']}", headers=admin, json={"policy_number": "POL-NEW"})
    assert r.status_code == 200
    assert r.json()["policy_number"] == "POL-NEW"

    # PDF الفاتورة ينجح بعد الدفع
    r = client.get(f"/invoices/{inv['id']}/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"

    # تنظيف
    client.delete(f"/invoices/{inv['id']}", headers=admin)
    client.delete(f"/invoices/{r2.json()['id']}", headers=admin)


def test_insurance_fields_survive_rebuild(client, admin):
    """الحقول الجديدة تظهر بعد الترحيل/idempotency."""
    from app.database import ensure_columns, engine
    from sqlalchemy import inspect

    ensure_columns()
    cols = {c["name"] for c in inspect(engine).get_columns("invoices")}
    assert {"insurer", "policy_number"} <= cols


# ========== المرفقات في السجلات ==========
def test_record_with_attachment_listed(client, admin):
    pat_id = _make_patient(client, admin)
    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")

    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id, "diagnosis": "كسور"})
    rec_id = r.json()["id"]

    # رفع مرفق مرتبط بالسجل
    r = client.post("/attachments/", headers=admin,
                    data={"patient_id": str(pat_id), "record_id": str(rec_id)},
                    files={"file": ("fracture.txt", b"fracture visible", "text/plain")})
    assert r.status_code == 200
    att_id = r.json()["id"]
    assert r.json()["record_id"] == rec_id

    # جلب مرفقات السجل
    r = client.get("/attachments/", headers=admin, params={"record_id": rec_id})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["id"] == att_id

    # سجل آخر لا يرى مرفقاته
    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "diagnosis": "آخر"})
    other = r.json()["id"]
    r = client.get("/attachments/", headers=admin, params={"record_id": other})
    assert r.json() == []

    # تنظيف
    client.delete(f"/attachments/{att_id}", headers=admin)
    client.delete(f"/medical-records/{rec_id}", headers=admin)
    client.delete(f"/medical-records/{other}", headers=admin)


def test_medical_record_pdf_after_attachments(client, admin):
    pat_id = _make_patient(client, admin)
    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "diagnosis": "PDF بعد مرفق"})
    rec_id = r.json()["id"]
    r = client.get(f"/medical-records/{rec_id}/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    client.delete(f"/medical-records/{rec_id}", headers=admin)
