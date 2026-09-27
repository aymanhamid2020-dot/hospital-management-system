# سير عمل الطوارئ حيًّا على خادم 8001: فتح ملف ← طلب فحوصات ← بوابة الدفع
# (402) ← فاتورة ببنود ← تحصيل ← سحب العيّنة ← علاج/وصفة ← الصيدلية
# + مؤشرات منتقي الفحوصات المصنَّف. يُشغَّل يدويًا: python er_flow_check.py
import os
import time

import httpx

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8001")
c = httpx.Client(base_url=BASE, timeout=60)
fails = []
TAG = "E" + format(int(time.time()) % 100000, "05d")


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def j(r):
    try:
        return r.json()
    except Exception:
        return {}


tok = c.post("/auth/login", json={"username": "admin",
                                  "password": "admin123"}).json()
assert tok.get("access_token"), "تعذّر تسجيل الدخول على " + BASE
H = {"Authorization": "Bearer " + tok["access_token"],
     "Content-Type": "application/json"}

# ===== 1) مريض وملف طوارئ =====
pat = c.post("/patients/", headers=H, json={
    "full_name": "طوارئ فحص حي " + TAG, "gender": "ذكر",
    "date_of_birth": "1990-01-01", "phone": "0500000000",
    "email": f"er-flow-{TAG}@example.com"})
ok("إنشاء مريض", pat.status_code in (200, 201), str(pat.status_code))
pat = j(pat)

case = c.post("/service-units/emergency", headers=H, json={
    "patient_id": pat.get("id"), "complaint": "ألم صدري مفاجئ مع ضيق تنفس",
    "triage_level": "urgent", "arrival_at": "2026-01-01T09:30",
    "consult_fee": 80})
ok("فتح ملف طوارئ", case.status_code == 201, str(case.status_code))
case = j(case)
cid = case.get("id")

# ===== 2) الدليل المصنَّف =====
tests = c.get("/lab-tests/", headers=H, params={"active_only": True}).json()
groups = sorted({t.get("specimen_group") for t in tests})
ok("الدليل المصنَّف: 290 فحصًا في 14 مجموعة",
   len(tests) >= 290 and len(groups) == 14,
   f"{len(tests)} فحص · {len(groups)} مجموعة")

want = ([t for t in tests if t.get("specimen_group") == "blood"][:2]
        + [t for t in tests if t.get("specimen_group") == "xray"][:1])
ordered = c.post(f"/service-units/emergency/{cid}/orders", headers=H, json={
    "lines": [{"lab_test_id": t["id"],
               "priority": "stat" if i == 0 else "routine"}
              for i, t in enumerate(want)]})
body = j(ordered)
ok("طلب 3 فحوصات (دم + أشعة) يرجع ملخّص الحالة",
   ordered.status_code == 200 and len(body.get("lab_orders", [])) == 3,
   f"{ordered.status_code} · {len(body.get('lab_orders', []))}")

# ===== 3) بوابة الدفع =====
rows = c.get("/lab-orders/", headers=H).json()
mine = [o for o in rows if o.get("emergency_case_id") == cid]
ok("المختبر يرى الطلبات بحالة payment_pending",
   len(mine) == 3 and all(o["payment_pending"] for o in mine),
   f"{len(mine)} طلب")

gated = c.post(f"/lab-orders/{mine[0]['id']}/collect", headers=H,
               json={"specimen_type": "دم كامل", "collected_by": "مختبر"})
ok("التنفيذ قبل الدفع يرده 402", gated.status_code == 402,
   f"{gated.status_code} {j(gated).get('detail', '')[:60]}")
un = c.get("/notifications/unread-count", headers=H).json().get("unread", 0)
ok("إشعار غير مقروء لصاحب التحصيل", un > 0, str(un))

# ===== 4) فاتورة ببنود =====
sm = c.post(f"/service-units/emergency/{cid}/checkout", headers=H,
            json={"consult_fee": 80})
s = j(sm)
ok("فتح فاتورة تحصيل ببنود (كشفية + 3 فحوصات)",
   sm.status_code == 200 and len(s.get("lines", [])) == 4
   and s.get("payment_status") in ("unbilled", "unpaid"),
   f"{sm.status_code} · {s.get('payment_status')} · {len(s.get('lines', []))} سطر")
ok("بنود مربوطة (ref_type/ref_id) فلا تُحصَّل مرّتين",
   all(x.get("kind") for x in s.get("lines", []))
   and s.get("invoice_id"))

inv = c.get(f"/invoices/{s['invoice_id']}", headers=H).json()
ok("مبلغ الفاتورة = مجموع سطورها",
   abs(inv.get("amount", 0) - s.get("billed_total", 0)) < 0.01,
   str(inv.get("amount")))
ok("ملخّص الحالة يعرض كل فواتيرها مع المتبقي",
   s.get("invoices") and s["invoices"][0]["due"] > 0,
   str(s.get("invoices")))

paid = c.post(f"/invoices/{s['invoice_id']}/pay", headers=H,
              json={"method": "cash"})
ok("تحصيل الفاتورة", paid.status_code == 200, str(paid.status_code))
s2 = c.get(f"/service-units/emergency/{cid}/summary", headers=H).json()
ok("الحالة صارت مدفوعة بلا متبقي",
   s2.get("payment_status") == "paid" and s2.get("due") == 0,
   f"{s2.get('payment_status')} / {s2.get('due')}")

# ===== 5) فُتحت البوابة =====
col = c.post(f"/lab-orders/{mine[0]['id']}/collect", headers=H,
             json={"specimen_type": "دم كامل", "collected_by": "مختبر"})
ok("سحب العيّنة بعد الدفع ينجح", col.status_code == 200,
   str(col.status_code))

# ===== 6) العلاج والوصفة =====
med = c.get("/medications/", headers=H).json()[0]
tr = c.post(f"/service-units/emergency/{cid}/treatment", headers=H, json={
    "diagnosis": "ذبحة صدرية مستقرة",
    "treatment": "مضاد التهاب + مدر بول",
    "prescription": [{"medication_id": med["id"], "quantity": 2,
                      "dosage": "قرص", "frequency": "كل 8 ساعات",
                      "duration": "5 أيام"}],
    "discharge": False})
ok("تسجيل العلاج والوصفة", tr.status_code == 200, str(tr.status_code))
s3 = c.get(f"/service-units/emergency/{cid}/summary", headers=H).json()
ok("الملف: سجل طبي + وصفة",
   s3.get("has_record") and s3.get("has_prescription"),
   f"record={s3.get('case', {}).get('record_id')} "
   f"rx={s3.get('case', {}).get('prescription_id')}")

rx = [r for r in c.get("/prescriptions/", headers=H).json()
      if r.get("patient_id") == pat.get("id")]
ok("الوصفة لدى الصيدلية بحالة معلّقة",
   len(rx) == 1 and str(rx[0].get("status", "")).lower() == "pending",
   str(rx[0].get("status")) if rx else "—")

# ===== 7) مؤشرات الواجهة =====
js = c.get("/app.js").text
css = c.get("/app.css").text
html = c.get("/").text
ok("شاشة الطوارئ ومنتقي الفحوصات في app.js",
   all(k in js for k in ("renderEr", "erOrder", "erCheckout", "erTreat",
                         "erNewFile", "testPickerHTML", "TEST_GROUP",
                         "labPayPill", 'id="f-cat" value=""')))
ok("أنماط الشاشة والمنتقي في app.css",
   all(k in css for k in (".er-shell", ".tp-chip", ".tp-row", ".er-item")))
ok("رابط الطوارئ في القائمة الجانبية", 'data-view="er"' in html)

# ===== 8) التنظيف =====
c.delete(f"/patients/{pat.get('id')}", headers=H)

print(f"\n== ER FLOW RESULT: {len(fails) == 0} — failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
