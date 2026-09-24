# بحث عام Ctrl+K حيًّا على خادم8001: الأنواع الخمسة + قواعد الأدوار
# + الحدود والتحقق + مؤشرات الواجهة. يُشغَّل يدويًا: python search_flow_check.py
import time

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login",
             json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"],
     "Content-Type": "application/json"}
fails = []

# TAG فريد لكل تشغيل حتى يعمل الفحص على قاعدة مستخدمة (idempotent)
TAG = "Q" + format(int(time.time()) % 100000, "05d")


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def hdr(t):
    return {"Authorization": "Bearer " + t["access_token"],
            "Content-Type": "application/json"}


def rx_ids(headers, q):
    r = c.get("/search/", headers=headers, params={"q": q})
    if r.status_code != 200:
        return []
    return [x["id"] for x in r.json()["results"]
            if x["type"] == "prescription"]


# =====1) التحقق والحدود =====
ok("بلا توكن => 401",
   c.get("/search/", params={"q": "x"}).status_code == 401)
r = c.get("/search/", headers=H, params={"q": "   "})
ok("استعلام فارغ => 400 + رسالة عربية",
   r.status_code == 400 and "حرف واحد" in r.json()["detail"])
ok("بلا معامل q => 400",
   c.get("/search/", headers=H).status_code == 400)
ok("limit=0 => 422",
   c.get("/search/", headers=H,
         params={"q": "a", "limit": 0}).status_code == 422)
ok("limit=99 => 422",
   c.get("/search/", headers=H,
         params={"q": "a", "limit": 99}).status_code == 422)

# =====2) تجهيز الكيانات =====
r = c.post("/medications/", headers=H, json={
    "code": "QC" + TAG, "name": "دواء بحث " + TAG, "quantity": 30,
    "unit": "علبة", "price": 7.5, "min_quantity": 5})
med = r.json() if r.status_code == 200 else None
r = c.post("/patients/", headers=H, json={
    "full_name": "مريض بحث " + TAG, "date_of_birth": "1990-01-01",
    "gender": "ذكر", "phone": "0500000222",
    "email": f"q{TAG}@example.com"})
pat = r.json() if r.status_code == 200 else None
ok("تجهيز دواء ومريض", med is not None and pat is not None)

# طبيب مرتبط (سجل طبيب + حساب role=doctor بنفس البريد)
email = f"qs{TAG}@example.com"
r = c.post("/doctors/", headers=H, json={
    "full_name": "طبيب بحث " + TAG, "specialty": "باطنية",
    "license_number": "LQ" + TAG, "phone": "0511111111", "email": email})
doc = r.json() if r.status_code == 200 else None
u = "qs" + TAG
c.post("/auth/register", json={
    "username": u, "email": email, "full_name": "طبيب البحث",
    "password": "secret123", "role": "doctor"})
tok_d = c.post("/auth/login",
               json={"username": u, "password": "secret123"}).json()
HD = hdr(tok_d)
ok("تجهيز طبيب وحسابه",
   doc is not None and doc.get("id") and "access_token" in tok_d)

r = c.post("/appointments/", headers=H, json={
    "patient_id": pat["id"], "doctor_id": doc["id"],
    "appointment_date": "2031-04-04T10:00:00",
    "reason": f"سبب الزيارة {TAG}"})
appt = r.json() if r.status_code == 200 else None
r = c.post("/invoices/", headers=H, json={
    "patient_id": pat["id"], "amount": 150.0,
    "description": f"كشف بحث {TAG}"})
inv = r.json() if r.status_code == 200 else None
ok("تجهيز موعد وفاتورة", appt is not None and inv is not None)

# =====3) نتائج الأنواع الخمسة =====
r = c.get("/search/", headers=H, params={"q": TAG})
body = r.json() if r.status_code == 200 else {"results": []}
by = {(x["type"], x["id"]): x for x in body.get("results", [])}
ok("مرضى: النتيجة ووجهتها",
   ("patient", pat["id"]) in by
   and by[("patient", pat["id"])]["view"] == "patients")
ok("أدوية: النتيجة ووجهتها",
   ("medication", med["id"]) in by
   and by[("medication", med["id"])]["view"] == "inventory")
ok("مواعيد: النتيجة ووجهتها",
   ("appointment", appt["id"]) in by
   and by[("appointment", appt["id"])]["view"] == "appointments")
ok("فواتير: النتيجة ووجهتها",
   ("invoice", inv["id"]) in by
   and by[("invoice", inv["id"])]["view"] == "invoices")
hit = by.get(("patient", pat["id"]), {})
ok("حقول النتيجة (عنوان/فرعي/شارة/أيقونة)",
   bool(hit.get("title")) and bool(hit.get("subtitle"))
   and hit.get("type_label") == "مريض" and bool(hit.get("icon")))

# حساسية الأحرف: مريض بمزج حالة الأحرف والبحث بحروف صغيرة
mixed = "QwErTy" + TAG
c.post("/patients/", headers=H, json={
    "full_name": mixed, "date_of_birth": "1992-02-02", "gender": "ذكر",
    "phone": "0500000333", "email": f"qc{TAG}@example.com"})
r = c.get("/search/", headers=H, params={"q": mixed.lower()})
ok("حساسية الأحرف (ilike)",
   r.status_code == 200 and any(
       x["type"] == "patient" and x["title"] == mixed
       for x in r.json().get("results", [])))

# مطابقة رقمية (معرف المريض)
r = c.get("/search/", headers=H, params={"q": str(pat["id"])})
ok("مطابقة رقم (المعرف)",
   r.status_code == 200 and any(
       x["type"] == "patient" and x["id"] == pat["id"]
       for x in r.json().get("results", [])))

r = c.get("/search/", headers=H, params={"q": "zz-no-such-zzz"})
ok("لا نتائج => مصفوفة فارغة",
   r.status_code == 200 and r.json()["results"] == [])

# =====4) الوصفات وقواعد الأدوار =====
r = c.post("/prescriptions/", headers=HD, json={
    "patient_id": pat["id"],
    "items": [{"medication_id": med["id"], "quantity": 1}],
    "notes": f"ملاحظة بحث {TAG} الأولى"})
rx1 = r.json() if r.status_code == 200 else None
r = c.post("/prescriptions/", headers=H, json={
    "patient_id": pat["id"],
    "items": [{"medication_id": med["id"], "quantity": 1}],
    "notes": f"ملاحظة بحث {TAG} الثانية"})
rx2 = r.json() if r.status_code == 200 else None
ok("الطبيب ينشئ وصفته والمدير ينشئ وصفة بلا طبيب",
   rx1 is not None and rx2 is not None)

ids_d = rx_ids(HD, TAG)
ok("الطبيب يجد وصفته فقط",
   rx1 and rx2 and rx1["id"] in ids_d and rx2["id"] not in ids_d)
ids_a = rx_ids(H, TAG)
ok("المدير يجد الوصفتين",
   rx1 and rx2 and rx1["id"] in ids_a and rx2["id"] in ids_a)

# الاستقبال: حساب مُستقل يُسجَّل الآن (الدور الافتراضي موظف استقبال)
u3 = "qr" + TAG
c.post("/auth/register", json={
    "username": u3, "email": f"qr{TAG}@example.com",
    "full_name": "موظف استقبال", "password": "secret123"})
tok_r = c.post("/auth/login",
               json={"username": u3, "password": "secret123"}).json()
ids_r = rx_ids(hdr(tok_r), TAG)
ok("الاستقبال يجد الوصفتين",
   rx1 and rx2 and "access_token" in tok_r
   and rx1["id"] in ids_r and rx2["id"] in ids_r)

# طبيب بلا سجل مرتبط => لا وصفات في البحث
u2 = "qn" + TAG
c.post("/auth/register", json={
    "username": u2, "email": f"qn{TAG}@example.com",
    "full_name": "طبيب بلا سجل", "password": "secret123",
    "role": "doctor"})
tok_n = c.post("/auth/login",
               json={"username": u2, "password": "secret123"}).json()
ok("طبيب غير مرتبط => لا وصفات",
   "access_token" in tok_n and not rx_ids(hdr(tok_n), TAG))

# =====5) الحدود =====
r = c.get("/search/", headers=H, params={"q": TAG, "limit": 1})
ok("limit=1 يكبح كل نوع",
   r.status_code == 200
   and len([x for x in r.json()["results"]
            if x["type"] == "patient"]) <= 1)

# =====6) مؤشرات الواجهة =====
html = c.get("/ui/").text
js = c.get("/ui/app.js").text
css = c.get("/ui/app.css").text
ok("الواجهة: عناصر النافذة",
   'id="gsearch-back"' in html and 'id="gsearch-input"' in html
   and 'id="gsearch-results"' in html)
ok("الواجهة: زر الشريط",
   'onclick="openGSearch()"' in html)
ok("الواجهة: الكود والاختصار",
   "function openGSearch(" in js and "/search/?q=" in js
   and "e.ctrlKey" in js)
ok("الواجهة: أنماط CSS",
   "#gsearch-back" in css and ".gs-item" in css and ".gs-empty" in css)

# =====7) التنظيف =====
ok("حذف الوصفتين (غير مصروفتين)",
   rx1 and rx2
   and c.delete(f"/prescriptions/{rx1['id']}",
                headers=H).status_code in (200, 204, 404)
   and c.delete(f"/prescriptions/{rx2['id']}",
                headers=H).status_code in (200, 204, 404))
ok("حذف الفاتورة والموعد والمريض",
   c.delete(f"/invoices/{inv['id']}",
            headers=H).status_code in (200, 204, 404)
   and c.delete(f"/appointments/{appt['id']}",
                headers=H).status_code in (200, 204, 404)
   and c.delete(f"/patients/{pat['id']}",
                headers=H).status_code in (200, 204, 404))
c.delete(f"/medications/{med['id']}", headers=H)  # إن وُجد مسار حذفه

print(f"\n== SEARCH FLOW RESULT: {len(fails) == 0} "
      f"— failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
