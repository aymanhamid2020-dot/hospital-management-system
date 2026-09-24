"""اختبارات آلية لنظام إدارة المستشفيات — pytest."""
import uuid

from conftest import login


def uid():
    return uuid.uuid4().hex[:8]


# ========== الصحة والتوثيق ==========
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_index_page_is_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "نظام إدارة المستشفيات" in r.text


def test_ui_page_served(client):
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "تسجيل الدخول" in r.text


# ========== المصادقة ==========
def test_protected_requires_token(client):
    r = client.get("/patients/")
    assert r.status_code == 401


def test_login_wrong_password(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_register_and_login(client):
    u = "user_" + uid()
    r = client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "مستخدم اختبار",
        "password": "secret123",
    })
    assert r.status_code == 200
    assert r.json()["role"] == "موظف استقبال"

    h = login(client, u, "secret123")
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["username"] == u


def test_duplicate_username_rejected(client):
    u = "dup_" + uid()
    body = {"username": u, "email": f"{u}@test.com", "full_name": "أ", "password": "secret123"}
    assert client.post("/auth/register", json=body).status_code == 200
    r = client.post("/auth/register", json=body)
    assert r.status_code == 400


# ========== المرضى ==========
def test_patient_crud(client, admin):
    email = f"p_{uid()}@test.com"
    # إنشاء
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض اختبار", "date_of_birth": "1990-01-01", "gender": "ذكر",
        "phone": "0500000001", "email": email,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # قراءة
    r = client.get(f"/patients/{pid}", headers=admin)
    assert r.status_code == 200
    assert r.json()["email"] == email

    # تحديث
    r = client.put(f"/patients/{pid}", headers=admin, json={"phone": "0500000002"})
    assert r.status_code == 200
    assert r.json()["phone"] == "0500000002"

    # بحث
    r = client.get("/patients/", headers=admin, params={"search": "مريض اختبار"})
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())

    # بريد مكرر
    r = client.post("/patients/", headers=admin, json={
        "full_name": "آخر", "date_of_birth": "1991-01-01", "gender": "أنثى",
        "phone": "0500000003", "email": email,
    })
    assert r.status_code == 400

    # مريض غير موجود
    assert client.get("/patients/999999", headers=admin).status_code == 404

    # حذف (admin)
    assert client.delete(f"/patients/{pid}", headers=admin).status_code == 204


# ========== الأطباء والمواعيد ==========
def _make_doctor(client, admin, email):
    r = client.post("/doctors/", headers=admin, json={
        "full_name": "طبيب اختبار", "specialty": "باطنية",
        "license_number": "L-" + uid(), "phone": "0511111111", "email": email,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض مواعيد", "date_of_birth": "1992-02-02", "gender": "ذكر",
        "phone": "0522222222", "email": f"ap_{uid()}@test.com",
    })
    assert r.status_code == 200
    return r.json()["id"]


def test_appointment_creation_and_conflict(client, admin):
    doc_id = _make_doctor(client, admin, f"doc_{uid()}@test.com")
    pat_id = _make_patient(client, admin)
    body = {"patient_id": pat_id, "doctor_id": doc_id,
            "appointment_date": "2030-01-15T10:00:00", "reason": "فحص"}

    r = client.post("/appointments/", headers=admin, json=body)
    assert r.status_code == 200, r.text

    # تعارض نفس الطبيب/التاريخ
    r = client.post("/appointments/", headers=admin, json=body)
    assert r.status_code == 400
    assert "موعد في هذا التاريخ" in r.json()["detail"]


def test_appointment_filters(client, admin):
    r = client.get("/appointments/", headers=admin, params={"date": "not-a-date"})
    assert r.status_code == 400

    r = client.get("/appointments/", headers=admin, params={"status": "pending"})
    assert r.status_code == 200

    r = client.get("/appointments/", headers=admin, params={"date": "2030-01-15"})
    assert r.status_code == 200


# ========== الصلاحيات ==========
def test_receptionist_cannot_create_department(client, admin):
    u = "rec_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "موظف", "password": "secret123"})
    h = login(client, u, "secret123")

    r = client.post("/departments/", headers=h, json={"name": "قسم غير مصرح"})
    assert r.status_code == 403

    r = client.get("/auth/users", headers=h)
    assert r.status_code == 403


def test_receptionist_cannot_delete_patient(client, admin):
    u = "rec2_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "موظف", "password": "secret123"})
    h = login(client, u, "secret123")

    r = client.post("/patients/", headers=h, json={
        "full_name": "حماية", "date_of_birth": "1990-01-01", "gender": "ذكر",
        "phone": "0533333333", "email": f"prot_{uid()}@test.com"})
    pid = r.json()["id"]

    # لا يحذف
    assert client.delete(f"/patients/{pid}", headers=h).status_code == 403
    # لكن المدير يحذف
    assert client.delete(f"/patients/{pid}", headers=admin).status_code == 204


def test_department_crud_admin(client, admin):
    r = client.post("/departments/", headers=admin, json={"name": "قسم-" + uid()})
    assert r.status_code == 200
    did = r.json()["id"]
    assert client.get(f"/departments/{did}", headers=admin).status_code == 200
    assert client.delete(f"/departments/{did}", headers=admin).status_code == 204


# ========== السجلات الطبية وصلاحيات الطبيب ==========
def test_medical_record_doctor_scoping(client, admin):
    doc_email = f"dr_{uid()}@test.com"
    doc_id = _make_doctor(client, admin, doc_email)
    pat_id = _make_patient(client, admin)

    # سجل بيد هذا الطبيب
    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": doc_id, "diagnosis": "التهاب"})
    assert r.status_code == 200
    rec_id = r.json()["id"]

    # سجل بيد طبيب آخر
    other_doc = _make_doctor(client, admin, f"dr2_{uid()}@test.com")
    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat_id, "doctor_id": other_doc, "diagnosis": "آخر"})
    other_rec = r.json()["id"]

    # حساب المستخدم الطبيب
    un = "docuser_" + uid()
    client.post("/auth/register", json={
        "username": un, "email": doc_email, "full_name": "طبيب", "password": "secret123",
        "role": "doctor"})
    h = login(client, un, "secret123")

    # يرى سجله فقط
    recs = client.get("/medical-records/", headers=h).json()
    ids = [x["id"] for x in recs]
    assert rec_id in ids
    assert other_rec not in ids

    # إنشاء يُنسب له تلقائيًا
    r = client.post("/medical-records/", headers=h, json={
        "patient_id": pat_id, "diagnosis": "自动ربط"})
    assert r.status_code == 200
    assert r.json()["doctor_id"] == doc_id

    # لا يصل لسجل الطبيب الآخر
    assert client.get(f"/medical-records/{other_rec}", headers=h).status_code == 403

    # حذف محجوب للمدير فقط
    assert client.delete(f"/medical-records/{rec_id}", headers=h).status_code == 403
    assert client.delete(f"/medical-records/{rec_id}", headers=admin).status_code == 204
    client.delete(f"/medical-records/{other_rec}", headers=admin)


# ========== الفواتير و PDF ==========
def test_invoice_and_pdf(client, admin):
    pat_id = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat_id, "amount": 100.0, "description": "اختبار", "status": "paid"})
    assert r.status_code == 200
    inv_id = r.json()["id"]

    # طباعة HTML
    r = client.get(f"/invoices/{inv_id}/print", headers=admin)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "فاتورة" in r.text

    # PDF
    r = client.get(f"/invoices/{inv_id}/pdf", headers=admin)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"

    # بدون توكن
    assert client.get(f"/invoices/{inv_id}/pdf").status_code == 401


# ========== المرفقات ==========
def test_attachment_upload_download_delete(client, admin):
    pat_id = _make_patient(client, admin)

    # رفع ملف نصي
    r = client.post("/attachments/", headers=admin,
                    data={"patient_id": str(pat_id)},
                    files={"file": ("result.txt", "vitamin D: normal".encode(), "text/plain")})
    assert r.status_code == 200, r.text
    att_id = r.json()["id"]
    assert r.json()["size_bytes"] > 0

    # تنزيل
    r = client.get(f"/attachments/{att_id}/file", headers=admin)
    assert r.status_code == 200
    assert r.content == b"vitamin D: normal"

    # نوع ملف ممنوع
    r = client.post("/attachments/", headers=admin,
                    data={"patient_id": str(pat_id)},
                    files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400

    # مريض غير موجود
    r = client.post("/attachments/", headers=admin,
                    data={"patient_id": "999999"},
                    files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 404

    # حذف
    assert client.delete(f"/attachments/{att_id}", headers=admin).status_code == 204
    assert client.get(f"/attachments/{att_id}/file", headers=admin).status_code == 404


# ========== لوحة التحكم والتقارير ==========
def test_dashboard_stats(client, admin):
    r = client.get("/dashboard/stats", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert data["total_patients"] >= 0
    assert "revenue_total" in data
    assert "appointments_by_status" in data


def test_report_pdf_admin_only(client, admin):
    r = client.get("/dashboard/report/pdf", headers=admin)
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"

    # شهر خاطئ
    r = client.get("/dashboard/report/pdf", headers=admin, params={"month": "bad"})
    assert r.status_code == 400

    # بدون توكن
    assert client.get("/dashboard/report/pdf").status_code == 401


# ========== النسخ الاحتياطي ==========
def test_backup_admin_only(client, admin):
    r = client.post("/backup", headers=admin)
    assert r.status_code == 200
    assert r.json()["file"].startswith("hospital_")

    r = client.get("/backup", headers=admin)
    assert r.status_code == 200
    assert len(r.json()) >= 1

    # رفض بدون توكن
    assert client.post("/backup").status_code == 401
