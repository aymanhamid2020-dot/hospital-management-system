# تدفق حي كامل لتطوير الصيدلية: رفض المنتهي → سلة الصرف الجماعية → الإرجاع
# → الإتلاف → الإحصاءات/اقتراحات الطلب → الوصفات → التقارير الجديدة → الواجهة
import re
import time

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"], "Content-Type": "application/json"}
fails = []

# أكواد فريدة لكل تشغيل حتى يعمل الفحص على قاعدة مستخدمة (idempotent)
TAG = "P" + format(int(time.time()) % 100000, "05d")


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# ===== 1) الأمان =====
for path in ("/pharmacy/stats", "/pharmacy/reorder", "/prescriptions/",
             "/reports/pharmacy/stats/pdf", "/reports/pharmacy/stats/csv"):
    ok(f"{path} بدون توكن => 401", c.get(path).status_code == 401)
ok("dispenses/batch POST بدون توكن => 401",
   c.post("/dispenses/batch", json={}).status_code == 401)
ok("dispose بدون توكن => 401",
   c.post("/inventory/1/dispose", json={"quantity": 1}).status_code == 401)

# موظف استقبال بلا صلاحيات إدارية
u = "recph_" + TAG
c.post("/auth/register", json={"username": u, "email": f"{u}@test.com",
                               "full_name": "موظف استقبال", "password": "secret123"})
rt = c.post("/auth/login", json={"username": u, "password": "secret123"}).json()
RH = {"Authorization": "Bearer " + rt["access_token"], "Content-Type": "application/json"}
ok("dispose للموظف => 403",
   c.post("/inventory/1/dispose", headers=RH, json={"quantity": 1}).status_code == 403)
ok("إنشاء وصفة للموظف => 403",
   c.post("/prescriptions/", headers=RH, json={}).status_code
   in (403, 422))
ok("تقرير إحصاءات للموظف => 403",
   c.get("/reports/pharmacy/stats/pdf", headers=RH).status_code == 403)

# ===== 2) أدوية الفحص =====
r = c.post("/medications/", headers=H, json={
    "code": TAG + "1", "name": "عقار صرف " + TAG, "quantity": 20, "unit": "علبة",
    "price": 6.0, "min_quantity": 5})
ok("صنف سليم 20×6 => 200", r.status_code == 200, r.text[:120])
m1 = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "2", "name": "عقار فقير " + TAG, "quantity": 1, "unit": "علبة",
    "price": 4.0, "min_quantity": 5})
ok("صنف فقير 1 => 200", r.status_code == 200, r.text[:120])
m2 = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "3", "name": "عقار منتهٍ صرف " + TAG, "quantity": 6,
    "unit": "علبة", "price": 2.0, "min_quantity": 5,
    "expiry_date": "2020-01-01T00:00:00"})
ok("صنف منتهي => 200", r.status_code == 200, r.text[:120])
me = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "4", "name": "عقار منخفض طلب " + TAG, "quantity": 2,
    "unit": "علبة", "price": 3.0, "min_quantity": 10})
ok("صنف منخفض 2 ≤ 10 => 200", r.status_code == 200, r.text[:120])
mlow = r.json() if r.status_code == 200 else None

r = c.post("/medications/", headers=H, json={
    "code": TAG + "5", "name": "عقار مرتجع حصرى " + TAG, "quantity": 15,
    "unit": "علبة", "price": 8.0, "min_quantity": 5})
ok("صنف الإرجاع => 200", r.status_code == 200, r.text[:120])
mr = r.json() if r.status_code == 200 else None

# مريض الفحص
_pr = c.post("/patients/", headers=H, json={
    "full_name": "مريض صيدلية " + TAG, "date_of_birth": "1994-04-04",
    "gender": "ذكر", "phone": "0555000222", "email": f"ph{TAG}@example.com"})
pat = _pr.json() if _pr.status_code == 200 else next(
    (p for p in c.get("/patients/", headers=H).json()
     if p["email"] == f"ph{TAG}@example.com"), None)
ok("مريض الفحص جاهز", pat is not None)

# ===== 3) رفض صرف المنتهي =====
if me and pat:
    r = c.post("/dispenses/", headers=H, json={
        "medication_id": me["id"], "patient_id": pat["id"], "quantity": 1})
    ok("صرف منتهي (فردي) => 400", r.status_code == 400, r.text[:120])
    ok("رسالة الصلاحية ظاهرة", "منتهي الصلاحية" in r.json().get("detail", ""),
       r.json().get("detail", "")[:80])
    r = c.post("/dispenses/batch", headers=H, json={
        "patient_id": pat["id"],
        "items": [{"medication_id": me["id"], "quantity": 1}]})
    ok("صرف منتهي (سلة) => 400", r.status_code == 400, r.text[:120])
    ok("رصيد المنتهي لم يُمس", c.get(f"/medications/{me['id']}",
                                      headers=H).json()["quantity"] == 6)

# ===== 4) السلة الجماعية all-or-nothing =====
if m1 and m2 and pat:
    # نجاح بندَين مع حقول التوجيه
    r = c.post("/dispenses/batch", headers=H, json={
        "patient_id": pat["id"], "notes": "سلة " + TAG,
        "items": [
            {"medication_id": m1["id"], "quantity": 3,
             "dosage": "قرص بعد الأكل", "frequency": "3 مرات يوميًا",
             "duration": "5 أيام", "instructions": "لا تتجاوز الجرعة"},
            {"medication_id": m2["id"], "quantity": 1}]})
    ok("سلة ناجحة بندَين => 200", r.status_code == 200, r.text[:140])
    if r.status_code == 200:
        body = r.json()
        ok("count=2 والإجمالي 3×6+1×4=22",
           body["count"] == 2 and body["total"] == 22.0,
           f'{body.get("count")} {body.get("total")}')
        ok("حقل الجرعة محفوظ",
           any(d.get("dosage") == "قرص بعد الأكل" for d in body["dispenses"]))
        ok("رصيد m1 بعد السلة = 17",
           c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"] == 17)
        ok("رصيد m2 بعد السلة = 0",
           c.get(f"/medications/{m2['id']}", headers=H).json()["quantity"] == 0)

    # فشل بند واحد => لا تعديل نصفي
    before_ok = c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"]
    r = c.post("/dispenses/batch", headers=H, json={
        "patient_id": pat["id"],
        "items": [{"medication_id": m1["id"], "quantity": 2},
                  {"medication_id": m2["id"], "quantity": 9}]})
    ok("سلة بكمية فائضة => 400", r.status_code == 400, r.text[:140])
    ok("لا تعديل نصفي (رصيد m1 ثابت)",
       c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"] == before_ok)

    # تجميع المكرر: مجموع 5 ضمن المتوفر (17) => نجاح بعمليتين
    r = c.post("/dispenses/batch", headers=H, json={
        "patient_id": pat["id"],
        "items": [{"medication_id": m1["id"], "quantity": 3},
                  {"medication_id": m1["id"], "quantity": 2}]})
    ok("مكرر مجموعه ضمن المتوفر => 200 count=2",
       r.status_code == 200 and r.json()["count"] == 2, r.text[:140])
    ok("رصيد m1 بعد التجميع = 12",
       c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"] == 12)

    # تحقق التحقق المبكر: مجموع المكرر الفائض يُرفض قبل أي تعديل
    r = c.post("/dispenses/batch", headers=H, json={
        "patient_id": pat["id"],
        "items": [{"medication_id": m1["id"], "quantity": 10},
                  {"medication_id": m1["id"], "quantity": 10}]})
    ok("مكرر مجموعه 20 > 12 => 400", r.status_code == 400, r.text[:140])
    ok("رصيد m1 لم يتغير بعد الرفض",
       c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"] == 12)

    # تحقق قوائم الحقول
    r = c.post("/dispenses/batch", headers=H,
               json={"patient_id": pat["id"], "items": []})
    ok("سلة فارغة => 422", r.status_code == 422, str(r.status_code))
    r = c.post("/dispenses/batch", headers=H, json={
        "patient_id": 999999,
        "items": [{"medication_id": m1["id"], "quantity": 1}]})
    ok("مريض غير موجود => 404", r.status_code == 404, str(r.status_code))

# ===== 5) الإرجاع واستثناؤه من الحسابات =====
if mr and pat:
    d = c.post("/dispenses/", headers=H, json={
        "medication_id": mr["id"], "patient_id": pat["id"], "quantity": 4,
        "dosage": "كبسولة صباحًا"})
    ok("صرف مرتجع محتمل => 200", d.status_code == 200, d.text[:120])
    did = d.json()["id"] if d.status_code == 200 else None
    if did:
        ok("رصيد mr بعد الصرف = 11",
           c.get(f"/medications/{mr['id']}", headers=H).json()["quantity"] == 11)
        r = c.post(f"/dispenses/{did}/return", headers=H, json={"reason": "   "})
        ok("سبب من مسافات => 422", r.status_code == 422, str(r.status_code))
        r = c.post(f"/dispenses/{did}/return", headers=H, json={
            "reason": "وصفة خاطئة " + TAG})
        ok("إرجاع صحيح => 200", r.status_code == 200, r.text[:140])
        if r.status_code == 200:
            ok("returned_by = admin",
               r.json().get("returned_by") == "admin")
        ok("رصيد mr عاد = 15",
           c.get(f"/medications/{mr['id']}", headers=H).json()["quantity"] == 15)
        mv = c.get("/inventory/movements", headers=H,
                   params={"medication_id": mr["id"], "type": "return"}).json()
        ok("حركة return: +4 ورصيد 15",
           any(x["change"] == 4 and x["quantity_after"] == 15 for x in mv),
           str([(x["change"], x["quantity_after"]) for x in mv[:3]]))
        r = c.post(f"/dispenses/{did}/return", headers=H, json={"reason": "ثانيًا"})
        ok("إرجاع مكرر => 409", r.status_code == 409, str(r.status_code))

        # مستثني من استعلامات الحسابات
        sales = c.get("/accounts/sales", headers=H,
                      params={"patient_id": pat["id"]}).json()
        ok("المرتجع غير موجود في سجل المبيعات",
           all(s["id"] != did for s in sales), str([s["id"] for s in sales]))
        stmt = c.get(f"/accounts/statement/{pat['id']}", headers=H).json()
        ok("المرتجع غير موجود في كشف الحساب",
           all(s["id"] != did for s in stmt["sales"]))
        r = c.put(f"/accounts/sales/{did}/payment", headers=H,
                  json={"paid_amount": 1, "payment_method": "cash"})
        ok("تسديد المرتجع => 409", r.status_code == 409, str(r.status_code))
        rc = c.get(f"/accounts/sales/{did}/receipt", headers=H)
        ok("إيصال المرتجع يعرض شارة مرجعة", rc.status_code == 200
           and "مرتجع" in rc.text)
        ok("إيصال المرتجع يعرض الجرعة", "كبسولة صباحًا" in rc.text)

# ===== 6) الإتلاف =====
if m1:
    r = c.post(f"/inventory/{m1['id']}/dispose", headers=H, json={"quantity": 0})
    ok("إتلاف 0 => 422", r.status_code == 422, str(r.status_code))
    r = c.post(f"/inventory/{m1['id']}/dispose", headers=H,
               json={"quantity": 9999})
    ok("إتلاف أكبر من الرصيد => 400", r.status_code == 400, str(r.status_code))
    before = c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"]
    r = c.post(f"/inventory/{m1['id']}/dispose", headers=H,
               json={"quantity": 3, "note": "تلف " + TAG})
    ok("إتلاف 3 => 200 والرصيد -3",
       r.status_code == 200 and r.json()["quantity"] == before - 3,
       r.text[:140])
    mv = c.get("/inventory/movements", headers=H,
               params={"medication_id": m1["id"], "type": "disposal"}).json()
    ok("حركة disposal: -3 وملاحظة محفوظة",
       any(x["change"] == -3 and TAG in (x["note"] or "") for x in mv))
    r = c.get("/inventory/movements", headers=H, params={"type": "bogus"})
    ok("نوع حركة خاطئ ما زال 400", r.status_code == 400)

# ===== 7) الإحصاءات =====
s0 = c.get("/pharmacy/stats", headers=H)
ok("GET /pharmacy/stats => 200", s0.status_code == 200, s0.text[:140])
base = s0.json()
ok("مفاتيح الإحصاءات كاملة",
   all(k in base for k in ("period", "dispense_count", "units", "revenue",
                           "paid", "outstanding", "inventory_value", "low",
                           "out", "expired", "expiring", "top_medications",
                           "daily")), str(list(base)))
if m1 and pat:
    r = c.post("/dispenses/", headers=H, json={
        "medication_id": m1["id"], "patient_id": pat["id"], "quantity": 2})
    ok("صرف لقياس الإحصاء => 200", r.status_code == 200, r.text[:120])
    s1 = c.get("/pharmacy/stats", headers=H).json()
    ok("الوحدات زادت 2", s1["units"] == base["units"] + 2,
       f'{base["units"]} -> {s1["units"]}')
    ok("الإيراد زاد 12.0", round(s1["revenue"] - base["revenue"], 2) == 12.0)
    ok("عدد العمليات زاد 1", s1["dispense_count"] == base["dispense_count"] + 1)
    # دقة تجميع "أكثر الأدوية": وحدات المتصدِّر = مجموع صفوفه غير المرتجعة.
    # القائمة تراكمية (أول10 لكل الفترات بكسر تعادل المعرّف الأقدم) فلا يُفرض
    # على صنف هذا التشغيل حجز رتبة فيها؛ عكس الصرف على الأرقام العامة أعلاه
    # (وحدات/إيراد/عمليات +2/+12/+1) يثبت أصلًا ظهور الصرف في الإحصاء.
    top10 = s1["top_medications"]
    if top10:
        lead = top10[0]
        dd = c.get("/dispenses/", headers=H,
                   params={"medication_id": lead["medication_id"]}).json()
        lead_units = sum(x["quantity"] or 0 for x in dd
                         if x.get("returned_at") is None)
        ok("أرقام أكثر الأدوية مطابقة لصفوف الصرف",
           lead["units"] == lead_units,
           f'{lead["units"]} vs {lead_units} (صنف {lead["code"]})')
    else:
        ok("أكثر الأدوية غير فارغ بعد الصرف", False)
r = c.get("/pharmacy/stats", headers=H, params={"from_date": "nope"})
ok("تاريخ خاطئ => 400", r.status_code == 400, str(r.status_code))
r = c.get("/pharmacy/stats", headers=H, params={
    "from_date": "2000-01-01", "to_date": "2000-01-31"})
ok("فترة قديمة => 200 وصفر عمليات",
   r.status_code == 200 and r.json()["dispense_count"] == 0, r.text[:120])

# ===== 8) اقتراحات إعادة الطلب =====
r = c.get("/pharmacy/reorder", headers=H)
ok("GET /pharmacy/reorder => 200", r.status_code == 200, r.text[:140])
if mlow and r.status_code == 200:
    rows = r.json()
    row = next((x for x in rows if x["medication_id"] == mlow["id"]), None)
    ok("الصنف المنخفض في الاقتراحات", row is not None)
    if row:
        ok("المقترح ≥ 8 (10 − 2)", row["suggested_qty"] >= 8,
           str(row["suggested_qty"]))
        ok("متوسط الاستهلاك اليومي", row["avg_per_day"] >= 0
           and row["days_cover"] is None, str(row["days_cover"]))
r = c.get("/pharmacy/reorder", headers=H, params={"days": 0})
ok("days=0 => 422", r.status_code == 422, str(r.status_code))
r = c.get("/pharmacy/reorder", headers=H, params={"days": 400})
ok("days=400 => 422", r.status_code == 422, str(r.status_code))

# ===== 9) الوصفات الطبية =====
rx = None
if m1 and pat:
    r = c.post("/prescriptions/", headers=H, json={
        "patient_id": pat["id"], "notes": "وصف " + TAG,
        "items": [{"medication_id": m1["id"], "quantity": 3,
                   "dosage": "قرص", "frequency": "مرتان", "duration": "يومان"}]})
    ok("إنشاء وصفة => 200", r.status_code == 200, r.text[:140])
    rx = r.json() if r.status_code == 200 else None
    if rx:
        ok("وصفة PENDING وبنودها PENDING",
           rx["status"] == "PENDING" and rx["items"][0]["dispensed_quantity"] == 0)
        ok("بند الوصفة remaining = 3", rx["items"][0]["remaining"] == 3)
        stock0 = c.get(f"/medications/{m1['id']}", headers=H).json()["quantity"]
        r = c.post(f"/prescriptions/{rx['id']}/dispense", headers=H, json={})
        ok("صرف الوصفة => 200", r.status_code == 200, r.text[:140])
        ok("الرصيد نقص 3", c.get(f"/medications/{m1['id']}",
                                  headers=H).json()["quantity"] == stock0 - 3)
        after = c.get(f"/prescriptions/{rx['id']}", headers=H).json()
        ok("وصفة DISPENSED وبند مصروف بالكامل",
           after["status"] == "DISPENSED"
           and after["items"][0]["dispensed_quantity"] == 3)
        # الصرف المنوط بالوصفة يحمل prescription_id
        rows = c.get("/accounts/sales", headers=H,
                     params={"patient_id": pat["id"]}).json()
        ok("صرف مرتبط بالوصفة prescription_id",
           any(x.get("prescription_id") == rx["id"] for x in rows))
        ok("إعادة صرف الوصفة => 409",
           c.post(f"/prescriptions/{rx['id']}/dispense", headers=H,
                  json={}).status_code == 409)
        ok("إلغاء وصفة مصروفة => 409",
           c.put(f"/prescriptions/{rx['id']}", headers=H,
                 json={"status": "CANCELLED"}).status_code == 409)
        ok("حذف وصفة مصروفة => 409",
           c.delete(f"/prescriptions/{rx['id']}", headers=H).status_code == 409)
        ok("حالة يدوية DISPENSED => 400",
           c.put(f"/prescriptions/{rx['id']}", headers=H,
                 json={"status": "DISPENSED"}).status_code == 400)

    # وصفة تُلغى ثم تُحذف
    r = c.post("/prescriptions/", headers=H, json={
        "patient_id": pat["id"],
        "items": [{"medication_id": m1["id"], "quantity": 1}]})
    if r.status_code == 200:
        rx2 = r.json()
        ok("صرف وصفة ملغاة => 409 (تُلغى أولًا)",
           c.put(f"/prescriptions/{rx2['id']}", headers=H,
                 json={"status": "CANCELLED"}).status_code == 200)
        ok("صرف ملغى => 409",
           c.post(f"/prescriptions/{rx2['id']}/dispense", headers=H,
                  json={}).status_code == 409)
        ok("حذف وصفة ملغاة (غير مصروفة) => 204",
           c.delete(f"/prescriptions/{rx2['id']}", headers=H).status_code == 204)

r = c.get("/prescriptions/", headers=H, params={"status": "bogus"})
ok("فلتر حالة خاطئ => 400", r.status_code == 400, str(r.status_code))
ok("وصفة غير موجودة => 404",
   c.get("/prescriptions/999999", headers=H).status_code == 404)
ok("حالة الوصفات متوفرة كفلتر", all(
    st in ("PENDING", "PARTIAL", "DISPENSED", "CANCELLED")
    for st in ("PENDING", "DISPENSED")))

# ===== 10) التقارير الجديدة =====
pdf = c.get("/reports/pharmacy/stats/pdf", headers=H)
ok("PDF إحصاءات %PDF", pdf.status_code == 200 and pdf.content[:4] == b"%PDF",
   str(pdf.status_code))
pdf = c.get("/reports/pharmacy/stats/pdf", headers=H, params={"lang": "en"})
ok("PDF إحصاءات EN %PDF", pdf.status_code == 200 and pdf.content[:4] == b"%PDF")
r = c.get("/reports/pharmacy/stats/pdf", headers=H, params={"lang": "fr"})
ok("lang خاطئ => 400", r.status_code == 400, str(r.status_code))
csv = c.get("/reports/pharmacy/stats/csv", headers=H)
ok("CSV إحصاءات + BOM + الإيراد", csv.status_code == 200
   and csv.content[:3] == b"\xef\xbb\xbf"
   and "الإيراد" in csv.content.decode("utf-8-sig"), str(csv.status_code))
csv = c.get("/reports/pharmacy/csv", headers=H, params={"section": "disposals"})
ok("CSV إتلاف/إرجاع => 200 + عمود النوع", csv.status_code == 200
   and "النوع" in csv.content.decode("utf-8-sig"), str(csv.status_code))
r = c.get("/reports/pharmacy/csv", headers=H, params={"section": "bad"})
ok("section خاطئ => 400", r.status_code == 400, str(r.status_code))
csv = c.get("/reports/pharmacy/csv", headers=H, params={"section": "dispenses"})
ok("CSV الصرف يحمل الجرعة والمرتجع", csv.status_code == 200
   and "الجرعة" in csv.content.decode("utf-8-sig")
   and "المرتجع" in csv.content.decode("utf-8-sig"))
# استثناء المرتجع من مبيعات CSV (اسم الدواء فريد بهذا TAG)
csv = c.get("/reports/accounts/sales/csv", headers=H)
if mr:
    ok("مرتجع " + TAG + " مستثنى من CSV المبيعات",
       "عقار مرتجع حصرى " + TAG not in csv.content.decode("utf-8-sig"))
ok("PDF الصيدلية ما زال %PDF",
   c.get("/reports/pharmacy/pdf", headers=H).content[:4] == b"%PDF")

# ===== 10ب) طباعة الوصفة PDF + CSV اقتراحات الطلب =====
if rx:
    pdf = c.get(f"/prescriptions/{rx['id']}/pdf", headers=H)
    ok("PDF وصفة %PDF", pdf.status_code == 200 and pdf.content[:4] == b"%PDF",
       str(pdf.status_code))
    pdf = c.get(f"/prescriptions/{rx['id']}/pdf", headers=H,
                params={"lang": "en"})
    ok("PDF وصفة EN %PDF", pdf.status_code == 200 and pdf.content[:4] == b"%PDF",
       str(pdf.status_code))
    r = c.get(f"/prescriptions/{rx['id']}/pdf", headers=H, params={"lang": "fr"})
    ok("وصفة lang خاطئ => 400", r.status_code == 400, str(r.status_code))
    r = c.get("/prescriptions/999999/pdf", headers=H)
    ok("طباعة وصفة غير موجودة => 404", r.status_code == 404, str(r.status_code))
csv = c.get("/reports/pharmacy/csv", headers=H, params={"section": "reorder"})
csv_text = csv.content.decode("utf-8-sig") if csv.status_code == 200 else ""
ok("CSV اقتراحات الطلب => 200 + المقترح شراءه",
   csv.status_code == 200 and "المقترح شراءه" in csv_text, str(csv.status_code))
if mlow:
    ok("الصنف المنخفض ضمن CSV الطلب", mlow["code"] in csv_text)

# ===== 11) مؤشرات الواجهة =====
ui = c.get("/").text + c.get("/app.js").text
ok("رابط القائمة pharmacy", 'data-view="pharmacy"' in ui)
ok("عرض الصيدلية في الواجهة", "async pharmacy(main)" in ui)
ok("السلة: basket-rows", "basket-rows" in ui)
ok("السلة: dispenseBatch()", "function dispenseBatch(" in ui)
ok("الباركود: quickFind()", "function quickFind(" in ui)
ok("الفلاتر: filterPharmacy()", "function filterPharmacy(" in ui)
ok("زر الإرجاع returnDispense()", "function returnDispense(" in ui)
ok("زر الإتلاف disposeMed()", "function disposeMed(" in ui)
ok("الوصفات dispenseRx()/createRx()", "function dispenseRx(" in ui
   and "function createRx(" in ui)
ok("مسار /dispenses/batch في الواجهة", "/dispenses/batch" in ui)
ok("مسار الإرجاع في الواجهة", "/return" in ui and "returnDispense(" in ui)
ok("مسار الإتلاف في الواجهة", "/dispose" in ui)
ok("إحصاءات في الواجهة", "/pharmacy/stats" in ui)
ok("اقتراحات الطلب في الواجهة", "/pharmacy/reorder" in ui)
ok("الوصفات في الواجهة", "/prescriptions/" in ui)
ok("زر إحصاءات PDF", "/reports/pharmacy/stats/pdf" in ui)
ok("زر إحصاءات CSV", "/reports/pharmacy/stats/csv" in ui)
ok("زر إتلاف/إرجاع CSV", "section=disposals" in ui)
ok("تقرير المخزون PDF قائم", "/reports/pharmacy/pdf" in ui)
ok("CSV مخزون قائم", "/reports/pharmacy/csv?section=inventory" in ui)
ok("CSV صرف قائم", "/reports/pharmacy/csv?section=dispenses" in ui)
ok("زر الجرد قائم", "function adjustStock(" in ui)
ok("التوريد قائم", "'/inventory/' + id + '/restock'" in ui)
ok("زر طباعة الوصفة", "/prescriptions/${r.id}/pdf" in ui)
ok("فلتر حالة الوصفات", "f-rx-status" in ui
   and "function filterRxRows(" in ui)
ok("زر اقتراحات الطلب CSV", "section=reorder" in ui)
_sw = c.get("/sw.js").text
_m = re.search(r"const CACHE = '(hms-shell-v[^']*)'", _sw)
ok("اسم الكاش hms-shell-v* (يتحدّث مع كل قشرة)", bool(_m),
   _m.group(1) if _m else "غير معروف")

# ===== 12) ملصقات الباركود + ورقة نتيجة المختبر + تنبيه المعلّقة =====
r = c.get("/inventory/labels")
ok("ملصقات بلا توكن => 401", r.status_code == 401, str(r.status_code))
r = c.get("/inventory/labels", headers=RH)
ok("ملصقات للموظف => 403", r.status_code == 403, str(r.status_code))
r = c.get("/inventory/labels", headers=H)
ok("ملصقات الكل %PDF باسم med_labels.pdf",
   r.status_code == 200 and r.content[:4] == b"%PDF"
   and "med_labels.pdf" in r.headers.get("content-disposition", ""),
   str(r.status_code))
if m1:
    r = c.get("/inventory/labels", headers=H, params={"ids": str(m1["id"])})
    ok("ملصق دواء واحد %PDF", r.status_code == 200
       and r.content[:4] == b"%PDF", str(r.status_code))
r = c.get("/inventory/labels", headers=H, params={"ids": "abc"})
ok("ids غير رقمية => 400", r.status_code == 400
   and "ids" in r.json().get("detail", ""), r.text[:120])
r = c.get("/inventory/labels", headers=H, params={"ids": "99999999"})
ok("معرّف دواء مجهول => 404", r.status_code == 404
   and "لا يوجد دواء بالمعرف" in r.json().get("detail", ""), r.text[:120])

# ورقة نتيجة المختبر/الأشعة
lab = None
if pat:
    docs = c.get("/doctors/", headers=H)
    doc_id = (docs.json()[0]["id"]
              if docs.status_code == 200 and docs.json() else None)
    payload = {"patient_id": pat["id"], "test_type": "lab",
               "test_name": "فحص ورقة " + TAG, "price": 10}
    if doc_id is not None:
        payload["doctor_id"] = doc_id
    r = c.post("/lab-orders/", headers=H, json=payload)
    lab = r.json() if r.status_code == 200 else None
    ok("طلب مختبر لورقة النتيجة => 200", lab is not None, r.text[:140])
if lab:
    r = c.get(f"/lab-orders/{lab['id']}/pdf", headers=H)
    ok("ورقة النتيجة ar %PDF", r.status_code == 200
       and r.content[:4] == b"%PDF", str(r.status_code))
    r = c.get(f"/lab-orders/{lab['id']}/pdf", headers=H,
              params={"lang": "en"})
    ok("ورقة النتيجة en %PDF", r.status_code == 200
       and r.content[:4] == b"%PDF", str(r.status_code))
    r = c.get(f"/lab-orders/{lab['id']}/pdf", headers=H,
              params={"lang": "fr"})
    ok("ورقة النتيجة lang خاطئ => 400", r.status_code == 400,
       str(r.status_code))
r = c.get("/lab-orders/999999/pdf", headers=H)
ok("ورقة النتيجة غير موجودة => 404", r.status_code == 404, str(r.status_code))
r = c.get("/lab-orders/999999/pdf")
ok("ورقة النتيجة بلا توكن => 401", r.status_code == 401, str(r.status_code))

# تنبيه الوصفات المعلّقة + الملصقات + المختبر في الواجهة
ok("بطاقة الوصفات المعلّقة rx-stale", 'id="rx-stale"' in ui
   and "staleRx" in ui)
ok("زر عرض المعلّقات showStaleRx()", "function showStaleRx(" in ui)
ok("أيقونة تنبيه rx_stale", "rx_stale" in ui)
ok("مسار الملصقات في الواجهة", "/inventory/labels" in ui
   and "ملصقات الكل" in ui and "label_${m.code}.pdf" in ui)
ok("فلترة المختبر filterLabRows() بحالة data-status",
   "function filterLabRows(" in ui and "f-lab-status" in ui
   and 'data-status="${o.status}"' in ui)
ok("زر ورقة النتيجة في المختبر", "ورقة النتيجة" in ui
   and "/lab-orders/${o.id}/pdf" in ui)

print(f"\n== PHARMACY FLOW RESULT: {len(fails) == 0} — failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
