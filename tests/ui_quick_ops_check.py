# -*- coding: utf-8 -*-
"""فحص حي لمركز العمليات السريعة: يقرأ static ويشغّل العمليات الثلاث على خادم 8001."""
import httpx

HTML = open("static/index.html", "rb").read()
APP = open("static/app.js", "rb").read()
ALL = HTML + APP

NEEDLES = [
    'data-view="quickops"',
    "qoGo('sale')",
    "⚡ العمليات السريعة",
    "const QO = {",
    "async function quickops(main)",
    "function qoAdd(i)",
    "function qoSubmit()",
    "function qoResultCard(box)",
    "function qoRecentCard()",
    "async function qoEnsureVendors()",
    "async function qoRunPatient()",
    "function qoRunSearch()",
    "qoTotalsBar('sale')",
    "qoBasketTable('purchase')",
    "qoBasketTable('transfer')",
    "/quick-ops/catalog",
    "/quick-ops/sales",
    "/quick-ops/purchases",
    "/quick-ops/transfers",
    "quickops: 'العمليات السريعة'",
    "if (!(e.ctrlKey && e.altKey)) return;",
    "const map = { s: 'sale', b: 'purchase', t: 'transfer' }",
    "🛒 بيع سريع",
    "📥 شراء سريع",
    "🔄 ترحيل سريع",
    "✅ إتمام البيع",
    "✅ تسجيل الشراء",
    "✅ تنفيذ الترحيل",
    "آخر عمليات اليوم",
]
print("== static ==")
bad = 0
for n in NEEDLES:
    ok = n.encode("utf-8") in ALL
    bad += 0 if ok else 1
    print(("  [PASS] " if ok else "  [FAIL] ") + n)

print("== live server ==")
c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"]}

ov = c.get("/quick-ops/overview", headers=H)
cat = c.get("/quick-ops/catalog", headers=H, params={"limit": 3})
whs = c.get("/stock/warehouses", headers=H).json()
wh = next((w for w in whs if w["is_default"]), whs[0])
vends = c.get("/accounts/ledger/vendors", headers=H).json()
vendor = vends[0]["id"] if vends else None
pts = c.get("/patients/", headers=H, params={"limit": 1}).json()
patient = pts[0]["id"] if pts else None
items = c.get("/general-stock/", headers=H).json()
item = next((i for i in items if i.get("is_active")), None)
meds = c.get("/medications/", headers=H).json()
med = next((m for m in meds if m["quantity"] > 5), None)

# توريد الصنف ثم بيعه فعلًا (عملية حقيقية على قاعدة التشغيل)
sale_ok = buy_ok = tr_ok = False
sale_msg = buy_msg = tr_msg = "لم تُنفَّذ (بيانات غير مكتملة)"
if item and patient and vendor:
    buy = c.post("/quick-ops/purchases", headers=H, json={
        "vendor_id": vendor, "warehouse_id": wh["id"],
        "lines": [{"item_id": item["id"], "quantity": 2, "unit_cost": item["unit_cost"] or 1}]})
    buy_ok = buy.status_code == 201
    buy_msg = f"شراء سريع ⇒ {buy.status_code}"
    sale = c.post("/quick-ops/sales", headers=H, json={
        "patient_id": patient, "warehouse_id": wh["id"],
        "paid_amount": 0, "payment_method": "cash",
        "lines": [{"item_id": item["id"], "quantity": 1,
                   "unit_price": max(item["unit_cost"] or 1, 1)}]})
    sale_ok = sale.status_code == 201
    sale_msg = f"بيع سريع ⇒ {sale.status_code}"
    other = next((w for w in whs if w["id"] != wh["id"]), None)
    if other:
        tr = c.post("/quick-ops/transfers", headers=H, json={
            "from_warehouse_id": wh["id"], "to_warehouse_id": other["id"],
            "lines": [{"item_id": item["id"], "quantity": 1}]})
        tr_ok = tr.status_code == 201
        tr_msg = f"ترحيل سريع ⇒ {tr.status_code}"
else:
    buy_msg = sale_msg = "بيانات غير مكتملة في القاعدة"

checks = [
    ("GET / يخدم الواجهة", c.get("/").status_code == 200),
    ("رابط القائمة موجود", 'data-view="quickops"'.encode() in c.get("/").content),
    ("مؤشرات العمليات السريعة 200", ov.status_code == 200),
    ("مؤشرات فيها مفاتيح اليوم", ov.status_code == 200 and
     all(k in ov.json() for k in ("sales_today", "purchases_today", "movements_today"))),
    ("البحث عن الأصناف 200", cat.status_code == 200 and isinstance(cat.json(), list)),
    ("بحث بحرف واحد لا يخطئ", c.get("/quick-ops/catalog", headers=H, params={"q": "ا"}).status_code == 200),
    ("شراء سريع 201", buy_ok),
    ("بيع سريع 201", sale_ok),
    ("ترحيل سريع 201", tr_ok),
    ("بيع بلا توكن ⇒ 401", c.post("/quick-ops/sales", json={"patient_id": 1, "lines": []}).status_code == 401),
    ("شراء بلا توكن ⇒ 401", c.post("/quick-ops/purchases", json={"vendor_id": 1, "lines": []}).status_code == 401),
    ("ترحيل بلا توكن ⇒ 401", c.post("/quick-ops/transfers", json={"from_warehouse_id": 1, "to_warehouse_id": 2, "lines": []}).status_code == 401),
]
for name, ok in checks:
    bad += 0 if ok else 1
    print(("  [PASS] " if ok else "  [FAIL] ") + name)
print(f"   · {sale_msg} · {buy_msg} · {tr_msg}")

total = len(NEEDLES) + len(checks)
print(f"\n== QUICK OPS CHECK: {total - bad} passed, {bad} failed ==")
raise SystemExit(1 if bad else 0)