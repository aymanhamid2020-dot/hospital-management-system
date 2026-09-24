# تدفق حي كامل: صرف → تسديد جزئي → تسديد كامل → ملخص → تقارير
import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"], "Content-Type": "application/json"}
fails = []


def ok(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


base = c.get("/accounts/summary", headers=H).json()

med = c.post("/medications/", headers=H, json={
    "code": "UIACC1", "name": "دواء الواجهة", "quantity": 40,
    "unit": "علبة", "price": 12.5, "min_quantity": 5})
med = med.json() if med.status_code == 200 else {
    "id": next(m["id"] for m in c.get("/medications/", headers=H).json()
               if m["code"] == "UIACC1")}
_pat = c.post("/patients/", headers=H, json={
    "full_name": "مريض واجهة حسابات", "date_of_birth": "1991-04-04",
    "gender": "ذكر", "phone": "0555777888", "email": "uiacc@example.com"})
pat = _pat.json() if _pat.status_code == 200 else {
    "id": next(p["id"] for p in c.get("/patients/", headers=H).json()
               if p["full_name"] == "مريض واجهة حسابات")}

d = None
if med.get("quantity", 0) < 10:
    # ذاتي الإصلاح: يصرف 4 في كل تشغيل — يعيد التوريد قبل النفاد
    rr = c.post(f"/inventory/{med['id']}/restock", headers=H, json={"quantity": 40})
    if rr.status_code == 200:
        med = c.get(f"/medications/{med['id']}", headers=H).json()

d = c.post("/dispenses/", headers=H, json={
    "medication_id": med["id"], "patient_id": pat["id"], "quantity": 4}).json()
did = d["id"]
ok("صرف 4 × 12.5 => total_price 50", d.get("total_price") == 50.0, str(d.get("total_price")))
ok("الحالة الابتدائية UNPAID", d.get("status") == "UNPAID")
ok("المدفوع 0", d.get("paid_amount") == 0)

p1 = c.put(f"/accounts/sales/{did}/payment", headers=H,
           json={"paid_amount": 20.0, "payment_method": "cash"}).json()
ok("دفعة 20 => PARTIAL", p1["status"] == "PARTIAL" and p1["paid_amount"] == 20.0)

# فلترة الحالة من الواجهة: status=PAID يجب ألا تُرجع العملية بعد
paid_ids = [x["id"] for x in c.get("/accounts/sales", headers=H,
                                   params={"status": "PAID"}).json()]
ok("فلتر status=PAID لا يشمل PARTIAL", did not in paid_ids)
part_ids = [x["id"] for x in c.get("/accounts/sales", headers=H,
                                   params={"status": "PARTIAL"}).json()]
ok("فلتر status=PARTIAL يشملها", did in part_ids)

p2 = c.put(f"/accounts/sales/{did}/payment", headers=H,
           json={"paid_amount": 50.0, "payment_method": "card"}).json()
ok("استبدال الدفعة بـ50 => PAID", p2["status"] == "PAID" and p2["paid_amount"] == 50.0)
ok("الطريقة صارت card", p2["payment_method"] == "card")

s = c.get("/accounts/summary", headers=H).json()
ok("summary.total_sales زاد 50", s["total_sales"] >= base["total_sales"] + 50,
   f"{base['total_sales']} -> {s['total_sales']}")
ok("summary.total_paid ≥ 50", s["total_paid"] >= 50)
ok("by_payment_method يحوي card", "card" in s["by_payment_method"])

# فلترة المريض والتواريخ واسم الصرف
by_pat = c.get("/accounts/sales", headers=H, params={"patient_id": pat["id"]}).json()
ok("فلتر patient_id", any(x["id"] == did for x in by_pat))
by_staff = c.get("/accounts/sales", headers=H, params={"staff": "admin"}).json()
ok("فلتر staff=admin", any(x["id"] == did for x in by_staff))
by_date = c.get("/accounts/sales", headers=H,
                params={"from_date": "2026-09-01", "to_date": "2026-09-30T23:59:59"}).json()
ok("فلتر التواريخ", isinstance(by_date, list))

# أخطاء متوقعة
ok("دفعة أكبر من الإجمالي => 400",
   c.put(f"/accounts/sales/{did}/payment", headers=H,
         json={"paid_amount": 999, "payment_method": "cash"}).status_code == 400)
ok("دفعة سالبة => 422",
   c.put(f"/accounts/sales/{did}/payment", headers=H,
         json={"paid_amount": -1, "payment_method": "cash"}).status_code == 422)
ok("عملية غير موجودة => 404",
   c.put("/accounts/sales/999999/payment", headers=H,
         json={"paid_amount": 5, "payment_method": "cash"}).status_code == 404)

# تقارير
csv = c.get("/reports/accounts/sales/csv", headers=H)
ok("CSV BOM + رأس عربي", csv.content[:3] == b"\xef\xbb\xbf"
   and "المريض".encode() in csv.content)
pdf = c.get("/reports/accounts/sales/pdf", headers=H)
ok("PDF عربي %PDF", pdf.content[:4] == b"%PDF")
pdfen = c.get("/reports/accounts/sales/pdf", headers=H, params={"lang": "en"})
ok("PDF إنجليزي %PDF", pdfen.content[:4] == b"%PDF")
ok("CSV غير مسجّل => 401", c.get("/reports/accounts/sales/csv").status_code == 401)

print(f"\n== FLOW RESULT: {len(fails) == 0} — failed: {len(fails)} ==")
raise SystemExit(1 if fails else 0)
