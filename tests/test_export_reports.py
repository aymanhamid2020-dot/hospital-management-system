"""اختبارات: تصدير/استيراد CSV + إتمام الموعد + تقرير الطبيب."""
import csv
import io

from conftest import login
from test_api import uid, _make_doctor, _make_patient


# ========== تصدير CSV ==========
def test_export_patients_csv(client, admin):
    r = client.get("/patients/export.csv", headers=admin)
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    # BOM حتى يتعرّف Excel على العربية
    assert r.content[:3] == "\ufeff".encode("utf-8")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][0] == "الاسم الكامل"
    assert len(rows) > 1  # بيانات موجودة فعلًا


def test_export_invoices_csv(client, admin):
    pat_id = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 66, "description": "فاتورة تصدير csv",
        "insurer": "التعاونية"})
    inv_id = r.json()["id"]

    r = client.get("/invoices/export.csv", headers=admin)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "فاتورة تصدير csv" in text
    assert "التعاونية" in text

    # فلترة بالحالة
    r = client.get("/invoices/export.csv", headers=admin, params={"status": "paid"})
    assert r.status_code == 200
    assert "فاتورة تصدير csv" not in r.content.decode("utf-8-sig")  # لم تُدفع بعد

    client.delete(f"/invoices/{inv_id}", headers=admin)


def test_export_requires_auth(client):
    assert client.get("/patients/export.csv").status_code == 401
    assert client.get("/invoices/export.csv").status_code == 401


# ========== استيراد CSV ==========
def test_import_patients_roundtrip(client, admin):
    email = f"imp_{uid()}@test.com"
    content = (
        "الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد الإلكتروني,العنوان,مجموعة الدم\r\n"
        f"مستورد اختبار,1990-05-05,male,0550000001,{email},الرياض,O+\r\n"
    ).encode("utf-8")

    r = client.post("/patients/import", headers=admin,
                    files={"file": ("patients.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 1 and d["skipped"] == 0 and d["errors"] == []

    # الإعادة → مكرّر (حسب البريد)
    r = client.post("/patients/import", headers=admin,
                    files={"file": ("patients.csv", content, "text/csv")})
    assert r.json()["created"] == 0 and r.json()["skipped"] == 1

    # المريض موجود والجنس طُبّع إلى قيمة enum
    r = client.get("/patients/", headers=admin, params={"search": "مستورد اختبار"})
    rows = r.json()
    assert rows and rows[0]["email"] == email
    assert rows[0]["gender"] == "ذكر"

    client.delete(f"/patients/{rows[0]['id']}", headers=admin)


def test_import_bad_rows_reported(client, admin):
    content = (
        "الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد الإلكتروني\r\n"
        "بلا بريد,1990-01-01,ذكر,0551,\r\n"          # بريد فارغ → خطأ
        "تاريخ خاطئ,ليس تاريخًا,أنثى,0552,notdate@test.com\r\n"  # تاريخ غير صالح
    ).encode("utf-8")
    r = client.post("/patients/import", headers=admin,
                    files={"file": ("bad.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 0
    assert len(d["errors"]) == 2
    assert d["errors"][0]["row"] == 2 and d["errors"][1]["row"] == 3


def test_import_empty_file_rejected(client, admin):
    r = client.post("/patients/import", headers=admin,
                    files={"file": ("e.csv", b"", "text/csv")})
    assert r.status_code == 400


def test_import_cp1256_encoding(client, admin):
    """Excel العربي قد يحفظ بترميز cp1256 — يجب قراءته أيضًا."""
    email = f"cp_{uid()}@test.com"
    line = f"مريض cp1256,1988-03-03,أنثى,0553,{email}\r\n"
    content = ("الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد الإلكتروني\r\n" + line)
    r = client.post("/patients/import", headers=admin,
                    files={"file": ("p.csv", content.encode("cp1256"), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 1, d

    found = client.get("/patients/", headers=admin, params={"search": "مريض cp1256"}).json()
    assert found and found[0]["gender"] == "أنثى"
    client.delete(f"/patients/{found[0]['id']}", headers=admin)


# ========== إتمام الموعد ==========
def test_appointment_confirm_and_complete(client, admin):
    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")
    pat_id = _make_patient(client, admin)
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id,
        "appointment_date": "2031-03-03T09:00:00", "reason": "اختبار الإتمام"})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    assert r.json()["status"] == "pending"

    r = client.put(f"/appointments/{aid}", headers=admin, json={"status": "confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"

    r = client.put(f"/appointments/{aid}", headers=admin, json={"status": "completed"})
    assert r.status_code == 200 and r.json()["status"] == "completed"

    client.delete(f"/appointments/{aid}", headers=admin)


# ========== تقرير الطبيب ==========
def _make_doctor_user(client, admin, prefix):
    """سجل طبيب + حساب مستخدم role=doctor بنفس البريد + تسجيل دخوله."""
    u = f"{prefix}_{uid()}"
    email = f"{u}@test.com"
    doc_id = _make_doctor(client, admin, email)
    client.post("/auth/register", json={
        "username": u, "email": email, "full_name": "طبيب التقرير",
        "password": "secret123", "role": "doctor"})
    return doc_id, login(client, u, "secret123")


def test_doctor_scoped_report_pdf(client, admin):
    doc_id, doc_h = _make_doctor_user(client, admin, "drrep")
    pat_id = _make_patient(client, admin)
    client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id, "diagnosis": "لتقرير الطبيب"})
    client.post("/appointments/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id,
        "appointment_date": "2031-04-04T10:00:00", "reason": "موعد التقرير"})

    # الطبيب يصل لتقريره
    r = client.get("/dashboard/report/pdf", headers=doc_h)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-", r.text

    # مع شهر صحيح
    r = client.get("/dashboard/report/pdf", headers=doc_h, params={"month": "2026-09"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"

    # شهر خاطئ → 400
    r = client.get("/dashboard/report/pdf", headers=doc_h, params={"month": "bad"})
    assert r.status_code == 400


def test_unlinked_doctor_report_forbidden(client, admin):
    """طبيب حسابه غير مرتبط بسجل طبيب → 403."""
    u = "drnl_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "بلا سجل",
        "password": "secret123", "role": "doctor"})
    h = login(client, u, "secret123")
    r = client.get("/dashboard/report/pdf", headers=h)
    assert r.status_code == 403


def test_receptionist_report_forbidden(client, admin):
    u = "recrep_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "موظف استقبال",
        "password": "secret123"})
    h = login(client, u, "secret123")
    r = client.get("/dashboard/report/pdf", headers=h)
    assert r.status_code == 403


def test_admin_report_still_global(client, admin):
    r = client.get("/dashboard/report/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
