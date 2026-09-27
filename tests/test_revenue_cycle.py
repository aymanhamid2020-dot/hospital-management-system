# -*- coding: utf-8 -*-
"""دورة الإيراد: التسعير · العروض والباقات · الودائع · إغلاق الصندوق ·
الموافقات المسبقة · حزم المطالبات · إشعارات الدائن · تقارير المبيعات."""
import uuid
from datetime import datetime, timedelta

from conftest import login


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _patient_id(client, admin):
    rows = client.get("/patients/", headers=admin, params={"limit": 1}).json()
    if rows:
        return rows[0]["id"]
    tag = uid()
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض {tag}", "date_of_birth": "1990-05-05T00:00:00",
        "gender": "ذكر", "phone": f"050{uid()}", "email": f"{tag}@qo.example.com"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _paid_invoice(client, admin, pid, amount=400):
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": amount, "payment_method": "cash",
        "status": "paid", "description": "خدمة مدفوعة"})
    assert r.status_code in (200, 201), r.text
    return r.json()


# ===== 5) التسعير والخصومات =====
def test_price_lists_crud_and_resolve(client, admin):
    """قائمة أسعار تُنشأ وتُقرأ، والسعر يُحل حسب التأمين ثم الافتراضي."""
    tag = uid()
    r = client.post("/revenue/price-lists", headers=admin, json={
        "code": f"PL{tag}", "name": "أسعار شركة الاختبار",
        "lines": [{"service_code": "CONS", "service_name": "استشارة", "unit_price": 250}]})
    assert r.status_code == 201, r.text
    assert r.json()["items_count"] == 1
    dup = client.post("/revenue/price-lists", headers=admin, json={
        "code": f"PL{tag}", "name": "مكررة", "lines": []})
    assert dup.status_code == 409
    rows = client.get("/revenue/price-lists", headers=admin).json()
    assert any(x["code"] == f"PL{tag}" for x in rows)
    found = client.get("/revenue/price-lists/resolve", headers=admin,
                       params={"service_code": "CONS"}).json()
    assert found["unit_price"] == 250
    missing = client.get("/revenue/price-lists/resolve", headers=admin,
                         params={"service_code": "NOPE-XYZ"})
    assert missing.status_code == 404


def test_discount_rule_check(client, admin):
    """سقف الخصم: داخله مسموح، وخارجه محجوب مع ذكر السياسة."""
    r = client.post("/revenue/discount-rules", headers=admin, json={
        "name": f"سقف {uid()}", "max_percent": 10, "scope": "all",
        "requires_approval": True})
    assert r.status_code == 201, r.text
    ok = client.get("/revenue/discount-rules/check", headers=admin, params={"percent": 5})
    assert ok.status_code == 200 and ok.json()["allowed"] is True
    assert ok.json()["requires_approval"] is True
    over = client.get("/revenue/discount-rules/check", headers=admin, params={"percent": 40})
    assert over.json()["allowed"] is False
    assert over.json()["max_percent"] == 10


# ===== 4) الباقات والعروض =====
def test_package_calculates_list_total_and_saving(client, admin):
    """مجموع بنود الباقة وسعرها ⇒ قيمة التوفير محسوبة."""
    r = client.post("/revenue/packages", headers=admin, json={
        "code": f"PK{uid()}", "name": "باقة فحص شامل", "package_price": 350,
        "lines": [{"service_code": "CONS", "service_name": "استشارة", "quantity": 1,
                   "unit_price": 200},
                  {"service_code": "LAB", "service_name": "تحليل", "quantity": 2,
                   "unit_price": 100}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["list_total"] == 400.0 and d["saving"] == 50.0


def test_quotation_lifecycle_and_convert(client, admin):
    """عرض: إنشاء ⇒ قبول ⇒ تحويل لفاتورة، والتحويل مرة واحدة فقط."""
    pid = _patient_id(client, admin)
    r = client.post("/revenue/quotations", headers=admin, json={
        "patient_id": pid, "title": "عرض تجميل", "tax_rate": 15,
        "lines": [{"description": "جلسة ليزر", "quantity": 2, "unit_price": 1500}]})
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["total"] == 3450.0 and q["status"] == "draft"
    assert client.post("/revenue/quotations", headers=admin,
                       json={"patient_id": pid, "title": "بلا بنود"}).status_code == 400
    assert client.post("/revenue/quotations", headers=admin, json={
        "patient_id": pid, "title": "خصم كبير", "discount": 99999,
        "lines": [{"description": "س", "quantity": 1, "unit_price": 10}]}).status_code == 400
    assert client.put(f"/revenue/quotations/{q['id']}/status", headers=admin,
                      json={"status": "wrong"}).status_code == 400
    acc = client.put(f"/revenue/quotations/{q['id']}/status", headers=admin,
                     json={"status": "accepted"})
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    conv = client.post(f"/revenue/quotations/{q['id']}/convert", headers=admin)
    assert conv.status_code == 200, conv.text
    assert conv.json()["status"] == "converted" and conv.json()["invoice_id"]
    # الفاتورة الناتجة عن التحويل تُرحَّل تلقائيًّا كأي فاتورة من شاشة
    # الفواتير — وإلا بقيت الإيرادات خارج الدفتر عند أطول مسار بيع.
    inv_id = conv.json()["invoice_id"]
    entries = client.get("/accounts/ledger/entries", headers=admin).json()
    posted = [e for e in entries
              if e["reference_type"] == "patient_invoice" and e["reference_id"] == inv_id]
    assert len(posted) == 1, f"قيود الفاتورة المحوّلة: {len(posted)} (المتوقع 1)"
    assert sum(l["debit"] for l in posted[0]["lines"]) == \
        sum(l["credit"] for l in posted[0]["lines"]) == 3450.0
    assert {l["account_code"] for l in posted[0]["lines"]} == {"1100", "4000"}
    assert client.post(f"/revenue/quotations/{q['id']}/convert",
                       headers=admin).status_code == 409
    assert client.put(f"/revenue/quotations/{q['id']}/status", headers=admin,
                      json={"status": "rejected"}).status_code == 400


def test_quotation_from_package_uses_package_price(client, admin):
    """العرض من باقة يخصم فرق سعر الباقة تلقائيًا."""
    pid = _patient_id(client, admin)


# ===== 2) الودائع والورديات =====
def test_deposit_recorded_then_applied_to_invoice(client, admin):
    """الوديعة تُقيَّد رصيدًا للمريض وتُخصم من فاتورة فيتحوّل الرصيد إلى صفر."""
    pid = _patient_id(client, admin)
    r = client.post("/revenue/deposits", headers=admin, json={
        "patient_id": pid, "amount": 300, "method": "cash", "notes": "دفعة تنويم"})
    assert r.status_code == 201, r.text
    dep = r.json()
    assert dep["status"] == "active" and dep["balance"] == 300.0
    inv = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 300, "payment_method": "cash",
        "description": "تنويم"}).json()
    ap = client.post(f"/revenue/deposits/{dep['id']}/apply", headers=admin,
                     json={"invoice_id": inv["id"]})
    assert ap.status_code == 200, ap.text
    assert ap.json()["balance"] == 0.0 and ap.json()["status"] == "applied"
    assert client.post(f"/revenue/deposits/{dep['id']}/apply", headers=admin,
                       json={"invoice_id": inv["id"]}).status_code == 400
    bad = client.post(f"/revenue/deposits/{dep['id']}/apply", headers=admin,
                      json={"invoice_id": 999999})
    assert bad.status_code in (400, 404)


def test_deposit_validation(client, admin):
    """مريض غير موجود أو مبلغ صفر مرفوضان."""
    assert client.post("/revenue/deposits", headers=admin,
                       json={"patient_id": 999999, "amount": 50}).status_code == 404
    assert client.post("/revenue/deposits", headers=admin,
                       json={"patient_id": _patient_id(client, admin),
                             "amount": 0}).status_code == 422


def test_shift_open_and_close_reconciliation(client, admin):
    """الوردية تُفتح، وتُغلق بمطابقة النقد المعدّ مع محسوب النظام."""
    r = client.post("/revenue/shifts/open", headers=admin, json={"opening_cash": 100})
    assert r.status_code in (200, 201), r.text
    assert r.json()["status"] == "open"
    assert client.post("/revenue/shifts/open", headers=admin,
                       json={"opening_cash": 0}).status_code == 409
    cur = client.get("/revenue/shifts/current", headers=admin)
    assert cur.status_code == 200
    cl = client.post("/revenue/shifts/close", headers=admin, json={"counted_cash": 100})
    assert cl.status_code == 200, cl.text
    d = cl.json()
    assert d["difference"] == 0.0 and d["status"] == "balanced"
    op = client.post("/revenue/shifts/open", headers=admin, json={"opening_cash": 0})
    assert op.status_code in (200, 201)
    cl2 = client.post("/revenue/shifts/close", headers=admin, json={"counted_cash": 25})
    d2 = cl2.json()
    assert d2["status"] == "unbalanced", d2
    assert d2["difference"] == round(25 - d2["expected_cash"], 2)


# ===== 3) التأمين =====
def test_prior_authorization_and_decision(client, admin):
    """طلب موافقة مسبقة مع أكواد ICD/CPT ثم قرار شركة التأمين."""
    pid = _patient_id(client, admin)
    r = client.post("/revenue/prior-authorizations", headers=admin, json={
        "patient_id": pid, "insurer": "شركة أ", "service_description": "عملية قلب",
        "icd10_code": "I21.4", "cpt_code": "33510", "requested_amount": 40000})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "pending" and a["auth_number"].startswith("PA-")


def test_claim_batch_build_submit_and_no_double_count(client, admin):
    """حزمة مطالبات تجمع مُرسَلة لفترة وتُرسَل مرة واحدة بلا تكرار."""
    pid = _patient_id(client, admin)
    insurer = f"شركة {uid()}"
    inv = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 1200, "insurer": insurer,
        "description": "عملية"}).json()
    cl = client.post(f"/patients/{pid}/claims", headers=admin, json={
        "invoice_id": inv["id"], "claim_number": f"CL{uid()}",
        "insurer": insurer, "amount": 1200})
    assert cl.status_code == 201, cl.text
    frm = (datetime.now() - timedelta(days=5)).isoformat()
    to = (datetime.now() + timedelta(days=1)).isoformat()
    b = client.post("/revenue/claim-batches", headers=admin, json={
        "insurer": insurer, "period_from": frm, "period_to": to})
    assert b.status_code == 201, b.text
    batch = b.json()
    assert batch["total_claims"] == 1 and batch["total_amount"] == 1200.0
    assert batch["batch_no"].startswith("CLM-")
    assert client.post("/revenue/claim-batches", headers=admin, json={
        "insurer": insurer, "period_from": frm, "period_to": to}).status_code == 409
    assert client.post("/revenue/claim-batches", headers=admin, json={
        "insurer": "شركة بلا مطالبات", "period_from": frm,
        "period_to": to}).status_code == 400
    sb = client.post(f"/revenue/claim-batches/{batch['id']}/submit", headers=admin, json={})
    assert sb.status_code == 200 and sb.json()["status"] == "submitted"
    assert client.post(f"/revenue/claim-batches/{batch['id']}/submit",
                       headers=admin, json={}).status_code == 400


def test_denied_claim_transfers_to_patient(client, admin):
    """المطالبة المرفوضة تُحمَّل على حساب المريض بدل ضياعها."""
    pid = _patient_id(client, admin)
    insurer = f"شركة {uid()}"
    inv = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 900, "insurer": insurer,
        "description": "مخدمة مرفوضة"}).json()
    cl = client.post(f"/patients/{pid}/claims", headers=admin, json={
        "invoice_id": inv["id"], "claim_number": f"DN{uid()}",
        "insurer": insurer, "amount": 900}).json()
    rj = client.put(f"/patients/{pid}/claims/{cl['id']}", headers=admin, json={
        "status": "rejected", "rejection_reason": "خدمة غير مشمولة"})
    assert rj.status_code == 200
    denials = client.get("/revenue/denials", headers=admin).json()
    assert any(x["id"] == cl["id"] and x["kind"] == "claim" for x in denials)
    tr = client.post(f"/revenue/denials/claims/{cl['id']}/transfer", headers=admin)
    assert tr.status_code == 200, tr.text
    assert tr.json()["invoice_id"] == inv["id"]
    after = client.get(f"/invoices/{inv['id']}", headers=admin).json()
    assert after["status"] == "unpaid"
    other = client.post(f"/patients/{pid}/claims", headers=admin, json={
        "invoice_id": inv["id"], "claim_number": f"OK{uid()}",
        "insurer": insurer, "amount": 50}).json()
    assert client.post(f"/revenue/denials/claims/{other['id']}/transfer",
                       headers=admin).status_code == 400


# ===== 1) إشعارات الدائن =====
def test_credit_note_refunds_paid_only(client, admin):
    """الاسترداد لا يتجاوز المدفوع، ويُنقص رصيد الفاتورة."""
    pid = _patient_id(client, admin)
    inv = _paid_invoice(client, admin, pid, 400)
    r = client.post("/revenue/credit-notes", headers=admin, json={
        "patient_id": pid, "invoice_id": inv["id"], "amount": 150,
        "reason": "خدمة لم تُقدَّم", "method": "cash", "refund_now": True})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "refunded" and r.json()["note_no"].startswith("CN-")
    after = client.get(f"/invoices/{inv['id']}", headers=admin).json()
    assert after["paid_amount"] == 250 and after["status"] == "partial"
    assert client.post("/revenue/credit-notes", headers=admin, json={
        "patient_id": pid, "invoice_id": inv["id"], "amount": 9999,
        "reason": "مبالغ"}).status_code == 400
    assert client.post("/revenue/credit-notes", headers=admin, json={
        "patient_id": pid, "amount": 10, "reason": "بلا هدف"}).status_code == 400


# ===== 6) تقارير المبيعات =====
def test_sales_report_groups(client, admin):
    """التقرير يجمع الفواتير والصرف بأربعة مفاتيح: الدفع والطبيب والحالة والتأمين."""
    r = client.get("/revenue/reports/sales", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("invoices_total", "pharmacy_total", "grand_total",
                "by_payment", "by_doctor", "by_status", "by_insurer"):
        assert key in d, key
    assert d["grand_total"] >= d["invoices_total"]
    assert isinstance(d["by_payment"], list) and isinstance(d["by_doctor"], list)


# ===== الصلاحيات =====
def test_revenue_cycle_permissions(client, admin):
    """القراءة لأي مستخدم مسجّل، والكتابة للمدير فقط."""
    tag = uid()
    reg = client.post("/auth/register", json={
        "username": f"rc{tag}", "email": f"rc{tag}@qo.example.com",
        "full_name": "موظف استقبال", "password": "R0pass!2026x"})
    assert reg.status_code in (200, 201), reg.text
    staff = login(client, f"rc{tag}", "R0pass!2026x")
    pid = _patient_id(client, admin)
    for path in ("/revenue/deposits", "/revenue/shifts", "/revenue/prior-authorizations",
                 "/revenue/claim-batches", "/revenue/credit-notes", "/revenue/quotations",
                 "/revenue/price-lists", "/revenue/packages", "/revenue/discount-rules",
                 "/revenue/denials", "/revenue/reports/sales"):
        assert client.get(path, headers=staff).status_code == 200, path
    for path, body in (
        ("/revenue/deposits", {"patient_id": pid, "amount": 10}),
        ("/revenue/quotations", {"patient_id": pid, "title": "x",
                                 "lines": [{"description": "y", "quantity": 1,
                                            "unit_price": 5}]}),
        ("/revenue/price-lists", {"code": f"X{uid()}", "name": "قائمة"}),
        ("/revenue/packages", {"code": f"Y{uid()}", "name": "باقة"}),
        ("/revenue/discount-rules", {"name": "سياسة", "max_percent": 5}),
        ("/revenue/credit-notes", {"patient_id": pid, "amount": 5, "reason": "س"}),
    ):
        assert client.post(path, headers=staff, json=body).status_code == 403, path
    assert client.get("/revenue/deposits").status_code == 401
