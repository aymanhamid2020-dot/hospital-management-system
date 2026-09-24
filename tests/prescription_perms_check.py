# مصفوفة صلاحيات الوصفات حيًّا على خادم 8001: سبعة مسارات × الأدوار
# (مدير/طبيب مالك/طبيب غير مالك/طبيب بلا سجل/استقبال/بلا توكن)
# + قواعد الحالات وما بعد الصرف. يُشغَّل يدويًا: python prescription_perms_check.py
import time

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login",
             json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"],
     "Content-Type": "application/json"}
fails = []

# TAG فريد لكل تشغيل حتى يعمل الفحص على قاعدة مستخدمة (idempotent)
TAG = "R" + format(int(time.time()) % 100000, "05d")


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def hdr(t):
    return {"Authorization": "Bearer " + t["access_token"],
            "Content-Type": "application/json"}


# ===== التجهيز: دواء + مريض + وصفة المدير =====
r = c.post("/medications/", headers=H, json={
    "code": "PC" + TAG, "name": "دواء صلاحيات " + TAG, "quantity": 50,
    "unit": "علبة", "price": 5.0, "min_quantity": 5})
med = r.json() if r.status_code == 200 else None

r = c.post("/patients/", headers=H, json={
    "full_name": "مريض صلاحيات " + TAG, "date_of_birth": "1990-01-01",
    "gender": "ذكر", "phone": "0500000111",
    "email": f"pc{TAG}@example.com"})
pat = r.json() if r.status_code == 200 else None
ok("تجهيز دواء ومريض الفحص", med is not None and pat is not None)

rx_a = None
body = None
if med and pat:
    body = {"patient_id": pat["id"],
            "items": [{"medication_id": med["id"], "quantity": 2}]}
    r = c.post("/prescriptions/", headers=H,
               json={**body, "notes": "صلاحيات " + TAG})
    rx_a = r.json() if r.status_code == 200 else None
    ok("وصفة المدير جاهزة PENDING",
       rx_a is not None and rx_a["status"] == "PENDING", r.text[:140])

# ===== الطبقات: طبيب مالك + طبيب غير مالك + طبيب بلا سجل + استقبال =====
email_o = f"own{TAG}@test.com"
r = c.post("/doctors/", headers=H, json={
    "full_name": "طبيب مالك", "specialty": "باطنية",
    "license_number": "L-OW" + TAG, "phone": "0533333333",
    "email": email_o})
ok("سجل طبيب المالك", r.status_code == 200, r.text[:120])
u_o = "own_" + TAG
c.post("/auth/register", json={"username": u_o, "email": email_o,
                               "full_name": "طبيب مالك",
                               "password": "secret123", "role": "doctor"})
to = c.post("/auth/login",
            json={"username": u_o, "password": "secret123"}).json()
HO = hdr(to)

email_x = f"oth{TAG}@test.com"
c.post("/doctors/", headers=H, json={
    "full_name": "طبيب آخر", "specialty": "جراحة",
    "license_number": "L-OT" + TAG, "phone": "0544444444",
    "email": email_x})
u_x = "oth_" + TAG
c.post("/auth/register", json={"username": u_x, "email": email_x,
                               "full_name": "طبيب آخر",
                               "password": "secret123", "role": "doctor"})
tx = c.post("/auth/login",
            json={"username": u_x, "password": "secret123"}).json()
HX = hdr(tx)

u_n = "nolink_" + TAG
c.post("/auth/register", json={"username": u_n, "email": f"{u_n}@test.com",
                               "full_name": "طبيب بلا سجل",
                               "password": "secret123", "role": "doctor"})
tn = c.post("/auth/login",
            json={"username": u_n, "password": "secret123"}).json()
HN = hdr(tn)

u_r = "recp_" + TAG
c.post("/auth/register", json={"username": u_r, "email": f"{u_r}@test.com",
                               "full_name": "موظف استقبال",
                               "password": "secret123"})
tr = c.post("/auth/login",
            json={"username": u_r, "password": "secret123"}).json()
HR = hdr(tr)
ok("حسابات الأدوار الأربعة جاهزة",
   all(t.get("access_token") for t in (to, tx, tn, tr)))

# وصفة الطبيب المالك (تُنسب له عبر ربط البريد)
rx_d = None
if med and pat and to.get("access_token") and body:
    r = c.post("/prescriptions/", headers=HO, json=body)
    rx_d = r.json() if r.status_code == 200 else None
    ok("وصفة المالك + doctor_id من ربط البريد",
       rx_d is not None and rx_d.get("doctor_id") is not None, r.text[:140])

RXA = rx_a["id"] if rx_a else 999999
RXD = rx_d["id"] if rx_d else 999999

# ===== 1) المصادقة: المسارات السبعة بلا توكن => 401 =====
ok("GET / بلا توكن => 401", c.get("/prescriptions/").status_code == 401)
ok("GET /{id} بلا توكن => 401",
   c.get(f"/prescriptions/{RXA}").status_code == 401)
ok("GET /{id}/pdf بلا توكن => 401",
   c.get(f"/prescriptions/{RXA}/pdf").status_code == 401)
ok("POST / بلا توكن => 401",
   c.post("/prescriptions/", json={}).status_code == 401)
ok("PUT /{id} بلا توكن => 401",
   c.put(f"/prescriptions/{RXA}", json={}).status_code == 401)
ok("DELETE /{id} بلا توكن => 401",
   c.delete(f"/prescriptions/{RXA}").status_code == 401)
ok("POST /{id}/dispense بلا توكن => 401",
   c.post(f"/prescriptions/{RXA}/dispense", json={}).status_code == 401)

# ===== 2) موظف الاستقبال: يقرأ ويطبع ولا ينشئ/يعدّل/يحذف =====
ok("استقبال GET / => 200",
   c.get("/prescriptions/", headers=HR).status_code == 200)
if body:
    ok("استقبال POST / => 403",
       c.post("/prescriptions/", headers=HR, json=body).status_code == 403)
ok("استقبال PUT /{id} => 403",
   c.put(f"/prescriptions/{RXA}", headers=HR,
         json={"notes": "محاولة"}).status_code == 403)
ok("استقبال DELETE /{id} => 403",
   c.delete(f"/prescriptions/{RXA}", headers=HR).status_code == 403)
ok("استقبال GET /{id} => 200 (قراءة مسموحة)",
   c.get(f"/prescriptions/{RXA}", headers=HR).status_code == 200)
r = c.get(f"/prescriptions/{RXA}/pdf", headers=HR)
ok("استقبال PDF => 200 %PDF",
   r.status_code == 200 and r.content[:4] == b"%PDF", str(r.status_code))

# ===== 3) الطبيب المالك =====
r = c.get("/prescriptions/", headers=HO)
ids = [x["id"] for x in r.json()] if r.status_code == 200 else []
ok("مالك GET / => 200", r.status_code == 200, str(r.status_code))
ok("المالك يرى وصفته", RXD in ids, str(ids[-5:]))
ok("المالك لا يرى وصفات المدير", RXA not in ids, str(ids[:5]))
ok("مالك GET /{id} صاحبه => 200",
   c.get(f"/prescriptions/{RXD}", headers=HO).status_code == 200)
r = c.get(f"/prescriptions/{RXD}/pdf", headers=HO)
ok("مالك PDF وصفته => 200 %PDF",
   r.status_code == 200 and r.content[:4] == b"%PDF", str(r.status_code))
if body:
    r = c.post("/prescriptions/", headers=HO, json=body)
    ok("مالك POST / => 200", r.status_code == 200, r.text[:140])
ok("مالك PUT وصفته => 200",
   c.put(f"/prescriptions/{RXD}", headers=HO,
         json={"notes": "تعديل المالك " + TAG}).status_code == 200)
ok("مالك GET وصفة المدير => 403",
   c.get(f"/prescriptions/{RXA}", headers=HO).status_code == 403)
ok("مالك PDF وصفة المدير => 403",
   c.get(f"/prescriptions/{RXA}/pdf", headers=HO).status_code == 403)
ok("مالك PUT وصفة المدير => 403",
   c.put(f"/prescriptions/{RXA}", headers=HO,
         json={"notes": "x"}).status_code == 403)
ok("مالك DELETE (ليس مديرًا) => 403",
   c.delete(f"/prescriptions/{RXA}", headers=HO).status_code == 403)

# ===== 4) الطبيب غير مالك =====
ok("غير مالك GET /{id} => 403",
   c.get(f"/prescriptions/{RXD}", headers=HX).status_code == 403)
ok("غير مالك PDF => 403",
   c.get(f"/prescriptions/{RXD}/pdf", headers=HX).status_code == 403)
ok("غير مالك PUT => 403",
   c.put(f"/prescriptions/{RXD}", headers=HX,
         json={"notes": "x"}).status_code == 403)
ok("غير مالك DELETE => 403",
   c.delete(f"/prescriptions/{RXD}", headers=HX).status_code == 403)

# ===== 5) طبيب بلا سجل طبيب مرتبط =====
if body:
    ok("بلا سجل POST / => 403",
       c.post("/prescriptions/", headers=HN, json=body).status_code == 403)
r = c.get("/prescriptions/", headers=HN)
ok("بلا سجل GET / => 200 وقائمة فارغة",
   r.status_code == 200 and r.json() == [], r.text[:120])

# ===== 6) قواعد الحالة (المدير) =====
ok("فلتر status خاطئ => 400",
   c.get("/prescriptions/", headers=H,
         params={"status": "bogus"}).status_code == 400)
r = c.get(f"/prescriptions/{RXA}/pdf", headers=H, params={"lang": "fr"})
ok("PDF lang خاطئ => 400", r.status_code == 400, str(r.status_code))
r = c.get("/prescriptions/999999/pdf", headers=H, params={"lang": "fr"})
ok("PDF lang خاطئ يسبق الوجود (id مجهول) => 400",
   r.status_code == 400, str(r.status_code))
ok("وصفة مجهولة GET => 404",
   c.get("/prescriptions/999999", headers=H).status_code == 404)
ok("وصفة مجهولة PDF => 404",
   c.get("/prescriptions/999999/pdf", headers=H).status_code == 404)
ok("وصفة مجهولة DELETE => 404",
   c.delete("/prescriptions/999999", headers=H).status_code == 404)
ok("حالة يدوية DISPENSED => 400",
   c.put(f"/prescriptions/{RXA}", headers=H,
         json={"status": "DISPENSED"}).status_code == 400)

# ===== 7) الصرف (أي مستخدم) وما بعد الصرف =====
if rx_d:
    r = c.post(f"/prescriptions/{rx_d['id']}/dispense", headers=HR, json={})
    ok("استقبال يصرف وصفة (أي مستخدم) => 200", r.status_code == 200,
       r.text[:140])
    ok("إعادة الصرف => 409",
       c.post(f"/prescriptions/{rx_d['id']}/dispense",
              headers=H, json={}).status_code == 409)
    ok("إلغاء مصروفة => 409",
       c.put(f"/prescriptions/{rx_d['id']}", headers=H,
             json={"status": "CANCELLED"}).status_code == 409)
    ok("حذف مصروفة => 409",
       c.delete(f"/prescriptions/{rx_d['id']}",
                headers=H).status_code == 409)

# وصفة تُلغى ثم تُحذف (تنظيف المسار)
if med and pat:
    r = c.post("/prescriptions/", headers=H,
               json={"patient_id": pat["id"],
                     "items": [{"medication_id": med["id"], "quantity": 1}]})
    rx_b = r.json() if r.status_code == 200 else None
    if rx_b:
        ok("إلغاء وصفة PENDING => 200",
           c.put(f"/prescriptions/{rx_b['id']}", headers=H,
                 json={"status": "CANCELLED"}).status_code == 200)
        ok("صرف ملغاة => 409",
           c.post(f"/prescriptions/{rx_b['id']}/dispense",
                  headers=H, json={}).status_code == 409)
        ok("حذف ملغاة (غير مصروفة) => 204",
           c.delete(f"/prescriptions/{rx_b['id']}",
                    headers=H).status_code == 204)
        ok("حذف الملغاة ثانيًا => 404",
           c.delete(f"/prescriptions/{rx_b['id']}",
                    headers=H).status_code == 404)

print(f"\n== PRESCRIPTION PERMS RESULT: {len(fails) == 0} "
      f"— failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
