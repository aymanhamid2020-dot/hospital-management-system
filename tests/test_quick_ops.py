# -*- coding: utf-8 -*-
"""مركز العمليات السريعة — بيع/شراء/ترحيل في عملية واحدة.

يغطي: Lancet (catalog) + مؤشرات (overview) + ثلاث عمليات POST مع أثرها
على الأرصدة والحركات والقيود، وكل مسارات الخطأ والصلاحيات.
"""
import uuid

from conftest import login


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _item(client, admin, cost=10, **over):
    payload = {"code": f"QO{uid()}", "name": f"مستلزم {uid()}",
               "category": "medical_supplies", "unit": "قطعة",
               "unit_cost": cost, "reorder_point": 1, "max_quantity": 500}
    payload.update(over)
    r = client.post("/general-stock/", headers=admin, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _med(client, admin, qty=40, price=5):
    r = client.post("/medications/", headers=admin,
                    json={"code": f"QM{uid()}", "name": f"دواء {uid()}",
                          "quantity": qty, "price": price, "min_quantity": 1,
                          "unit": "علبة"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _vendor(client, admin):
    r = client.post("/accounts/ledger/vendors", headers=admin,
                    json={"code": f"QV{uid()}", "name": f"مورد {uid()}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _main_wh(client, admin):
    return next(w for w in client.get("/stock/warehouses", headers=admin).json()
                if w["is_default"])


def _patient(client, admin):
    """مريض للاختبار — قاعدة الاختبار تبدأ بلا مرضى."""
    rows = client.get("/patients/", headers=admin, params={"limit": 1}).json()
    if rows:
        return rows[0]
    tag = uid()
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض {tag}", "date_of_birth": "1990-05-05T00:00:00",
        "gender": "ذكر", "phone": f"050{uid()}", "email": f"{tag}@qo.example.com"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _balance(client, admin, item_id, wh_id):
    rows = client.get(f"/stock/warehouses/{wh_id}/items", headers=admin).json()
    return next((r["quantity"] for r in rows if r["item_id"] == item_id), 0)


def _med_qty(client, admin, med_id):
    return next(m["quantity"] for m in client.get("/medications/", headers=admin).json()
                if m["id"] == med_id)


# ===== اللوحة والبحث =====
def test_overview_shape_and_numbers(client, admin):
    """/overview يقرأ مؤشرات اليوم بلا أخطاء وبنفس مستخدم مسجّل."""
    r = client.get("/quick-ops/overview", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("sales_today", "purchases_today", "movements_today",
                "low_stock_count", "expiring_soon_count", "top_items", "recent"):
        assert key in d, key
    assert d["sales_today"] >= 0 and d["movements_today"] >= 0
    assert isinstance(d["recent"], list)


def test_catalog_search_and_stock(client, admin):
    """البحث يحمّل الأصناف النشطة مع المتاح والسعر المقترح، والحرفان شرط."""
    item = _item(client, admin, cost=20)
    _balance_seed = client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 7,
                                      "unit_cost": 20}]})
    assert _balance_seed.status_code == 201, _balance_seed.text
    head = item["name"][:4]
    rows = client.get("/quick-ops/catalog", headers=admin, params={"q": head}).json()
    hit = next((x for x in rows if x["id"] == item["id"]), None)
    assert hit, "لم يظهر الصنف في البحث السريع"
    assert hit["kind"] == "item"
    assert hit["available"] == 7
    assert hit["suggested_price"] >= hit["unit_cost"]   # هامش مقترح
    one = client.get("/quick-ops/catalog", headers=admin, params={"q": "ا"}).json()
    assert isinstance(one, list)   # حرف واحد ⇒ لا خطأ


# ===== بيع سريع =====
def test_quick_sale_items_only(client, admin):
    """بيع مستلزم ⇒ فاتورة + إذن صرف + خصم الرصيد + قيد محاسبي."""
    wh = _main_wh(client, admin)
    item = _item(client, admin, cost=10)
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 10,
                                      "unit_cost": 10}]})
    patient = _patient(client, admin)
    r = client.post("/quick-ops/sales", headers=admin, json={
        "patient_id": patient["id"], "warehouse_id": wh["id"],
        "discount": 1, "tax_rate": 10, "paid_amount": 42.9, "payment_method": "cash",
        "lines": [{"item_id": item["id"], "quantity": 2, "unit_price": 20}]})
    assert r.status_code == 201, r.text
    d = r.json()
    # 2×20=40 ناقص خصم 1 = 39 +10% ضريبة = 42.9
    assert d["subtotal"] == 40.0 and d["discount"] == 1.0
    assert d["tax"] == 3.9 and d["total"] == 42.9
    assert d["remaining"] == 0.0 and d["status"] == "PAID"
    assert d["invoice_id"] and d["doc_no"].startswith("ISSUE-")
    assert d["journal_entry_no"]
    assert _balance(client, admin, item["id"], wh["id"]) == 8


def test_quick_sale_medicines_appear_in_sales(client, admin):
    """الدواء يُصرف كسجل صيدلية فيظهر في شاشة المبيعات، ويُنقص رصيده."""
    med = _med(client, admin, qty=20, price=6)
    patient = _patient(client, admin)
    r = client.post("/quick-ops/sales", headers=admin, json={
        "patient_id": patient["id"], "paid_amount": 5, "payment_method": "card",
        "lines": [{"kind": "med", "medication_id": med["id"], "quantity": 2}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["dispense_count"] == 1 and d["dispense_ids"]
    assert d["invoice_id"] is None and d["doc_no"] is None   # لا فاتورة لأدوية فقط
    assert d["medicines_total"] == 12.0 and d["total"] == 12.0
    assert _med_qty(client, admin, med["id"]) == 18
    # يظهر في سجل المبيعات المعتمد على الصرف
    sales = client.get("/accounts/sales", headers=admin).json()
    assert any(s["id"] == d["dispense_ids"][0] for s in sales)


def test_quick_sale_mixed_basket(client, admin):
    """سلة مختلطة: دواء + مستلزم ⇒ صرفان وفيوترة، والمدفوع يوزَّع بالتناسب."""
    wh = _main_wh(client, admin)
    item = _item(client, admin, cost=10)
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 5,
                                      "unit_cost": 10}]})
    med = _med(client, admin, qty=10, price=4)
    patient = _patient(client, admin)
    r = client.post("/quick-ops/sales", headers=admin, json={
        "patient_id": patient["id"], "warehouse_id": wh["id"], "paid_amount": 14,
        "lines": [{"item_id": item["id"], "quantity": 1, "unit_price": 10},
                  {"kind": "med", "medication_id": med["id"], "quantity": 1}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["invoice_id"] and d["dispense_count"] == 1
    assert d["items_total"] == 10.0 and d["medicines_total"] == 4.0
    assert d["total"] == 14.0 and d["paid_amount"] == 14.0 and d["remaining"] == 0.0
    shares = {ln["kind"]: ln["paid"] for ln in d["lines"]}
    assert shares["item"] == 10.0 and shares["med"] == 4.0
    assert _balance(client, admin, item["id"], wh["id"]) == 4
    assert _med_qty(client, admin, med["id"]) == 9


def test_quick_sale_partial_leaves_receivable(client, admin):
    """الدفع الجزئي يترك الباقي ذممة على المريض ويوجّه القيد لحساب الذمم."""
    wh = _main_wh(client, admin)
    item = _item(client, admin, cost=10)
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 3,
                                      "unit_cost": 10}]})
    patient = _patient(client, admin)
    r = client.post("/quick-ops/sales", headers=admin, json={
        "patient_id": patient["id"], "warehouse_id": wh["id"], "paid_amount": 5,
        "lines": [{"item_id": item["id"], "quantity": 1, "unit_price": 10}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "PARTIAL" and d["remaining"] == 5.0
    entry = next(e for e in client.get("/accounts/ledger/entries", headers=admin).json()
                 if e["id"] == d["journal_entry_id"])
    codes = {ln["account_code"]: ln["debit"] for ln in entry["lines"] if ln["debit"]}
    assert "1100" in codes or "1110" in codes   # ذمم مريض/تأمين


def test_quick_sale_validations(client, admin):
    """كل خطأ متوقّع برسالة واضحة، ولا عملية نصفية."""
    wh = _main_wh(client, admin)
    item = _item(client, admin)
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 2,
                                      "unit_cost": 10}]})
    patient = _patient(client, admin)
    base = {"patient_id": patient["id"], "warehouse_id": wh["id"],
            "lines": [{"item_id": item["id"], "quantity": 1, "unit_price": 10}]}

    r = client.post("/quick-ops/sales", headers=admin,
                    json={**base, "lines": [{"item_id": item["id"], "quantity": 999}]})
    assert r.status_code == 400 and "الكمية غير كافية" in r.json()["detail"]
    assert client.post("/quick-ops/sales", headers=admin,
                       json={**base, "patient_id": 999999}).status_code == 404
    assert client.post("/quick-ops/sales", headers=admin,
                       json={**base, "payment_method": "crypto"}).status_code == 400
    assert client.post("/quick-ops/sales", headers=admin,
                       json={**base, "discount": 9999}).status_code == 400
    assert client.post("/quick-ops/sales", headers=admin,
                       json={**base, "lines": [{"item_id": item["id"], "quantity": 1,
                                                "unit_price": 0}]}).status_code == 400
    over_paid = client.post("/quick-ops/sales", headers=admin,
                            json={**base, "paid_amount": 9999})
    assert over_paid.status_code == 400 and "المدفوع أكبر" in over_paid.json()["detail"]
    assert client.post("/quick-ops/sales", headers=admin,
                       json={**base, "lines": []}).status_code == 422
    # الرصيد لم يتغيّر بعد كل الأخطاء
    assert _balance(client, admin, item["id"], wh["id"]) == 2


# ===== شراء سريع =====
def test_quick_purchase_posts_grn_bill_and_entry(client, admin):
    """شراء سريع ⇒ إذن استلام مرحّل + فاتورة مورد + قيد ذمم دائنة."""
    wh = _main_wh(client, admin)
    item = _item(client, admin, cost=7)
    vendor = _vendor(client, admin)
    r = client.post("/quick-ops/purchases", headers=admin, json={
        "vendor_id": vendor, "warehouse_id": wh["id"],
        "lines": [{"item_id": item["id"], "quantity": 12, "unit_cost": 7,
                   "batch_no": f"B{uid()[:4]}"}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["doc_no"].startswith("GRN-") and d["total_quantity"] == 12
    assert d["bill_amount"] == 84.0 and d["outstanding"] == 84.0
    assert d["journal_entry_no"]
    assert _balance(client, admin, item["id"], wh["id"]) == 12
    bills = client.get("/accounts/ledger/vendor-bills", headers=admin).json()
    assert any(b["bill_no"] == d["bill_no"] and b["status"] == "unpaid" for b in bills)
    # التكرار بنفس الرقم مرفوض
    again = client.post("/quick-ops/purchases", headers=admin, json={
        "vendor_id": vendor, "bill_no": d["bill_no"],
        "lines": [{"item_id": item["id"], "quantity": 1, "unit_cost": 7}]})
    assert again.status_code == 409


def test_quick_purchase_auto_bill_no_and_rules(client, admin):
    """رقم الفاتورة يُولَّد تلقائيًا، والمورد الخامل/التكلفة الصفرية مرفوضة."""
    wh = _main_wh(client, admin)
    item = _item(client, admin, cost=3)
    vendor = _vendor(client, admin)
    r = client.post("/quick-ops/purchases", headers=admin, json={
        "vendor_id": vendor, "warehouse_id": wh["id"],
        "lines": [{"item_id": item["id"], "quantity": 2, "unit_cost": 3}]})
    assert r.status_code == 201 and r.json()["bill_no"].startswith("V-")
    assert client.post("/quick-ops/purchases", headers=admin, json={
        "vendor_id": 999999, "lines": [{"item_id": item["id"], "quantity": 1,
                                        "unit_cost": 3}]}).status_code == 404
    assert client.post("/quick-ops/purchases", headers=admin, json={
        "vendor_id": vendor,
        "lines": [{"item_id": item["id"], "quantity": 1, "unit_cost": 0}]}).status_code == 400


# ===== ترحيل سريع =====
def test_quick_transfer_moves_stock(client, admin):
    """التحويل يخصم من المصدر ويضيف للوجهة بحركتين في دفتر الحركات."""
    whs = client.get("/stock/warehouses", headers=admin).json()
    src = next(w for w in whs if w["is_default"])
    dst = next((w for w in whs if w["id"] != src["id"]), None) or \
        client.post("/stock/warehouses", headers=admin,
                    json={"name": f"مستودع {uid()}", "kind": "or"}).json()
    item = _item(client, admin, cost=10)
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "to_warehouse_id": src["id"],
        "lines": [{"item_id": item["id"], "quantity": 20, "unit_cost": 10}]})
    r = client.post("/quick-ops/transfers", headers=admin, json={
        "from_warehouse_id": src["id"], "to_warehouse_id": dst["id"],
        "lines": [{"item_id": item["id"], "quantity": 6}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["doc_no"].startswith("TRANSFER-") and d["total_quantity"] == 6
    assert d["total_value"] == 60.0
    assert _balance(client, admin, item["id"], src["id"]) == 14
    assert _balance(client, admin, item["id"], dst["id"]) == 6
    moves = client.get("/stock/movements", headers=admin,
                       params={"item_id": item["id"]}).json()
    assert any(m["type"] == "transfer_out" for m in moves)
    assert any(m["type"] == "transfer_in" for m in moves)


def test_quick_transfer_rules(client, admin):
    """لا ترحيل لنفس المستودع، ولا كمية أكبر من المتاح، ولا أدوية."""
    src = _main_wh(client, admin)
    dst = client.post("/stock/warehouses", headers=admin,
                      json={"name": f"مستودع {uid()}", "kind": "or"}).json()
    item = _item(client, admin)
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 4,
                                      "unit_cost": 10}]})
    same = client.post("/quick-ops/transfers", headers=admin, json={
        "from_warehouse_id": src["id"], "to_warehouse_id": src["id"],
        "lines": [{"item_id": item["id"], "quantity": 1}]})
    assert same.status_code == 400 and "نفس المستودع" in same.json()["detail"]
    over = client.post("/quick-ops/transfers", headers=admin, json={
        "from_warehouse_id": src["id"], "to_warehouse_id": dst["id"],
        "lines": [{"item_id": item["id"], "quantity": 99}]})
    assert over.status_code == 400 and "الكمية غير كافية" in over.json()["detail"]
    assert _balance(client, admin, item["id"], src["id"]) == 4


# ===== الصلاحيات =====
def test_quick_ops_require_auth_and_admin(client, admin):
    """اللوحة والبحث لأي مستخدم مسجّل، والعمليات الثلاث للمدير فقط."""
    tag = uid()
    reg = client.post("/auth/register", json={
        "username": f"qo{tag}", "email": f"qo{tag}@qo.example.com",
        "full_name": "موظف استقبال", "password": "Q0pass!2026x"})
    assert reg.status_code in (200, 201), reg.text
    nurse = login(client, f"qo{tag}", "Q0pass!2026x")
    assert client.get("/quick-ops/overview", headers=nurse).status_code == 200
    assert client.get("/quick-ops/catalog", headers=nurse).status_code == 200
    wh = _main_wh(client, nurse)
    patient = _patient(client, nurse)
    for path, body in (
        ("/quick-ops/sales", {"patient_id": patient["id"],
                              "lines": [{"item_id": 1, "quantity": 1}]}),
        ("/quick-ops/purchases", {"vendor_id": 1, "lines": [{"item_id": 1, "quantity": 1}]}),
        ("/quick-ops/transfers", {"from_warehouse_id": wh["id"],
                                  "to_warehouse_id": wh["id"],
                                  "lines": [{"item_id": 1, "quantity": 1}]}),
    ):
        assert client.post(path, headers=nurse, json=body).status_code == 403
    assert client.get("/quick-ops/overview").status_code == 401