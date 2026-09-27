"""سيناريو الطوارئ الكامل كما طلبه صاحب النظام، من أول خطوة إلى آخرها:

مريض يدخل الطوارئ ⇒ صاحب النوبة يفتح له ملفًا ⇒ يُوجَّه للتحصيل بفاتورة
تجمع الكشفية وبنود الفحوصات ⇒ تظهر معلوماته للمختبر فورًا وعليها شارة
«بانتظار التحصيل» ويُمنع تنفيذها قبل الدفع مع تنبيه لصاحب التحصيل ⇒
بعد الدفع تُدخل النتيجة ⇒ يسجّل الطبيب العلاج ⇒ تظهر الوصفة للصيدلية.
"""
from test_advanced import _make_linked_doctor
from test_api import uid


def _patient(client, admin):
    s = uid()
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض طوارئ {s}",
        "gender": "ذكر",
        "date_of_birth": "1992-04-11",
        "phone": f"055{s[:7]}",
        "email": f"er_{s}@test.com",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _open_case(client, admin, pid, fee=50.0):
    r = client.post("/service-units/emergency", headers=admin, json={
        "patient_id": pid,
        "complaint": "ألم شديد بالبطن مع غثيان",
        "triage_level": "urgent",
        "arrival_at": "2026-09-27T09:30:00",
        "consult_fee": fee,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _case_orders(client, admin, case_id):
    orders = client.get("/lab-orders/", headers=admin).json()
    return [o for o in orders if o.get("emergency_case_id") == case_id]


def test_lab_catalog_is_seeded_and_grouped(client, admin):
    """الدليل مزروع ومصنَّف: دم/بول/براز… وأنواع الأشعة — لا يبقى فارغًا."""
    rows = client.get("/lab-tests/", headers=admin).json()
    assert len(rows) >= 150, f"الدليل زُرع {len(rows)} صفًّا فقط"

    groups = {t.get("specimen_group") for t in rows}
    assert {"blood", "serum", "urine", "stool", "hormones"} <= groups, groups
    assert {"xray", "ct", "mri", "ultrasound"} <= groups, groups
    assert {t["category"] for t in rows} == {"lab", "radiology"}
    assert all(t["code"] and t["name"] for t in rows)

    # البذر idempotent: إعادة تشغيله لا يضاعف أي صف
    from main import seed_lab_catalog_data
    assert seed_lab_catalog_data() == 0


def test_emergency_workflow_end_to_end(client, admin):
    """الطوارئ: ملف ← طرح الفحوصات ← تحصيل ← بوابة الدفع ← النتيجة ← العلاج."""
    pid = _patient(client, admin)
    case = _open_case(client, admin, pid, fee=50.0)
    assert case["consult_fee"] == 50.0 and case["status"] == "arrived"
    assert case["invoice_id"] is None and case["record_id"] is None

    rows = client.get("/lab-tests/", headers=admin).json()
    blood = next(t for t in rows if t.get("specimen_group") == "blood")
    xray = next(t for t in rows
                if t.get("specimen_group") == "xray" and t["category"] == "radiology")

    # صاحب النوبة (طبيب مرتبط بحسابه) يطلب الفحوصات من الدليل المصنَّف
    _, doc_h = _make_linked_doctor(client, admin, "erdoc")
    r = client.post(f"/service-units/emergency/{case['id']}/orders",
                    headers=doc_h, json={"lines": [
                        {"lab_test_id": blood["id"], "priority": "stat"},
                        {"lab_test_id": xray["id"]},
                    ]})
    assert r.status_code == 200, r.text
    summary = r.json()
    assert len(summary["lab_orders"]) == 2
    assert summary["payment_status"] == "unbilled"
    assert all(not o["billed"] for o in summary["lab_orders"])
    # تُسند لطبيب النوبة الذي فتح الملف
    assert summary["case"]["doctor_id"] is not None

    # صاحب التحصيل يفتح فاتورة واحدة: كشفية + ما لم يُفوتر من الفحوصات
    r = client.post(f"/service-units/emergency/{case['id']}/checkout",
                    headers=admin, json={"consult_fee": 50})
    assert r.status_code == 200, r.text
    bill = r.json()
    assert bill["payment_status"] == "unpaid"
    kinds = {ln["kind"] for ln in bill["lines"]}
    assert kinds == {"visit", "lab", "radiology"}, kinds
    assert bill["billed_total"] == round(50 + blood["price"] + xray["price"], 2)
    assert bill["due"] == bill["billed_total"]
    inv_id = bill["invoice_id"]
    assert bill["case"]["invoice_id"] == inv_id

    # إيصال مفصّل: البنود نفسها في الفاتورة ومجموعها يساوي المبلغ
    inv = client.get(f"/invoices/{inv_id}", headers=admin).json()
    assert len(inv["lines"]) == 3
    assert inv["lines_total"] == inv["amount"] == bill["billed_total"]
    assert inv["status"] == "unpaid"

    # المختبر يرى الطلبين فورًا وعليهما شارة انتظار التحصيل (المرونة)
    mine = _case_orders(client, admin, case["id"])
    assert len(mine) == 2
    assert all(o["payment_pending"] for o in mine)
    lab_order = next(o for o in mine if o["test_type"] == "lab")

    # لكن التنفيذ محجوب قبل الدفع — 402
    r = client.post(f"/lab-orders/{lab_order['id']}/collect", headers=admin,
                    json={"specimen_type": "دم"})
    assert r.status_code == 402, r.text
    assert "بانتظار التحصيل" in r.json()["detail"]

    # وتنبيه يبقى غير مقروء عند صاحب التحصيل
    r = client.get("/notifications/", headers=admin,
                   params={"unread_only": True, "limit": 200})
    notes = r.json()
    assert any(f"تحصيل طوارئ #{case['id']}" in (n["title"] or "") for n in notes)

    # التحصيل يفتح التنفيذ
    r = client.post(f"/invoices/{inv_id}/pay", headers=admin, json={"method": "cash"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    mine = _case_orders(client, admin, case["id"])
    assert not any(o["payment_pending"] for o in mine)

    assert client.post(f"/lab-orders/{lab_order['id']}/collect", headers=admin,
                       json={"specimen_type": "دم"}).status_code == 200
    assert client.post(f"/lab-orders/{lab_order['id']}/receive", headers=admin,
                       json={"accepted": True}).status_code == 200
    r = client.post(f"/lab-orders/{lab_order['id']}/result", headers=admin,
                    json={"result": "13.4", "value": 13.4})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"

    sm = client.get(f"/service-units/emergency/{case['id']}/summary",
                    headers=admin).json()
    assert sm["tests_ready"] == 1
    assert sm["payment_status"] == "paid" and sm["due"] == 0

    # إعادة فتح التحصيل لا تُعيد فوترة ما سبق فوترته
    r = client.post(f"/service-units/emergency/{case['id']}/checkout",
                    headers=admin, json={})
    assert r.status_code == 409, r.text
    assert "لا توجد بنود جديدة" in r.json()["detail"]

    # العلاج: سجل طبي + وصفة تظهر فورًا للصيدلية
    med = client.post("/medications/", headers=admin, json={
        "code": "ER" + uid()[:8], "name": "باراسيتامول 500",
        "quantity": 120, "price": 5.0})
    assert med.status_code in (200, 201), med.text

    r = client.post(f"/service-units/emergency/{case['id']}/treatment",
                    headers=doc_h, json={
                        "diagnosis": "التهاب زائدة دودية مبكر",
                        "treatment": "مضاد حيوي وريدي + مسكن",
                        "prescription": [{
                            "medication_id": med.json()["id"], "quantity": 10,
                            "dosage": "قرص", "frequency": "كل 8 ساعات",
                            "duration": "5 أيام",
                        }],
                    })
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["has_record"] and done["has_prescription"]
    assert done["case"]["status"] == "under_treatment"
    assert done["case"]["record_id"] and done["case"]["prescription_id"]
    assert done["case"]["diagnosis"] == "التهاب زائدة دودية مبكر"

    rx = client.get("/prescriptions/", headers=admin,
                    params={"status": "PENDING"}).json()
    assert any(p["id"] == done["case"]["prescription_id"] for p in rx)

    # السجل الطبي مرتبط بالمريض ويحمل التشخيص
    recs = client.get("/medical-records/", headers=admin,
                      params={"patient_id": pid}).json()
    assert any(r_["id"] == done["case"]["record_id"] for r_ in recs)

    # لا علاج مرّتين على الحالة نفسها
    r = client.post(f"/service-units/emergency/{case['id']}/treatment",
                    headers=doc_h, json={
                        "diagnosis": "تشخيص ثانٍ", "treatment": "علاج ثانٍ"})
    assert r.status_code == 409, r.text

    # الخروج يُغلق الحالة فلا متابعة بعده
    r = client.post(f"/service-units/emergency/{case['id']}/status",
                    headers=admin, json={"status": "discharged"})
    assert r.status_code == 200, r.text
    assert r.json()["closed_at"] is not None
    r = client.post(f"/service-units/emergency/{case['id']}/orders",
                    headers=doc_h, json={"lines": [{"test_name": "تحليل إضافي"}]})
    assert r.status_code == 409, r.text


def test_emergency_status_gate(client, admin):
    """الحالات الخمس المقبولة فقط — والواجهة تعرضهنّ لا ما يرده الخادم."""
    pid = _patient(client, admin)
    case = _open_case(client, admin, pid)

    for bad in ("cancelled", "unknown", "CLOSED"):
        r = client.post(f"/service-units/emergency/{case['id']}/status",
                        headers=admin, json={"status": bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)

    r = client.post(f"/service-units/emergency/{case['id']}/status",
                    headers=admin, json={"status": "triaged"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "triaged"

    js = client.get("/app.js").text
    # قائمة أزرار الشاشة العامة للطوارئ مطابقة حرفيًّا لما يقبله الخادم
    assert "emergency:['arrived','triaged','under_treatment','discharged','closed']" in js


def test_er_ui_markers(client):
    """علامات الواجهة: شاشة الطوارئ ومنتقي الفحوصات المصنَّف في app.js/CSS."""
    js = client.get("/app.js").text
    for marker in ("renderEr", "erOrder", "erCheckout", "erTreat", "erNewFile",
                   "testPickerHTML", "TEST_GROUP", "specimen_group",
                   "er: renderEr", "payment_pending"):
        assert marker in js, f"علامة مفقودة في app.js: {marker}"
    # المنتقي بديل القائمة المسطّحة القديمة ذات الـ290 خيارًا
    assert 'id="f-cat" value=""' in js
    css = client.get("/app.css").text
    for marker in (".er-shell", ".tp-chip", ".tp-row", ".er-item"):
        assert marker in css, f"علامة مفقودة في app.css: {marker}"
    html = client.get("/").text
    assert 'data-view="er"' in html, "رابط الطوارئ غير موجود في القائمة الجانبية"
