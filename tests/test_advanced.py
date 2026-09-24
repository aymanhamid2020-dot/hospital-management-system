"""اختبارات متقدمة: نطاق الطبيب في المختبر، استيراد الهوية الوطنية،
تدقيق عمليات المستخدمين، وتقارير PDF المتخصصة (مختبر/صيدلية/رواتب)."""
from conftest import login
from test_api import uid


def _register(client, role=None, prefix="adv"):
    """تسجيل مستخدم + دخول → (username, user_id, headers)."""
    u = prefix + "_" + uid()
    payload = {
        "username": u, "email": f"{u}@test.com",
        "full_name": "مستخدم متقدم", "password": "secret123",
    }
    if role:
        payload["role"] = role
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return u, r.json()["id"], login(client, u, "secret123")


def _make_linked_doctor(client, admin, prefix):
    """طبيب + حساب مستخدم بنفس البريد بدور doctor → (doctor_id, headers)."""
    email = f"{prefix}_{uid()}@test.com"
    r = client.post("/doctors/", headers=admin, json={
        "full_name": f"د. {prefix}", "specialty": "باطنة",
        "license_number": "SC-" + uid(), "phone": "0512345670", "email": email})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    u = prefix + "_" + uid()
    r = client.post("/auth/register", json={
        "username": u, "email": email, "full_name": f"د. {prefix}",
        "role": "doctor", "password": "secret123"})
    assert r.status_code == 200, r.text
    return doc_id, login(client, u, "secret123")


def _make_patient_with(client, admin, name, phone, birth):
    r = client.post("/patients/", headers=admin, json={
        "full_name": name, "date_of_birth": birth, "gender": "ذكر",
        "phone": phone, "email": f"adv_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ================= نطاق الطبيب في المختبر =================
def test_doctor_lab_orders_scoping(client, admin):
    doc_a, h_a = _make_linked_doctor(client, admin, "scA")
    r = client.post("/doctors/", headers=admin, json={
        "full_name": "د. نطاق ب", "specialty": "جراحة",
        "license_number": "SC-" + uid(), "phone": "0512345671",
        "email": f"scB_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    doc_b = r.json()["id"]
    pat = _make_patient_with(client, admin, "مريض النطاق", "0533333333", "1993-01-01")

    def mk(did, name):
        r = client.post("/lab-orders/", headers=admin, json={
            "patient_id": pat, "doctor_id": did, "test_name": name})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    o_a = mk(doc_a, "تحليل نطاق أ")
    o_b = mk(doc_b, "تحليل نطاق ب")
    o_n = mk(None, "تحليل بلا طبيب")

    # القائمة: الطبيب يرى طلباته فقط (لا طلبات زميله ولا غير المنسوبة)
    r = client.get("/lab-orders/", headers=h_a)
    assert r.status_code == 200
    ids = {o["id"] for o in r.json()}
    assert o_a in ids
    assert o_b not in ids
    assert o_n not in ids

    # فلترة صريحة على طبيب آخر ضمن نطاقه → فارغ
    r = client.get("/lab-orders/", headers=h_a, params={"doctor_id": doc_b})
    assert r.status_code == 200 and r.json() == []

    # تفصيل/تعديل طلب أجنبي → 404 دون تسريب الوجود
    assert client.get(f"/lab-orders/{o_b}", headers=h_a).status_code == 404
    r = client.put(f"/lab-orders/{o_b}", headers=h_a, json={"result": "محاولة"})
    assert r.status_code == 404

    # تفصيل وتعديل طلبه → مسموح
    assert client.get(f"/lab-orders/{o_a}", headers=h_a).status_code == 200
    r = client.put(f"/lab-orders/{o_a}", headers=h_a, json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"

    # المدير يرى الجميع
    r = client.get("/lab-orders/", headers=admin)
    admin_ids = {o["id"] for o in r.json()}
    assert {o_a, o_b, o_n} <= admin_ids


def test_doctor_lab_create_autolink_and_isolation(client, admin):
    doc_a, h_a = _make_linked_doctor(client, admin, "mkA")
    r = client.post("/doctors/", headers=admin, json={
        "full_name": "د. زميل", "specialty": "أسنان",
        "license_number": "SC-" + uid(), "phone": "0512345672",
        "email": f"mkB_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    doc_b = r.json()["id"]
    pat = _make_patient_with(client, admin, "مريض ذاتي", "0544444444", "1994-04-04")

    # إنشاء بلا طبيب → يُنسب تلقائيًا للطبيب نفسه
    r = client.post("/lab-orders/", headers=h_a, json={
        "patient_id": pat, "test_name": "طلب ذاتي"})
    assert r.status_code == 200, r.text
    assert r.json()["doctor_id"] == doc_a

    # محاولة إنشاء لطبيب آخر → 403
    r = client.post("/lab-orders/", headers=h_a, json={
        "patient_id": pat, "doctor_id": doc_b, "test_name": "اقتحام"})
    assert r.status_code == 403
    assert "طلباتك فقط" in r.json()["detail"]

    # طبيب بلا سجل طبيب مرتبط: قائمة فارغة + تقرير 403 + إنشاء 403
    _, _, h_lonely = _register(client, role="doctor", prefix="lonely")
    r = client.get("/lab-orders/", headers=h_lonely)
    assert r.status_code == 200 and r.json() == []
    assert client.get("/reports/lab/pdf", headers=h_lonely).status_code == 403
    r = client.post("/lab-orders/", headers=h_lonely, json={
        "patient_id": pat, "test_name": "بلا سجل"})
    assert r.status_code == 403
    assert "غير مرتبط" in r.json()["detail"]


# ================= استيراد الهوية الوطنية =================
def test_import_csv_national_id_dedupe(client, admin):
    nat = "IMP" + uid()
    email = f"imp_{uid()}@test.com"
    header = ("الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد الإلكتروني,"
              "الهوية الوطنية,شركة التأمين,رقم الوثيقة\r\n")
    row1 = f"عميل مستورد,1991-03-03,male,0551234567,{email},{nat},بوبا,POL9\r\n"
    files = {"file": ("imp.csv", (header + row1).encode("utf-8"), "text/csv")}

    # أول دفعة: إنشاء بالحقول الجديدة كاملة
    r = client.post("/patients/import", headers=admin, files=files)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 1 and d["errors"] == []

    r = client.get("/patients/", headers=admin, params={"search": nat})
    found = r.json()
    assert len(found) == 1
    p = found[0]
    assert p["national_id"] == nat
    assert p["insurer"] == "بوبا"
    assert p["policy_number"] == "POL9"

    # إعادة الدفعة نفسها → مكرر بالكامل
    r = client.post("/patients/import", headers=admin, files=files)
    assert r.status_code == 200
    assert r.json()["created"] == 0 and r.json()["skipped"] >= 1

    # بريد جديد لكن نفس الهوية → تُتجاهل بقاعدة الهوية الوطنية
    row2 = f"شخص آخر,1995-05-05,female,0557654321,oth_{uid()}@test.com,{nat}\r\n"
    files2 = {"file": ("imp2.csv", (header + row2).encode("utf-8"), "text/csv")}
    r = client.post("/patients/import", headers=admin, files=files2)
    assert r.status_code == 200
    assert r.json()["created"] == 0 and r.json()["skipped"] == 1

    # الهوية لم تتضاعف
    r = client.get("/patients/", headers=admin, params={"search": nat})
    assert len(r.json()) == 1


# ================= سجل التدقيق لعمليات المستخدمين =================
def test_audit_records_user_management(client, admin):
    _, user_id, _ = _register(client, prefix="aud")

    # PUT على إدارة المستخدمين يُسجَّل بمستخدم المدير
    r = client.put(f"/auth/users/{user_id}/toggle", headers=admin)
    assert r.status_code == 200

    r = client.get("/audit-logs/", headers=admin,
                   params={"method": "PUT", "username": "admin", "limit": 50})
    assert r.status_code == 200
    logs = r.json()
    assert all(l["method"] == "PUT" and l["username"] == "admin" for l in logs)
    assert any(l["path"].startswith("/auth/users") and l["status_code"] == 200
               for l in logs), "لم يُسجَّل تعديل المستخدمين في السجل"

    # السجل لا يحتوي عمليات GET مطلقًا
    r = client.get("/audit-logs/", headers=admin, params={"limit": 200})
    assert r.status_code == 200
    assert all(l["method"] in ("POST", "PUT", "PATCH", "DELETE")
               for l in r.json())

    # فلترة مستخدم غير مسجّل أي عملية له → فارغ
    r = client.get("/audit-logs/", headers=admin, params={"username": "لا أحد"})
    assert r.json() == []


# ================= تقارير PDF المتخصصة =================
def test_report_endpoints_roles_and_validation(client, admin):
    _, _, h_rec = _register(client, prefix="recp")
    _, h_doc = _make_linked_doctor(client, admin, "rpt")

    # تقرير المختبر: المدير + الطبيب المرتبط — ورفض بقية الأدوار
    for h_ok in (admin, h_doc):
        r = client.get("/reports/lab/pdf", headers=h_ok)
        assert r.status_code == 200 and r.content[:4] == b"%PDF", r.status_code
    assert client.get("/reports/lab/pdf", headers=h_rec).status_code == 403
    assert client.get("/reports/lab/pdf").status_code == 401
    # فلترة حالة اختيارية
    r = client.get("/reports/lab/pdf", headers=admin, params={"status": "pending"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"

    # تقرير الصيدلية: للمدير فقط
    r = client.get("/reports/pharmacy/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert client.get("/reports/pharmacy/pdf", headers=h_rec).status_code == 403

    # كشف الرواتب: للمدير فقط + تحقق صيغة الفترة
    r = client.get("/reports/payroll/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = client.get("/reports/payroll/pdf", headers=admin, params={"period": "2026-01"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = client.get("/reports/payroll/pdf", headers=admin, params={"period": "bad"})
    assert r.status_code == 400 and "YYYY-MM" in r.json()["detail"]
    assert client.get("/reports/payroll/pdf", headers=h_rec).status_code == 403


# ================= حالة النظام العامة =================
def test_status_public_json(client):
    # دون أي توكن
    r = client.get("/status")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["database"]["engine"] == "sqlite"
    assert d["database"]["connected"] is True
    assert d["version"]
    for k in ("patients", "doctors", "appointments", "invoices"):
        assert k in d["counts"] and d["counts"][k] >= 0
    assert "T" in d["time"]


def test_status_counts_follow_data(client, admin):
    before = client.get("/status").json()["counts"]["patients"]
    _make_patient_with(client, admin, "مريض عدّاد الحالة", "0567890123", "1989-09-09")
    after = client.get("/status").json()["counts"]["patients"]
    assert after == before + 1
