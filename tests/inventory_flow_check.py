# تدفق حي كامل لقسم المخزون: ملخص → أصناف وحالات → توريد → جرد → حركات → تقارير
import time

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"], "Content-Type": "application/json"}
fails = []

# أكواد فريدة لكل تشغيل حتى يعمل الفحص على قاعدة مستخدمة (idempotent)
TAG = "I" + format(int(time.time()) % 100000, "05d")


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# ===== 1) الأمان والملخّص =====
ok("قائمة المخزون بدون توكن => 401", c.get("/inventory/").status_code == 401)
ok("ملخص بدون توكن => 401", c.get("/inventory/summary").status_code == 401)
ok("restock بدون توكن => 401",
   c.post("/inventory/1/restock", json={"quantity": 1}).status_code == 401)
ok("جرد بدون توكن => 401",
   c.put("/inventory/1/adjust", json={"quantity": 1}).status_code == 401)

s0 = c.get("/inventory/summary", headers=H).json()
ok("ملخص المخزون يحوي كل المفاتيح",
   all(k in s0 for k in ("items", "units", "total_value", "low", "out",
                         "expired", "expiring", "expiring_days")), str(s0))
base_value = s0["total_value"]

# ===== 2) أربعة أصناف بحالات مختلفة =====
r = c.post("/medications/", headers=H, json={
    "code": TAG + "1", "name": "عقار سليم " + TAG, "quantity": 20, "unit": "علبة",
    "price": 5.0, "min_quantity": 5})
ok("صنف سليم 20×5", r.status_code == 200, r.text[:120])
m_ok = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "2", "name": "عقار منخفض " + TAG, "quantity": 3, "unit": "علبة",
    "price": 10.0, "min_quantity": 5})
ok("صنف منخفض 3 ≤ 5", r.status_code == 200, r.text[:120])
m_low = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "3", "name": "عقار منتهٍ " + TAG, "quantity": 6, "unit": "علبة",
    "price": 2.0, "min_quantity": 5, "expiry_date": "2020-01-01T00:00:00"})
ok("صنف منتهي الصلاحية", r.status_code == 200, r.text[:120])
m_exp = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "4", "name": "عقار نافد " + TAG, "quantity": 0, "unit": "علبة",
    "price": 7.5, "min_quantity": 5})
ok("صنف نافد 0", r.status_code == 200, r.text[:120])
m_out = r.json() if r.status_code == 200 else None

# ===== 3) الحالات والقيمة في القائمة =====
items = c.get("/inventory/", headers=H, params={"search": TAG}).json()
by_id = {x["id"]: x for x in items}
if m_ok and m_ok["id"] in by_id:
    ok("قيمة السليم = 20 × 5 = 100", by_id[m_ok["id"]]["value"] == 100.0,
       str(by_id[m_ok["id"]]["value"]))
    ok("حالة السليم = ok", by_id[m_ok["id"]]["status"] == "ok",
       by_id[m_ok["id"]]["status"])
if m_low and m_low["id"] in by_id:
    ok("حالة المنخفض = low", by_id[m_low["id"]]["status"] == "low",
       by_id[m_low["id"]]["status"])
if m_exp and m_exp["id"] in by_id:
    ok("حالة المنتهي = expired", by_id[m_exp["id"]]["status"] == "expired",
       by_id[m_exp["id"]]["status"])
    ok("أيام سالبة للمنتجي", by_id[m_exp["id"]]["days_to_expiry"] < 0,
       str(by_id[m_exp["id"]]["days_to_expiry"]))
if m_out and m_out["id"] in by_id:
    ok("حالة النافد = out", by_id[m_out["id"]]["status"] == "out",
       by_id[m_out["id"]]["status"])

# ===== 4) الفلاتر =====
by_code = c.get("/inventory/", headers=H, params={"search": TAG + "2"}).json()
ok("بحث بالرمز يرجع الصنف فقط",
   len(by_code) == 1 and by_code[0]["code"] == TAG + "2", str(len(by_code)))
low_only = c.get("/inventory/", headers=H, params={"status": "low"}).json()
ok("فلتر status=low كلها low", bool(low_only)
   and all(x["status"] == "low" for x in low_only), str(len(low_only)))
r = c.get("/inventory/", headers=H, params={"status": "bogus"})
ok("فلتر حالة خاطئ => 400", r.status_code == 400, str(r.status_code))
r = c.get("/inventory/", headers=H, params={"expiring_days": -5})
ok("expiring_days سالب => 400", r.status_code == 400, str(r.status_code))
r = c.get("/inventory/summary", headers=H, params={"expiring_days": 999})
ok("ملخص expiring_days > 365 => 400", r.status_code == 400, str(r.status_code))
r = c.get("/inventory/movements", headers=H, params={"type": "bogus"})
ok("نوع حركة خاطئ => 400", r.status_code == 400, str(r.status_code))
r = c.get("/inventory/movements", headers=H, params={"limit": 0})
ok("limit=0 => 422", r.status_code == 422, str(r.status_code))

# ===== 5) التوريد =====
if m_ok:
    before = m_ok["quantity"]
    r = c.post(f"/inventory/{m_ok['id']}/restock", headers=H,
               json={"quantity": 25, "note": "توريد المورد الأسبوعي"})
    ok("restock +25 => 200", r.status_code == 200, r.text[:120])
    ok("الكمية صارت 45", r.json().get("quantity") == before + 25,
       str(r.json().get("quantity")))
    mv = c.get("/inventory/movements", headers=H,
               params={"medication_id": m_ok["id"], "type": "in"}).json()
    ok("حركة in: تغير +25 ورصيد 45",
       any(x["change"] == 25 and x["quantity_after"] == before + 25 for x in mv),
       str([(x["change"], x["quantity_after"]) for x in mv[:3]]))
    ok("ملاحظة الحركة محفوظة",
       any(x["note"] == "توريد المورد الأسبوعي" for x in mv))
    ok("بمن الحركة admin",
       any(x["made_by"] == "admin" for x in mv))

    # أخطاء التوريد
    r = c.post(f"/inventory/{m_ok['id']}/restock", headers=H, json={"quantity": 0})
    ok("restock 0 => 422", r.status_code == 422, str(r.status_code))
    r = c.post(f"/inventory/{m_ok['id']}/restock", headers=H, json={"quantity": -4})
    ok("restock سالب => 422", r.status_code == 422, str(r.status_code))
    r = c.post("/inventory/999999/restock", headers=H, json={"quantity": 5})
    ok("restock غير موجود => 404", r.status_code == 404, str(r.status_code))

# ===== 6) الجرد المطلق =====
if m_low:
    r = c.put(f"/inventory/{m_low['id']}/adjust", headers=H,
              json={"quantity": 12, "note": "جرد نهاية الشهر"})
    ok("جرد 3 => 12", r.status_code == 200 and r.json().get("quantity") == 12,
       r.text[:120])
    mv = c.get("/inventory/movements", headers=H,
               params={"medication_id": m_low["id"], "type": "adjust"}).json()
    ok("حركة adjust: فرق +9 ورصيد 12",
       any(x["change"] == 9 and x["quantity_after"] == 12 for x in mv),
       str([(x["change"], x["quantity_after"]) for x in mv[:3]]))
    r = c.put(f"/inventory/{m_low['id']}/adjust", headers=H, json={"quantity": -1})
    ok("جرد سالب => 422", r.status_code == 422, str(r.status_code))
    r = c.put("/inventory/999999/adjust", headers=H, json={"quantity": 1})
    ok("جرد غير موجود => 404", r.status_code == 404, str(r.status_code))

# ===== 7) صرف يظهر كحركة out =====
_pat = c.post("/patients/", headers=H, json={
    "full_name": "مريض المخزون", "date_of_birth": "1993-03-03",
    "gender": "ذكر", "phone": "0555000111", "email": "invflow@example.com"})
pat = _pat.json() if _pat.status_code == 200 else next(
    (p for p in c.get("/patients/", headers=H).json()
     if p["full_name"] == "مريض المخزون"), None)
if m_ok and pat:
    d = c.post("/dispenses/", headers=H, json={
        "medication_id": m_ok["id"], "patient_id": pat["id"], "quantity": 5})
    ok("صرف 5 => 200", d.status_code == 200, d.text[:120])
    mv = c.get("/inventory/movements", headers=H,
               params={"medication_id": m_ok["id"], "type": "out"}).json()
    ok("حركة out: تغير -5 ورصيد 40",
       any(x["change"] == -5 and x["quantity_after"] == 40 for x in mv),
       str([(x["change"], x["quantity_after"]) for x in mv[:3]]))
    ok("الرصيد بعد الصرف = 40",
       c.get(f"/medications/{m_ok['id']}", headers=H).json()["quantity"] == 40)

# ===== 8) الملخّص بعد العمليات =====
s1 = c.get("/inventory/summary", headers=H).json()
ok("قيمة المخزون زادت", s1["total_value"] > base_value,
   f"{base_value} -> {s1['total_value']}")
ok("عدّاد الأصناف ≥ 4", s1["items"] >= 4, str(s1["items"]))
ok("عدّاد المنتهي ≥ 1", s1["expired"] >= 1, str(s1["expired"]))
ok("عدّاد النافد ≥ 1", s1["out"] >= 1, str(s1["out"]))
ok("القطع ≥ القيمة القصوى السابقة", s1["units"] >= 45, str(s1["units"]))

# ===== 9) تقارير المخزون =====
csv = c.get("/reports/pharmacy/csv", headers=H, params={"section": "inventory"})
ok("CSV مخزون + BOM", csv.status_code == 200
   and csv.content[:3] == b"\xef\xbb\xbf", str(csv.status_code))
pdf = c.get("/reports/pharmacy/pdf", headers=H)
ok("PDF مخزون %PDF", pdf.status_code == 200 and pdf.content[:4] == b"%PDF",
   str(pdf.status_code))

# ===== 10) مؤشرات الواجهة =====
ui = c.get("/ui/").text + c.get("/ui/app.js").text
ok("رابط القائمة inventory", 'data-view="inventory"' in ui)
ok("عرض inventory في الواجهة", "async inventory(main)" in ui)
ok("عنوان الشاشة المخزون", "inventory: 'المخزون'" in ui)
ok("بطاقات الملخص في العرض", "/inventory/summary" in ui)
ok("دفتر الحركات في العرض", "/inventory/movements" in ui)
ok("زر الجرد موجود", "function adjustStock(" in ui)
ok("التوريد عبر /inventory", "'/inventory/' + id + '/restock'" in ui)
ok("الكاش v5", "hms-shell-v5" in c.get("/ui/sw.js").text)

print(f"\n== INVENTORY FLOW RESULT: {len(fails) == 0} — failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
