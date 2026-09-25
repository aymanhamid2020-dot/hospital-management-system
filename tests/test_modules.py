"""اختبارات المحاور الجديدة:
المختبر/الأشعة، الصيدلية، الطابور، الرواتب، تغيير كلمة المرور،
الهوية التأمينية للمريض، خصم/ضريبة الفواتير والدفع الجزئي، وسجل التدقيق.
"""
from conftest import login
from test_api import uid, _make_doctor, _make_patient


def _receptionist(client):
    """إنشاء موظف استقبال (لا صلاحيات إدارية) وإرجاع ترويسته."""
    u = "rec_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "موظف استقبال",
        "password": "secret123"})
    return login(client, u, "secret123")


# ================= تغيير كلمة المرور الذاتي =================
def test_change_password_flow(client):
    u = "pw_" + uid()
    r = client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "مستخدم كلمة مرور",
        "password": "oldpass123"})
    assert r.status_code in (200, 201), r.text
    h = login(client, u, "oldpass123")

    # كلمة المرور الحالية خاطئة → 400
    r = client.post("/auth/change-password", headers=h,
                    json={"current_password": "wrong", "new_password": "newpass456"})
    assert r.status_code == 400
    assert "الحالية" in r.json()["detail"]

    # كلمة جديدة قصيرة → 422 (validation)
    r = client.post("/auth/change-password", headers=h,
                    json={"current_password": "oldpass123", "new_password": "12345"})
    assert r.status_code == 422

    # نجاح التغيير
    r = client.post("/auth/change-password", headers=h,
                    json={"current_password": "oldpass123", "new_password": "newpass456"})
    assert r.status_code == 200, r.text

    # الدخول بالجديدة يعمل، والقديمة يفشل
    login(client, u, "newpass456")
    r = client.post("/auth/login", json={"username": u, "password": "oldpass123"})
    assert r.status_code != 200

    # بدون ترويسة → 401
    r = client.post("/auth/change-password",
                    json={"current_password": "x", "new_password": "newpass999"})
    assert r.status_code == 401


# ================= الهوية الوطنية والتأمين للمريض =================
def test_patient_national_id_and_insurance(client, admin):
    nat = "NID" + uid()
    payload = {
        "full_name": "مريض بهوية", "date_of_birth": "1990-05-05", "gender": "ذكر",
        "phone": "0555555555", "email": f"nat_{uid()}@test.com",
        "national_id": nat, "insurer": "شركة التأمين الطبي", "policy_number": "POL-1",
    }
    r = client.post("/patients/", headers=admin, json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["national_id"] == nat
    assert d["insurer"] == "شركة التأمين الطبي"
    assert d["policy_number"] == "POL-1"

    # هوية مكررة → 400
    payload["email"] = f"nat2_{uid()}@test.com"
    r = client.post("/patients/", headers=admin, json=payload)
    assert r.status_code == 400
    assert "الهوية" in r.json()["detail"]

    # بحث بالهوية الوطنية
    r = client.get("/patients/", headers=admin, params={"search": nat})
    assert r.status_code == 200
    assert any(p["id"] == d["id"] for p in r.json())


def test_patient_csv_includes_national_id(client, admin):
    r = client.get("/patients/export.csv", headers=admin)
    assert r.status_code == 200
    assert "الهوية الوطنية" in r.text
    assert "شركة التأمين" in r.text
    assert "رقم الوثيقة" in r.text


# ================= خصم/ضريبة الفواتير =================
def test_invoice_discount_tax_totals(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 100, "discount": 10, "tax_rate": 10,
        "description": "كشف خصم"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["subtotal"] == 90
    assert d["tax"] == 9
    assert d["total"] == 99
    assert d["paid_amount"] == 0
    assert d["status"] == "unpaid"

    # الاسترجاع يعيد المجاميع
    r = client.get(f"/invoices/{d['id']}", headers=admin)
    assert r.status_code == 200
    assert r.json()["total"] == 99


def test_invoice_totals_validation(client, admin):
    pat = _make_patient(client, admin)
    # خصم أكبر من المبلغ → 400
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 50, "discount": 60, "description": "خصم مبالغ"})
    assert r.status_code == 400
    assert "يتجاوز" in r.json()["detail"]

    # ضريبة تتجاوز 100% → 422
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 100, "tax_rate": 150, "description": "ضريبة"})
    assert r.status_code == 422

    # خصم كامل = فاتورة مجانية
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 40, "discount": 40, "description": "مجاني"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0


def test_invoice_partial_payment_flow(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 100, "discount": 10, "description": "جزئي"})
    inv = r.json()["id"]
    assert r.json()["total"] == 90

    # دفعة جزئية
    r = client.post(f"/invoices/{inv}/pay", headers=admin,
                    json={"method": "cash", "amount": 40})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "partial"
    assert d["paid_amount"] == 40

    # تجاوز المتبقي → 400
    r = client.post(f"/invoices/{inv}/pay", headers=admin,
                    json={"method": "cash", "amount": 60})
    assert r.status_code == 400
    assert "يتجاوز" in r.json()["detail"]

    # إتمام المتبقي (50) → مدفوعة
    r = client.post(f"/invoices/{inv}/pay", headers=admin,
                    json={"method": "card", "amount": 50})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "paid"
    assert d["paid_amount"] == 90
    assert d["paid_at"] is not None

    # دفع مكرر → 400
    r = client.post(f"/invoices/{inv}/pay", headers=admin, json={"method": "cash"})
    assert r.status_code == 400
    assert "بالفعل" in r.json()["detail"]


def test_invoice_created_as_paid_syncs_paid_amount(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 80, "description": "مدفوعة مسبقًا",
        "status": "paid"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "paid"
    assert d["paid_amount"] == 80
    assert d["paid_at"] is not None


def test_invoice_print_and_csv_show_totals(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pat, "amount": 200, "discount": 20, "tax_rate": 5,
        "description": "طباعة الإجمالي"})
    inv = r.json()["id"]
    assert r.json()["total"] == 189  # 180 + 9

    r = client.get(f"/invoices/{inv}/print", headers=admin)
    assert r.status_code == 200
    assert "الإجمالي" in r.text and "189.00" in r.text

    r = client.get("/invoices/export.csv", headers=admin)
    assert r.status_code == 200
    assert "الإجمالي" in r.text and "الخصم" in r.text


def test_dashboard_revenue_uses_totals(client, admin):
    r = client.get("/dashboard/stats", headers=admin)
    assert r.status_code == 200
    s = r.json()
    assert "revenue_total" in s and "revenue_paid" in s and "revenue_unpaid" in s
    # المجاميع الجديدة لا تُنتج إيرادًا محصّلًا زائدًا على الإجمالي
    assert s["revenue_paid"] <= s["revenue_total"] + 0.01
    assert s["revenue_paid"] > 0  # فواتير اختبارية مدفوعة موجودة
    assert s["revenue_unpaid"] >= 0


# ================= المختبر والأشعة =================
def test_lab_order_lifecycle(client, admin):
    pat = _make_patient(client, admin)
    doc = _make_doctor(client, admin, f"labdoc_{uid()}@test.com")
    r = client.post("/lab-orders/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc, "test_type": "lab",
        "test_name": "تحليل CBC", "price": 60})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["status"] == "pending"
    oid = order["id"]

    # لا جاهزية بلا نتيجة
    r = client.put(f"/lab-orders/{oid}", headers=admin, json={"status": "ready"})
    assert r.status_code == 400
    assert "نتيجة" in r.json()["detail"]

    # قيد التنفيذ ثم جاهزة بالنتيجة
    r = client.put(f"/lab-orders/{oid}", headers=admin, json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"

    r = client.put(f"/lab-orders/{oid}", headers=admin,
                   json={"status": "ready", "result": "النتيجة طبيعية"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["result"] == "النتيجة طبيعية"
    assert d["result_at"] is not None

    # إشعار جاهزية النتيجة
    r = client.get("/notifications/", headers=admin, params={"limit": 50})
    assert r.status_code == 200
    assert any(n["type"] == "lab_result" and "تحليل CBC" in n["message"]
               for n in r.json())

    # مراجعة الطبيب
    r = client.put(f"/lab-orders/{oid}", headers=admin, json={"status": "reviewed"})
    assert r.status_code == 200 and r.json()["status"] == "reviewed"


def test_lab_order_result_pdf(client, admin):
    """ورقة نتيجة المختبر PDF: ar/en + فحص lang أولًا + الملكية 404 + 401."""
    pat = _make_patient(client, admin)
    doc = _make_doctor(client, admin, f"pdfdoc_{uid()}@test.com")
    r = client.post("/lab-orders/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc, "test_type": "lab",
        "test_name": "تحليل ورقة PDF", "price": 55})
    assert r.status_code == 200, r.text
    oid = r.json()["id"]

    # النسختان عربي/إنجليزي
    r = client.get(f"/lab-orders/{oid}/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF", r.status_code
    assert f"lab_result_{oid}.pdf" in r.headers.get("content-disposition", "")
    r = client.get(f"/lab-orders/{oid}/pdf", headers=admin,
                   params={"lang": "en"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert (f"lab_result_{oid}_en.pdf"
            in r.headers.get("content-disposition", ""))

    # lang غير صالح => 400 أولًا — حتى قبل فحص وجود الطلب
    r = client.get(f"/lab-orders/{oid}/pdf", headers=admin,
                   params={"lang": "fr"})
    assert r.status_code == 400 and "lang" in r.json()["detail"]
    assert (client.get("/lab-orders/999999/pdf", headers=admin,
                       params={"lang": "fr"}).status_code == 400)

    # غير موجود + بلا توكن
    r = client.get("/lab-orders/999999/pdf", headers=admin)
    assert r.status_code == 404 and "لا يوجد طلب" in r.json()["detail"]
    assert client.get(f"/lab-orders/{oid}/pdf").status_code == 401

    # طبيب غير مالك للطلب => 404 (مطابق لمنطق عرض الطلب)
    email = f"otpdf_{uid()}@test.com"
    _make_doctor(client, admin, email)
    u = "otpdf_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": email, "full_name": "طبيب آخر",
        "password": "secret123", "role": "doctor"})
    h_other = login(client, u, "secret123")
    assert client.get(f"/lab-orders/{oid}",
                      headers=h_other).status_code == 404
    assert client.get(f"/lab-orders/{oid}/pdf",
                      headers=h_other).status_code == 404


def test_lab_ui_markers(client):
    """مؤشرات واجهة المختبر: ورقة النتيجة + فلترة الحالة بالبحث."""
    ui = client.get("/app.js").text
    for marker in ("async lab(main)", "function filterLabRows(",
                   "f-lab-status", 'data-status="${o.status}"',
                   "/lab-orders/${o.id}/pdf", "ورقة النتيجة"):
        assert marker in ui, f"مؤشر مفقود في واجهة المختبر: {marker}"


def test_lab_order_filters(client, admin):
    pat = _make_patient(client, admin)
    doc = _make_doctor(client, admin, f"qdoc_{uid()}@test.com")
    r = client.post("/lab-orders/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc, "test_type": "radiology",
        "test_name": "أشعة صدر"})
    assert r.status_code == 200, r.text
    oid = r.json()["id"]

    r = client.get("/lab-orders/", headers=admin, params={"test_type": "radiology"})
    assert any(o["id"] == oid for o in r.json())

    r = client.get("/lab-orders/", headers=admin, params={"patient_id": pat})
    assert any(o["id"] == oid for o in r.json())

    r = client.get("/lab-orders/", headers=admin,
                   params={"status": "pending", "test_type": "lab"})
    assert all(o["id"] != oid for o in r.json())

    r = client.get("/lab-orders/", headers=admin, params={"doctor_id": doc})
    assert any(o["id"] == oid for o in r.json())


def test_lab_order_validation_and_delete(client, admin):
    # مريض غير موجود → 404
    r = client.post("/lab-orders/", headers=admin,
                    json={"patient_id": 999999, "test_name": "CBC"})
    assert r.status_code == 404 and "مريض" in r.json()["detail"]

    pat = _make_patient(client, admin)
    # طبيب غير موجود → 404
    r = client.post("/lab-orders/", headers=admin,
                    json={"patient_id": pat, "doctor_id": 999999, "test_name": "CBC"})
    assert r.status_code == 404 and "طبيب" in r.json()["detail"]

    r = client.post("/lab-orders/", headers=admin,
                    json={"patient_id": pat, "test_name": "حذف لاحقًا"})
    oid = r.json()["id"]

    # الحذف للمدير فقط
    h = _receptionist(client)
    r = client.delete(f"/lab-orders/{oid}", headers=h)
    assert r.status_code == 403

    r = client.delete(f"/lab-orders/{oid}", headers=admin)
    assert r.status_code == 204
    assert client.get(f"/lab-orders/{oid}", headers=admin).status_code == 404


# ================= الصيدلية =================
def test_medication_admin_only(client, admin):
    h = _receptionist(client)
    assert client.get("/medications/", headers=h).status_code == 200
    r = client.post("/medications/", headers=h, json={
        "code": "X" + uid(), "name": "غير مصرح", "quantity": 1})
    assert r.status_code == 403


def test_medication_crud_and_duplicate_code(client, admin):
    code = "MED" + uid()
    r = client.post("/medications/", headers=admin, json={
        "code": code, "name": "باراسيتامول 500", "quantity": 20,
        "unit": "علبة", "price": 5.5, "min_quantity": 15})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert r.json()["quantity"] == 20

    # رمز مكرر → 400
    r = client.post("/medications/", headers=admin, json={
        "code": code, "name": "اسم آخر", "quantity": 5})
    assert r.status_code == 400 and "بالفعل" in r.json()["detail"]

    # توريد كمية
    r = client.put(f"/medications/{mid}", headers=admin, json={"quantity": 50})
    assert r.status_code == 200 and r.json()["quantity"] == 50

    # حذف (للمدير)
    r = client.delete(f"/medications/{mid}", headers=admin)
    assert r.status_code == 204
    assert client.get(f"/medications/{mid}", headers=admin).status_code == 404


def test_dispense_updates_stock_and_alerts(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/medications/", headers=admin, json={
        "code": "DSP" + uid(), "name": "أموكسيسيلين", "quantity": 20,
        "unit": "علبة", "price": 8, "min_quantity": 15})
    mid = r.json()["id"]

    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": mid, "patient_id": pat, "quantity": 5})
    assert r.status_code == 200, r.text
    disp = r.json()
    assert disp["unit_price"] == 8
    assert disp["dispensed_by"] == "admin"
    assert disp["patient"]["id"] == pat

    # المخزون انخفض إلى حد التنبيه → إشعار
    r = client.get(f"/medications/{mid}", headers=admin)
    assert r.json()["quantity"] == 15

    r = client.get("/notifications/", headers=admin, params={"limit": 50})
    assert any(n["type"] == "low_stock" and "أموكسيسيلين" in n["message"]
               for n in r.json())

    # ظهر في فلتر المخزون المنخفض
    r = client.get("/medications/", headers=admin, params={"low_stock": "true"})
    assert any(m["id"] == mid for m in r.json())

    # سجل الصرف يفلتر بالمريض
    r = client.get("/dispenses/", headers=admin, params={"patient_id": pat})
    assert any(d["medication_id"] == mid for d in r.json())


def test_dispense_errors(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/medications/", headers=admin, json={
        "code": "ERR" + uid(), "name": "مخزون ضيق", "quantity": 3,
        "unit": "علبة", "price": 2})
    mid = r.json()["id"]

    # كمية أكبر من المتوفر → 400
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": mid, "patient_id": pat, "quantity": 10})
    assert r.status_code == 400
    assert "تجاوز" in r.json()["detail"]

    # دواء غير موجود → 404
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": 999999, "patient_id": pat, "quantity": 1})
    assert r.status_code == 404

    # مريض غير موجود → 404
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": mid, "patient_id": 999999, "quantity": 1})
    assert r.status_code == 404

    # كمية صفر → 422
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": mid, "patient_id": pat, "quantity": 0})
    assert r.status_code == 422

    # المخزون لم يتغير
    assert client.get(f"/medications/{mid}", headers=admin).json()["quantity"] == 3


# ================= طابور الوصول =================
def test_checkin_assigns_sequential_queue(client, admin):
    doc = _make_doctor(client, admin, f"q1doc_{uid()}@test.com")
    pat = _make_patient(client, admin)

    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc,
        "appointment_date": "2030-05-20T09:00:00", "reason": "طابور"})
    assert r.status_code == 200, r.text
    a1 = r.json()["id"]
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc,
        "appointment_date": "2030-05-20T10:00:00", "reason": "طابور"})
    assert r.status_code == 200, r.text
    a2 = r.json()["id"]

    # الوصول الأول → رقم 1
    r = client.post(f"/appointments/{a1}/checkin", headers=admin)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["queue_number"] == 1
    assert j["checked_in_at"] is not None

    # تكرار الوصول → 400
    r = client.post(f"/appointments/{a1}/checkin", headers=admin)
    assert r.status_code == 400 and "بالفعل" in r.json()["detail"]

    # الثاني → رقم 2
    r = client.post(f"/appointments/{a2}/checkin", headers=admin)
    assert r.status_code == 200 and r.json()["queue_number"] == 2

    # طابور ذلك اليوم مرتب برقم الطابور
    r = client.get("/appointments/queue", headers=admin, params={"date": "2030-05-20"})
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()]
    assert ids == [a1, a2]

    # الظهور في قائمة المواعيد
    r = client.get("/appointments/", headers=admin, params={"date": "2030-05-20"})
    m = {a["id"]: a for a in r.json()}
    assert m[a1]["queue_number"] == 1
    assert m[a1]["checked_in_at"] is not None


def test_checkin_rejections_and_queue_date_validation(client, admin):
    doc = _make_doctor(client, admin, f"q2doc_{uid()}@test.com")
    pat = _make_patient(client, admin)
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc,
        "appointment_date": "2030-05-21T11:00:00", "reason": "ملغى"})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    # إلغاء الموعد يمنع الوصول
    r = client.put(f"/appointments/{aid}", headers=admin,
                   json={"status": "cancelled"})
    assert r.status_code == 200, r.text
    r = client.post(f"/appointments/{aid}/checkin", headers=admin)
    assert r.status_code == 400 and "ملغى" in r.json()["detail"]

    # موعد غير موجود → 404
    r = client.post("/appointments/999999/checkin", headers=admin)
    assert r.status_code == 404

    # صيغة تاريخ خاطئة للطابور → 400
    r = client.get("/appointments/queue", headers=admin, params={"date": "bad"})
    assert r.status_code == 400

    # طابور يوم بلا وصولات → فارغ
    r = client.get("/appointments/queue", headers=admin, params={"date": "2031-01-01"})
    assert r.status_code == 200 and r.json() == []


# ================= الرواتب =================
def test_payroll_and_audit_admin_only(client, admin):
    h = _receptionist(client)
    # الرواتب للمدير فقط
    assert client.get("/payroll/", headers=h).status_code == 403
    r = client.post("/payroll/", headers=h, json={
        "staff_id": 1, "period": "2030-01", "base_salary": 100})
    assert r.status_code == 403
    # سجل التدقيق للمدير فقط
    assert client.get("/audit-logs/", headers=h).status_code == 403
    assert client.get("/audit-logs/").status_code == 401


def test_payroll_flow(client, admin):
    r = client.post("/staff/", headers=admin, json={
        "full_name": "موظف رواتب", "position": "محاسب", "phone": "0566666666",
        "email": f"pay_{uid()}@test.com", "hire_date": "2025-01-01", "salary": 5000})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # إنشاء قيد: الصافي = أساسي + بدلات − استقطاعات
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": sid, "period": "2030-07", "base_salary": 5000,
        "bonus": 400, "deduction": 300})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["net"] == 5100
    assert d["status"] == "unpaid"
    pid = d["id"]

    # الفترة مكررة → 400
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": sid, "period": "2030-07", "base_salary": 100})
    assert r.status_code == 400 and "الفترة" in r.json()["detail"]

    # أساسي صفر ⇒ يعتمد راتب الموظف المسجّل
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": sid, "period": "2030-08", "base_salary": 0})
    assert r.status_code == 200
    assert r.json()["base_salary"] == 5000
    assert r.json()["net"] == 5000

    # صافي سالب → 400
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": sid, "period": "2030-09", "base_salary": 100,
        "deduction": 500})
    assert r.status_code == 400 and "سالب" in r.json()["detail"]

    # موظف غير موجود → 404
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": 999999, "period": "2030-10", "base_salary": 100})
    assert r.status_code == 404

    # التحديث يعيد حساب الصافي
    r = client.put(f"/payroll/{pid}", headers=admin, json={"bonus": 700})
    assert r.status_code == 200
    assert r.json()["net"] == 5400  # 5000 + 700 - 300

    # الصرف
    r = client.post(f"/payroll/{pid}/pay", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "paid" and d["paid_at"] is not None

    # صرف مكرر → 400
    r = client.post(f"/payroll/{pid}/pay", headers=admin)
    assert r.status_code == 400 and "بالفعل" in r.json()["detail"]

    # الفلترة بالحالة والفترة
    r = client.get("/payroll/", headers=admin,
                   params={"status": "paid", "period": "2030-07"})
    assert any(e["id"] == pid for e in r.json())

    # الحذف
    r = client.delete(f"/payroll/{pid}", headers=admin)
    assert r.status_code == 204


# ================= سجل التدقيق =================
def test_audit_log_records_mutations(client, admin):
    pat = _make_patient(client, admin)  # عملية POST تُسجَّل

    r = client.get("/audit-logs/", headers=admin, params={"limit": 200})
    assert r.status_code == 200
    logs = r.json()
    assert all(l["method"] != "GET" for l in logs)
    hit = [l for l in logs
           if l["method"] == "POST" and l["path"].startswith("/patients")
           and l["username"] == "admin" and l["status_code"] == 200]
    assert hit, "لم يُسجَّل إنشاء المريض في سجل التدقيق"

    # فلترة بالمسار/الطريقة
    r = client.get("/audit-logs/", headers=admin,
                   params={"method": "POST", "username": "admin"})
    assert r.status_code == 200
    assert all(l["method"] == "POST" and l["username"] == "admin"
               for l in r.json())
