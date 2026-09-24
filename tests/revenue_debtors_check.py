# فحص حي لـ /accounts/revenue و /accounts/debtors على الخادم الشغّال
import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"]}
fails = []


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


ok("revenue 200", c.get("/accounts/revenue", headers=H).status_code == 200)
rev = c.get("/accounts/revenue", headers=H).json()
ok("revenue list", isinstance(rev, list))
if rev:
    p = rev[0]
    ok("revenue حقول", all(k in p for k in ("date", "sales", "collected", "count")), str(p))
    ok("revenue collected ≤ sales", all(x["collected"] <= x["sales"] + 0.01 for x in rev))
    ok("revenue days مرتبة", [x["date"] for x in rev] == sorted(x["date"] for x in rev))

rev_m = c.get("/accounts/revenue", headers=H, params={"group": "month"})
ok("revenue group=month 200 + شهور 7 خانات",
   rev_m.status_code == 200 and all(len(x["date"]) == 7 for x in rev_m.json()),
   str(rev_m.status_code))
ok("revenue group خاطئ => 400",
   c.get("/accounts/revenue", headers=H, params={"group": "bad"}).status_code == 400)
ok("revenue فترة خاطئة => 400",
   c.get("/accounts/revenue", headers=H, params={"period": "bad"}).status_code == 400)
ok("revenue بدون توكن => 401", c.get("/accounts/revenue").status_code == 401)

ok("debtors 200", c.get("/accounts/debtors", headers=H).status_code == 200)

# نضمن وجود مدين: نصرف عملية دون تسديد
H2 = {"Authorization": "Bearer " + tok["access_token"], "Content-Type": "application/json"}
m = c.post("/medications/", headers=H2, json={
    "code": "DEBT1", "name": "دواء الدين", "quantity": 60,
    "unit": "علبة", "price": 9.0, "min_quantity": 5})
if m.status_code == 200:
    med_id = m.json()["id"]
else:
    med_id = next(x["id"] for x in c.get("/medications/", headers=H).json()
                  if x["code"] == "DEBT1")
p = c.post("/patients/", headers=H2, json={
    "full_name": "مريض مدين", "date_of_birth": "1988-08-08",
    "gender": "ذكر", "phone": "0555999000", "email": "debtor@example.com"})
if p.status_code == 200:
    pid = p.json()["id"]
else:
    pid = next(x["id"] for x in c.get("/patients/", headers=H).json()
               if x["full_name"] == "مريض مدين")
d1 = c.post("/dispenses/", headers=H2, json={
    "medication_id": med_id, "patient_id": pid, "quantity": 2})
ok("بذر صرف غير مسدّد", d1.status_code == 200, str(d1.status_code))
ok("الحالة UNPAID", d1.json().get("status") == "UNPAID")
ok("total = 18", d1.json().get("total_price") == 18.0, str(d1.json().get("total_price")))

deb = c.get("/accounts/debtors", headers=H).json()
ok("debtors list", isinstance(deb, list))
if deb:
    d = deb[0]
    ok("debtors حقول", all(k in d for k in
       ("patient_id", "full_name", "operations", "total", "paid", "outstanding")), str(d))
    ok("debtors outstanding = total - paid",
       all(abs(x["total"] - x["paid"] - x["outstanding"]) < 0.02 for x in deb))
    ok("debtors مرتدة تنازليًا",
       [x["outstanding"] for x in deb] == sorted([x["outstanding"] for x in deb], reverse=True))
    ok("لا يوجد مسدد بالكامل في المدينين", all(x["outstanding"] > 0 for x in deb))
    one = c.get("/accounts/debtors", headers=H,
                params={"min_outstanding": deb[0]["outstanding"] + 1}).json()
    ok("min_outstanding يرفع الصغار", all(x["outstanding"] >= deb[0]["outstanding"] + 1
                                          for x in one))

# تحقق: كل مدين له عمليات غير مسددة فعلًا
for d in deb[:3]:
    rows = c.get("/accounts/sales", headers=H, params={"patient_id": d["patient_id"]}).json()
    unpaid = [r for r in rows if r["status"] != "PAID"]
    ok(f"مدين #{d['patient_id']} له {len(unpaid)} غير مسددة", len(unpaid) == d["operations"])

ok("debtors بدون توكن => 401", c.get("/accounts/debtors").status_code == 401)
ok("debtors min سالب => 422",
   c.get("/accounts/debtors", headers=H, params={"min_outstanding": -1}).status_code == 422)

print(f"\n== REVENUE/DEBTORS RESULT: {len(fails) == 0} — failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
