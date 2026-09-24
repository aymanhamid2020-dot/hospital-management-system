"""فحص مباشر: ترحيل القاعدة + ربط الفواتير + الدفع + ملف المريض PDF."""
import httpx

BASE = "http://127.0.0.1:8001"

tok = httpx.post(BASE + "/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
h = {"Authorization": "Bearer " + tok}

print("=== 1. الترحيل: أعمدة الفواتير الجديدة ===")
invs = httpx.get(BASE + "/invoices/", headers=h).json()
assert len(invs) > 0, "لا توجد فواتير"
sample = invs[0]
for field in ("appointment_id", "record_id", "payment_method", "paid_at"):
    assert field in sample, f"missing {field}"
    print(f"  {field}: OK = {sample[field]!r}")

print("\n=== 2. ربط فاتورة بموعد ===")
pats = httpx.get(BASE + "/patients/", headers=h).json()
docs = httpx.get(BASE + "/doctors/", headers=h).json()
appt = httpx.post(BASE + "/appointments/", headers=h, json={
    "patient_id": pats[0]["id"], "doctor_id": docs[0]["id"],
    "appointment_date": "2030-07-07T10:00:00", "reason": "اختبار ربط"}).json()
print("Appointment:", appt["id"])

inv = httpx.post(BASE + "/invoices/", headers=h, json={
    "patient_id": pats[0]["id"], "appointment_id": appt["id"],
    "amount": 199.5, "description": "فاتورة مرتبطة"}).json()
assert inv["appointment_id"] == appt["id"]
print(f"Invoice #{inv['id']} linked to appt #{inv['appointment_id']}")

# ربط خاطئ (مريض آخر) → 400
r = httpx.post(BASE + "/invoices/", headers=h, json={
    "patient_id": pats[1]["id"] if len(pats) > 1 else 9999,
    "appointment_id": appt["id"], "amount": 10, "description": "x"})
print("Wrong-patient link:", r.status_code, "-", r.json().get("detail", "")[:40])
assert r.status_code == 400

# فلترة حسب الموعد
flt = httpx.get(BASE + "/invoices/", headers=h, params={"appointment_id": appt["id"]}).json()
assert any(i["id"] == inv["id"] for i in flt)
print("Filter by appointment: OK")

print("\n=== 3. الدفع ===")
r = httpx.post(f"{BASE}/invoices/{inv['id']}/pay", headers=h, json={"method": "bitcoin"})
print("Bad method:", r.status_code, "-", r.json()["detail"][:50])
assert r.status_code == 400

r = httpx.post(f"{BASE}/invoices/{inv['id']}/pay", headers=h, json={"method": "card"})
paid = r.json()
print(f"Pay: {r.status_code} | status={paid['status']} method={paid['payment_method']} paid_at={paid['paid_at']}")
assert r.status_code == 200 and paid["status"] == "paid" and paid["paid_at"]

r = httpx.post(f"{BASE}/invoices/{inv['id']}/pay", headers=h, json={"method": "card"})
print("Double pay:", r.status_code, "-", r.json()["detail"])
assert r.status_code == 400

# فلترة status=paid
flt = httpx.get(BASE + "/invoices/", headers=h, params={"status": "paid"}).json()
assert any(i["id"] == inv["id"] for i in flt)
print("Filter status=paid: OK")

print("\n=== 4. ملف المريض PDF ===")
r = httpx.get(f"{BASE}/patients/{pats[0]['id']}/pdf", headers=h)
print(f"Patient PDF: {r.status_code} | {r.headers.get('content-type')} | {len(r.content)} bytes | magic={r.content[:5]}")
assert r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 5000
assert httpx.get(f"{BASE}/patients/{pats[0]['id']}/pdf").status_code == 401
print("Auth required: 401 OK")

# PDF الفاتورة المدفوعة (يتضمن تفاصيل الدفع)
r = httpx.get(f"{BASE}/invoices/{inv['id']}/pdf", headers=h)
print(f"Paid invoice PDF: {r.status_code} | {len(r.content)} bytes")
assert r.status_code == 200 and r.content[:5] == b"%PDF-"

print("\n=== 5. FK حي: حذف موعد يلغي ربط الفاتورة (SET NULL) ===")
r = httpx.delete(f"{BASE}/appointments/{appt['id']}", headers=h)
print("Delete appointment:", r.status_code)
assert r.status_code == 204
after = httpx.get(f"{BASE}/invoices/{inv['id']}", headers=h).json()
print(f"Invoice appointment_id after delete: {after['appointment_id']}")
assert after["appointment_id"] is None, "SET NULL did not work!"

# تنظيف
httpx.delete(f"{BASE}/invoices/{inv['id']}", headers=h)
print("\nALL LIVE BILLING/PDF TESTS PASSED ✅")
