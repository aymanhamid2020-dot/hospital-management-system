"""إدارة المخازن المتقدّمة — مستودعات ومستندات (استلام/تحويل/صرف/مرتجع/جرد) ومشتريات.

المستودع الرئيسي يُنشأ تلقائيًا عند أول طلب، فالاختبار يبني عليه ولا يفترض
وجودًا مسبقًا (قاعدة الاختبار مشتركة بين الملفات).
"""
import uuid
from datetime import datetime, timedelta

from conftest import login


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _iso(days: int = 0) -> str:
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


def _item(client, admin, **over):
    payload = {"code": f"GS{uid()}", "name": f"مستلزم {uid()}",
               "category": "medical_supplies", "unit": "قطعة",
               "unit_cost": 10, "min_quantity": 5, "quantity": 0}
    payload.update(over)
    r = client.post("/general-stock/", headers=admin, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _warehouse(client, admin, name, kind="main"):
    r = client.post("/stock/warehouses", headers=admin,
                    json={"name": f"{name} {uid()}", "kind": kind})
    assert r.status_code == 201, r.text
    return r.json()


def _grn(client, admin, item_id, qty=50, **line):
    body = {"item_id": item_id, "quantity": qty, "unit_cost": 10}
    body.update(line)
    r = client.post("/stock/docs", headers=admin,
                    json={"doc_type": "grn", "lines": [body]})
    assert r.status_code == 201, r.text
    return r.json()


def _balance(client, admin, item_id, wh_id):
    rows = client.get(f"/stock/warehouses/{wh_id}/items", headers=admin).json()
    return next((r["quantity"] for r in rows if r["item_id"] == item_id), 0)


def _default_wh(client, admin):
    return next(w for w in client.get("/stock/warehouses", headers=admin).json()
                if w["is_default"])


def test_warehouses_crud_and_rules(client, admin):
    """المستودع الأول افتراضي، والاسم فريد، ولا حذف لمستودع فيه أرصدة."""
    first = _default_wh(client, admin)          # المستودع الرئيسي (يُنشأ عند أول طلب)
    other = _warehouse(client, admin, "مستودع العمليات", kind="or")
    assert other["name"].startswith("مستودع العمليات")
    assert other["kind"] == "or" and other["items_count"] == 0
    assert other["is_default"] is False and first["is_default"] is True

    # تكرار الاسم ⇒ 409 ، ومعرّف غير موجود ⇒ 404 (اسم صالح الطول)
    assert client.post("/stock/warehouses", headers=admin,
                       json={"name": other["name"], "kind": "main"}).status_code == 409
    assert client.put("/stock/warehouses/999999", headers=admin,
                      json={"name": "اسم غير موجود"}).status_code == 404
    assert client.delete("/stock/warehouses/999999", headers=admin).status_code == 404

    # أرصدة المستودع تُعرض بالحدود وقيمة الصنف — والاستلام دخل الافتراضي لا الآخر
    item = _item(client, admin, unit_cost=12, min_quantity=3)
    _grn(client, admin, item["id"], qty=9)
    assert client.get(f"/stock/warehouses/{other['id']}/items",
                      headers=admin).json() == []

    rows = client.get(f"/stock/warehouses/{first['id']}/items", headers=admin).json()
    mine = next(r for r in rows if r["item_id"] == item["id"])
    assert mine["quantity"] == 9 and mine["below_min"] is False
    assert mine["value"] == round(9 * 12, 2)

    # مستودع فيه رصيد لا يُحذف، وكذلك الافتراضي
    assert client.delete(f"/stock/warehouses/{first['id']}",
                         headers=admin).status_code == 400

    # تعديل المستودع، والمستودع المعطّل لا يُقبل كمستودع استلام
    r = client.put(f"/stock/warehouses/{other['id']}", headers=admin,
                   json={"name": f"مخزن الطوارئ {uid()}", "is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "to_warehouse_id": other["id"],
        "lines": [{"item_id": item["id"], "quantity": 1}]}).status_code == 400


def test_grn_records_batch_movement_and_expiry(client, admin):
    """إذن الاستلام: يرفع الرصيد وينشئ دفعة برقم التشغيلة وتاريخ الانتهاء."""
    item = _item(client, admin, unit_cost=20, min_quantity=5)
    wh = _default_wh(client, admin)
    doc = _grn(client, admin, item["id"], qty=40, batch_no=f"B{uid()}",
               expiry_date=_iso(120), unit_cost=20)

    assert doc["doc_type"] == "grn" and doc["status"] == "completed"
    assert doc["doc_no"].startswith("GRN-")
    assert doc["total_quantity"] == 40 and doc["total_value"] == 800.0
    assert doc["lines"][0]["batch_no"] and doc["lines"][0]["item_name"]

    assert _balance(client, admin, item["id"], wh["id"]) == 40
    row = next(i for i in client.get("/general-stock/", headers=admin).json()
               if i["id"] == item["id"])
    assert row["quantity"] == 40 and row["expiry_date"] is not None

    # بطاقة الصنف: دفعة واحدة + حركة استلام مرتبطة بالمستند
    card = client.get(f"/stock/items/{item['id']}/card", headers=admin).json()
    assert len(card["batches"]) == 1 and card["batches"][0]["quantity"] == 40
    assert card["batches"][0]["batch_no"] == doc["lines"][0]["batch_no"]
    assert "grn" in [m["type"] for m in card["movements"]]
    assert card["movements"][0]["doc_no"] == doc["doc_no"]

    # نفس رقم التشغيلة يدمج في الدفعة نفسها
    _grn(client, admin, item["id"], qty=5, batch_no=doc["lines"][0]["batch_no"],
         expiry_date=_iso(120))
    card = client.get(f"/stock/items/{item['id']}/card", headers=admin).json()
    assert len(card["batches"]) == 1 and card["batches"][0]["quantity"] == 45


def test_transfer_moves_stock_between_warehouses(client, admin):
    """التحويل ينقص المصدر ويزيد الوجهة بحركتين، ويرفض نقص الكمية أو تكرار المخزن."""
    item = _item(client, admin)
    src = _default_wh(client, admin)
    dst = _warehouse(client, admin, "مخزن الصيدلية", kind="pharmacy")
    _grn(client, admin, item["id"], qty=30)

    r = client.post("/stock/docs", headers=admin, json={
        "doc_type": "transfer", "from_warehouse_id": src["id"],
        "to_warehouse_id": dst["id"], "notes": "تمويل الصيدلية",
        "lines": [{"item_id": item["id"], "quantity": 12}]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "completed"
    assert r.json()["doc_no"].startswith("TRANSFER-")
    assert _balance(client, admin, item["id"], src["id"]) == 18
    assert _balance(client, admin, item["id"], dst["id"]) == 12

    moves = client.get(f"/stock/movements?item_id={item['id']}",
                       headers=admin).json()
    assert [m["type"] for m in moves[:2]] == ["transfer_in", "transfer_out"]
    assert moves[0]["warehouse"] == dst["name"] and moves[1]["warehouse"] == src["name"]

    # مخزن واحد للمصدر والوجهة ⇒ 400 ، ونقص الكمية ⇒ 400 ، وصنف مجهول ⇒ 404
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "transfer", "from_warehouse_id": src["id"],
        "to_warehouse_id": src["id"],
        "lines": [{"item_id": item["id"], "quantity": 1}]}).status_code == 400
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "transfer", "from_warehouse_id": src["id"],
        "to_warehouse_id": dst["id"],
        "lines": [{"item_id": item["id"], "quantity": 999}]}).status_code == 400
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "transfer", "from_warehouse_id": src["id"],
        "to_warehouse_id": dst["id"],
        "lines": [{"item_id": 999999, "quantity": 1}]}).status_code == 404


def _department(client, admin):
    r = client.post("/departments/", headers=admin,
                    json={"name": f"قسم {uid()}", "description": "اختبار المخزون"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض {uid()}", "date_of_birth": "1992-05-05",
        "gender": "ذكر", "phone": f"0555{uid()[:5]}",
        "email": f"pt_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _vendor(client, admin):
    r = client.post("/accounts/ledger/vendors", headers=admin, json={
        "code": f"V-{uid()}", "name": f"مورد مستلزمات {uid()}", "phone": "0500000000"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_issue_to_department_and_patient_then_return(client, admin):
    """الصرف يحتاج قسمًا أو مريضًا، والمرتجع يعيد الكمية إلى المستودع."""
    item = _item(client, admin)
    wh = _default_wh(client, admin)
    dept, pat = _department(client, admin), _patient(client, admin)
    _grn(client, admin, item["id"], qty=25)

    # صرف بلا قسم ولا مريض ⇒ 400 ، بقسم غير موجود ⇒ 404
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "issue", "lines": [{"item_id": item["id"], "quantity": 1}]
    }).status_code == 400
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "issue", "department_id": 999999,
        "lines": [{"item_id": item["id"], "quantity": 1}]}).status_code == 404

    r = client.post("/stock/docs", headers=admin, json={
        "doc_type": "issue", "department_id": dept, "patient_id": pat,
        "notes": "مستلزمات غرفة العمليات",
        "lines": [{"item_id": item["id"], "quantity": 6}]})
    assert r.status_code == 201, r.text
    assert r.json()["doc_no"].startswith("ISSUE-")
    assert r.json()["status"] == "completed"
    assert _balance(client, admin, item["id"], wh["id"]) == 19

    mv = client.get(f"/stock/movements?item_id={item['id']}&type=issue",
                    headers=admin).json()[0]
    assert mv["change"] == -6 and mv["department_id"] == dept and mv["patient_id"] == pat

    # مرتجع من القسم ⇒ يعود الرصيد
    r = client.post("/stock/docs", headers=admin, json={
        "doc_type": "return", "department_id": dept, "notes": "رجوع غير مستخدم",
        "lines": [{"item_id": item["id"], "quantity": 2}]})
    assert r.status_code == 201, r.text
    assert r.json()["doc_no"].startswith("RETURN-")
    assert _balance(client, admin, item["id"], wh["id"]) == 21


def test_supplier_return_requires_vendor(client, admin):
    """مرتجع المورد ينقص الرصيد ويحتاج موردًا ومعرّفه صحيح."""
    item = _item(client, admin)
    wh = _default_wh(client, admin)
    vendor = _vendor(client, admin)
    _grn(client, admin, item["id"], qty=20)

    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "supplier_return",
        "lines": [{"item_id": item["id"], "quantity": 1}]}).status_code == 400
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "supplier_return", "vendor_id": 999999,
        "lines": [{"item_id": item["id"], "quantity": 1}]}).status_code == 404

    r = client.post("/stock/docs", headers=admin, json={
        "doc_type": "supplier_return", "vendor_id": vendor, "reference": "مرتجع-99",
        "lines": [{"item_id": item["id"], "quantity": 4}]})
    assert r.status_code == 201, r.text
    assert r.json()["vendor_name"] and r.json()["doc_no"].startswith("SUPPLIER_RETURN-")
    assert _balance(client, admin, item["id"], wh["id"]) == 16


def test_stocktake_close_posts_variance(client, admin):
    """جلسة الجرد: تقارن العدّ الفعلي بالرصيد وتقيد الفرق كتسوية عند الإغلاق."""
    item = _item(client, admin, quantity=50, unit_cost=8)   # رصيد قديم (ترحيل)
    wh = _default_wh(client, admin)

    # بلا عدّ فعلي ⇒ 400 ، والعدّ قبل الإغلاق لا يغيّر الرصيد
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "stocktake", "from_warehouse_id": wh["id"],
        "lines": [{"item_id": item["id"], "quantity": 5}]}).status_code == 400

    r = client.post("/stock/docs", headers=admin, json={
        "doc_type": "stocktake", "from_warehouse_id": wh["id"],
        "notes": "جرد نهاية العام",
        "lines": [{"item_id": item["id"], "counted_quantity": 47}]})
    assert r.status_code == 201, r.text
    st = r.json()
    assert st["status"] == "draft" and st["doc_no"].startswith("STOCKTAKE-")
    assert st["total_quantity"] == 47
    assert _balance(client, admin, item["id"], wh["id"]) == 50  # لم يتغيّر بعد

    # الإغلاق يقيد الفرق −3
    r = client.post(f"/stock/docs/{st['id']}/action", headers=admin,
                    json={"action": "complete"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed" and r.json()["approved_by"] == "admin"
    assert _balance(client, admin, item["id"], wh["id"]) == 47
    adj = client.get(f"/stock/movements?item_id={item['id']}&type=adjust",
                     headers=admin).json()
    assert adj and adj[0]["change"] == -3 and adj[0]["quantity_after"] == 47
    # الإغلاق مرتين أو إجراء خاطئ ⇒ 400
    assert client.post(f"/stock/docs/{st['id']}/action", headers=admin,
                       json={"action": "complete"}).status_code == 400
    assert client.post(f"/stock/docs/{st['id']}/action", headers=admin,
                       json={"action": "approve"}).status_code == 400
    assert client.post(f"/stock/docs/{st['id']}/action", headers=admin,
                       json={"action": "unknown"}).status_code == 400


def test_item_with_stock_history_cannot_be_deleted(client, admin):
    """صنف له حركات/مستندات ⇒ 409 برسالة واضحة (كان 500 من قيد المفاتيح)."""
    # بلا تاريخ ⇒ الحذف ينجح
    plain = _item(client, admin)["id"]
    assert client.delete(f"/general-stock/{plain}", headers=admin).status_code == 204

    # برصيد قديم بلا حركات ⇒ يُحذف كسابقه (تُمسح أرصدته ودفعاته تاليًا)
    legacy = _item(client, admin, quantity=5)["id"]
    assert client.delete(f"/general-stock/{legacy}", headers=admin).status_code == 204

    # بحركة مستند ⇒ 409 برسالة توجّه للتعطيل
    moved = _item(client, admin)["id"]
    _grn(client, admin, moved, qty=3)
    r = client.delete(f"/general-stock/{moved}", headers=admin)
    assert r.status_code == 409, r.text
    assert "is_active=false" in r.json()["detail"]

    # التعطيل يبقى ممكنًا ويُخفيه من الدليل النشط مع بقاء سجله
    off = client.put(f"/general-stock/{moved}", headers=admin,
                     json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False
    card = client.get(f"/stock/items/{moved}/card", headers=admin)
    assert card.status_code == 200 and card.json()["item"]["quantity"] == 3


def test_purchase_request_and_order_flow(client, admin):
    """طلب شراء مسودّة ← اعتماد، وأمر شراء معتمد ← استلامه يولّد إذن استلام يورّد الكمية."""
    item = _item(client, admin, unit_cost=15)
    vendor, dept = _vendor(client, admin), _department(client, admin)
    wh = _default_wh(client, admin)

    # طلب شراء: مسودّة لا تحرّك المخزون
    pr = client.post("/stock/docs", headers=admin, json={
        "doc_type": "pr", "department_id": dept, "needed_at": _iso(10),
        "lines": [{"item_id": item["id"], "quantity": 30, "unit_cost": 15}]})
    assert pr.status_code == 201, pr.text
    pr = pr.json()
    assert pr["status"] == "draft" and pr["doc_no"].startswith("PR-")
    assert _balance(client, admin, item["id"], wh["id"]) == 0

    r = client.post(f"/stock/docs/{pr['id']}/action", headers=admin,
                    json={"action": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/stock/docs/{pr['id']}/action", headers=admin,
                       json={"action": "approve"}).status_code == 400

    # أمر شراء من الطلب المصدر، ومورده إجباري
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "po", "source_doc_id": pr["id"],
        "lines": [{"item_id": item["id"], "quantity": 30}]}).status_code == 400
    po = client.post("/stock/docs", headers=admin, json={
        "doc_type": "po", "vendor_id": vendor, "source_doc_id": pr["id"],
        "expected_at": _iso(5), "reference": "PO-EXT-1",
        "lines": [{"item_id": item["id"], "quantity": 30, "unit_cost": 15}]})
    assert po.status_code == 201, po.text
    po = po.json()
    assert po["status"] == "draft" and po["doc_no"].startswith("PO-")

    # استلام قبل الاعتماد ⇒ 400
    assert client.post(f"/stock/docs/{po['id']}/receive", headers=admin).status_code == 400
    assert client.post(f"/stock/docs/{po['id']}/action", headers=admin,
                       json={"action": "approve"}).status_code == 200

    grn = client.post(f"/stock/docs/{po['id']}/receive", headers=admin)
    assert grn.status_code == 201, grn.text
    grn = grn.json()
    assert grn["doc_type"] == "grn" and grn["status"] == "completed"
    assert grn["vendor_id"] == vendor
    assert _balance(client, admin, item["id"], wh["id"]) == 30
    # الأمر صار مستلَمًا فلا يُستلم مرتين
    assert client.post(f"/stock/docs/{po['id']}/receive", headers=admin).status_code == 400

    # إلغاء مسودّة شراء ووقف التوريد
    cancel_me = client.post("/stock/docs", headers=admin, json={
        "doc_type": "pr", "lines": [{"item_id": item["id"], "quantity": 1}]}).json()
    r = client.post(f"/stock/docs/{cancel_me['id']}/action", headers=admin,
                    json={"action": "cancel"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/stock/docs/{cancel_me['id']}/action", headers=admin,
                       json={"action": "cancel"}).status_code == 400


def test_fefo_consumes_nearest_expiry_first(client, admin):
    """FEFO: الصرف يخصم الدفعة الأقرب انتهاءً أولًا مهما تأخر تاريخ وصولها."""
    item = _item(client, admin)
    wh = _default_wh(client, admin)
    _grn(client, admin, item["id"], qty=20, batch_no=f"LATE{uid()}",
         expiry_date=_iso(300), unit_cost=10)
    _grn(client, admin, item["id"], qty=10, batch_no=f"SOON{uid()}",
         expiry_date=_iso(20), unit_cost=20)

    r = client.post("/stock/docs", headers=admin, json={
        "doc_type": "issue", "department_id": _department(client, admin),
        "lines": [{"item_id": item["id"], "quantity": 12}]})
    assert r.status_code == 201, r.text

    card = client.get(f"/stock/items/{item['id']}/card", headers=admin).json()
    remaining = {b["batch_no"]: b["quantity"] for b in card["batches"]}
    late = next(k for k in remaining if k.startswith("LATE"))
    # دفعة الـ20 يومًا استُهلكت بالكامل أولًا، فلم تعد في الدفعات النشطة
    assert not [k for k in remaining if k.startswith("SOON")]
    assert remaining[late] == 18     # ثم ذهب 2 من دفعة الـ300 يومًا
    assert _balance(client, admin, item["id"], wh["id"]) == 18
    # تاريخ انتهاء الصنف صار الأقرب المتبقي (دفعة الـ300 يومًا)
    row = next(i for i in client.get("/general-stock/", headers=admin).json()
               if i["id"] == item["id"])
    assert row["expiry_date"] is not None
    alerts = client.get("/stock/reports/expiry?days=90", headers=admin).json()
    assert not [a for a in alerts if a["item_id"] == item["id"]]


def test_reports_cover_reorder_expiry_valuation_and_slow_moving(client, admin):
    """التقارير الأربعة: إعادة الطلب · الانتهاء · التقييم · الركود + الملخّص."""
    dept = _department(client, admin)
    low = _item(client, admin, min_quantity=20, max_quantity=100,
                reorder_point=80, unit_cost=10, supplier_name="مورد الاختبار")
    _grn(client, admin, low["id"], qty=5)   # تحت حد الأمان ⇒ يظهر في إعادة الطلب

    soon = _item(client, admin, unit_cost=30)
    _grn(client, admin, soon["id"], qty=4, batch_no=f"EXP{uid()}",
         expiry_date=_iso(25), unit_cost=30)
    _grn(client, admin, soon["id"], qty=2, batch_no=f"FAR{uid()}",
         expiry_date=_iso(400), unit_cost=30)

    # 1) مستويات إعادة الطلب: الصنف تحت الحد مع كمية مقترحة
    rows = client.get("/stock/reports/reorder", headers=admin).json()
    mine = next(r for r in rows if r["item_id"] == low["id"])
    assert mine["quantity"] == 5 and mine["reorder_point"] == 80
    assert mine["suggested_quantity"] == 75
    assert mine["supplier_name"] == "مورد الاختبار"

    # 2) تنبيهات الانتهاء: ضمن 90 يومًا فقط، مرتّبة بالأقرب
    rows = client.get("/stock/reports/expiry?days=90", headers=admin).json()
    hit = [r for r in rows if r["item_id"] == soon["id"]]
    assert len(hit) == 1 and hit[0]["days_left"] <= 30
    assert hit[0]["value"] == round(4 * 30, 2) and hit[0]["warehouse"]
    assert not [r for r in rows if r["item_id"] == low["id"]]  # بلا تاريخ انتهاء
    # نافذة 0 ⇒ 400 ... بل 422 عبر التحقق، ونافذة أكبر من 365 ⇒ 422
    assert client.get("/stock/reports/expiry?days=400", headers=admin).status_code == 422

    # 3) التقييم: متوسط مرجّح + طبقات FIFO
    val = client.get("/stock/reports/valuation", headers=admin).json()
    mine = next(r for r in val if r["item_id"] == soon["id"])
    assert mine["quantity"] == 6 and mine["average_cost"] == 30.0
    assert mine["total_average"] == round(6 * 30, 2) == mine["total_fifo"]

    # 4) الركود: صنف بلا صرف يُعتبر راكدًا
    client.post("/stock/docs", headers=admin, json={
        "doc_type": "issue", "department_id": dept,
        "lines": [{"item_id": soon["id"], "quantity": 1}]})
    slow = client.get("/stock/reports/slow-moving?days=90", headers=admin).json()
    mine = next(r for r in slow if r["item_id"] == soon["id"])
    assert mine["issued_qty"] == 1 and mine["is_slow"] is False
    fresh = next(r for r in slow if r["item_id"] == low["id"])
    assert fresh["issued_qty"] == 0 and fresh["is_slow"] is True

    # 5) الملخّص: مستودعات وأصناف ومجموع قيمة
    summary = client.get("/stock/reports/summary", headers=admin).json()
    assert summary["warehouses"] >= 1 and summary["items"] >= 1
    assert summary["docs"]["grn"]["completed"] >= 1
    assert summary["docs"]["issue"]["completed"] >= 1
    assert summary["expiring_within_90"] >= 1
    assert summary["total_value"] > 0


def test_stock_ops_permissions_and_validation(client, admin):
    """بلا توكن 401، وغير المدير 403 على الكتابة، والتحققات ترفض المدخلات الفاسدة."""
    uname = f"stk{uid()}"
    r = client.post("/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "full_name": "أمين مخزن",
        "role": "موظف استقبال", "password": "Passw0rd!"})
    rec = login(client, r.json()["username"], "Passw0rd!")
    item = _item(client, admin)

    # القراءة متاحة لكل مسجّل، والكتابة للمدير فقط
    assert client.get("/stock/warehouses").status_code == 401
    assert client.get("/stock/reports/summary").status_code == 401
    assert client.post("/stock/warehouses", headers=rec,
                       json={"name": "مستودع موظف"}).status_code == 403
    assert client.post("/stock/docs", headers=rec, json={
        "doc_type": "grn",
        "lines": [{"item_id": item["id"], "quantity": 1}]}).status_code == 403
    assert client.post("/stock/warehouses", headers=admin,
                       json={"name": f"مستودع {uid()}"}).status_code == 201
    assert client.get("/stock/warehouses", headers=rec).status_code == 200

    # التحقق: نوع مجهول، صنف مجهول، كمية صفرية، سطور فارغة
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "zzz", "lines": [{"item_id": item["id"], "quantity": 1}]
    }).status_code == 400
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": 999999, "quantity": 1}]
    }).status_code == 404
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": [{"item_id": item["id"], "quantity": 0}]
    }).status_code == 400
    assert client.post("/stock/docs", headers=admin, json={
        "doc_type": "grn", "lines": []}).status_code == 422

    # مستند غير موجود / إجراء على نوع خطأ
    assert client.get("/stock/docs/999999", headers=admin).status_code == 404
    assert client.post("/stock/docs/999999/action", headers=admin,
                       json={"action": "approve"}).status_code == 404
    docs = client.get("/stock/docs?doc_type=grn", headers=admin).json()
    if docs:
        assert client.post(f"/stock/docs/{docs[0]['id']}/action", headers=admin,
                           json={"action": "approve"}).status_code == 400
