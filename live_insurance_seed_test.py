"""اختبار حي: التأمين + المرفقات في السجلات + البيانات التجريبية."""
import io
import sys

import httpx

BASE = "http://127.0.0.1:8001"
ok = 0
fail = 0


def check(cond, msg):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {msg}")
    else:
        fail += 1
        print(f"  ❌ {msg}")


c = httpx.Client(base_url=BASE, timeout=30)

# ---------- 1) تسجيل الدخول ----------
r = c.post("/auth/login", json={"username": "admin", "password": "admin123"})
check(r.status_code == 200, "تسجيل دخول المدير")
H = {"Authorization": f"Bearer {r.json()['access_token']}"}

# ---------- 2) البيانات التجريبية ----------
r = c.get("/patients/", headers=H)
check(r.status_code == 200 and len(r.json()) >= 10, f"المرضى التجريبية ({len(r.json())} مريض)")
r = c.get("/doctors/", headers=H)
check(r.status_code == 200 and len(r.json()) >= 6, f"الأطباء التجريبية ({len(r.json())} طبيب)")
r = c.get("/departments/", headers=H)
check(r.status_code == 200 and len(r.json()) == 5, f"الأقسام ({len(r.json())})")
r = c.get("/beds/", headers=H)
check(r.status_code == 200 and len(r.json()) >= 18, f"الأسرّة ({len(r.json())} سرير)")
r = c.get("/appointments/", headers=H)
check(r.status_code == 200 and len(r.json()) >= 10, f"المواعيد ({len(r.json())} — منها واحدة خلال 6 ساعات 🔔)")

# حساب طبيب تجريبي
r2 = c.post("/auth/login", json={"username": "demo_doc1", "password": "demo12345"})
check(r2.status_code == 200, "دخول الطبيب التجريبي demo_doc1/demo12345")

# ---------- 3) فواتير التأمين ----------
r = c.get("/invoices/", headers=H, params={"status": "paid"})
check(r.status_code == 200, "قائمة الفواتير المدفوعة")
ins_invs = [i for i in r.json() if i.get("insurer")]
check(len(ins_invs) >= 2, f"فواتير ببيانات تأمين ({len(ins_invs)}: "
      + "، ".join(sorted({i['insurer'] for i in ins_invs})) + ")")

# دفع بتأمين بلا شركة تأمين → 400
pat_id = c.get("/patients/", headers=H).json()[0]["id"]
r = c.post("/invoices/", headers=H, json={
    "patient_id": pat_id, "amount": 50, "description": "اختبار رفض التأمين"})
check(r.status_code == 200, "إنشاء فاتورة بدون تأمين")
inv_no_ins = r.json()["id"]
r = c.post(f"/invoices/{inv_no_ins}/pay", headers=H, json={"method": "insurance"})
check(r.status_code == 400 and "شركة التأمين" in r.json().get("detail", ""),
      "رفض الدفع بالتأمين بدون شركة تأمين (400)")

# دفع بتأمين مع شركة → 200
r = c.post("/invoices/", headers=H, json={
    "patient_id": pat_id, "amount": 120, "description": "اختبار تأمين سليم",
    "insurer": "التعاونية", "policy_number": "POL-LIVE-001"})
inv_ok = r.json()["id"]
r = c.post(f"/invoices/{inv_ok}/pay", headers=H, json={"method": "insurance"})
check(r.status_code == 200 and r.json()["payment_method"] == "insurance"
      and r.json()["insurer"] == "التعاونية", "دفع بالتأمين مع بيانات سليمة")

# PDF فاتورة التأمين
r = c.get(f"/invoices/{inv_ok}/pdf", headers=H)
check(r.status_code == 200 and r.content[:5] == b"%PDF-", "PDF فاتورة التأمين")

# تنظيف
c.delete(f"/invoices/{inv_no_ins}", headers=H)
c.delete(f"/invoices/{inv_ok}", headers=H)

# ---------- 4) المرفقات داخل السجلات ----------
r = c.get("/medical-records/", headers=H)
recs = r.json()
check(r.status_code == 200 and len(recs) >= 6, f"السجلات الطبية ({len(recs)})")

r = c.get("/attachments/", headers=H)
atts = r.json()
check(len(atts) >= 3, f"المرفقات التجريبية ({len(atts)})")
linked = [a for a in atts if a.get("record_id")]
check(len(linked) == 3, "كل المرفقات مربوطة بسجل طبي")

# فلترة مرفقات سجل محدد
rid = linked[0]["record_id"]
r = c.get("/attachments/", headers=H, params={"record_id": rid})
check(r.status_code == 200 and len(r.json()) >= 1,
      f"فلترة مرفقات السجل #{rid} ({len(r.json())} مرفق)")

# معاينة وتنزيل مرفق
aid = linked[0]["id"]
r = c.get(f"/attachments/{aid}/file", headers=H)
check(r.status_code == 200 and r.headers.get("content-type", "").startswith("image"),
      "معاينة ملف PNG (content-type image)")

# ---------- 5) إحصاءات لوحة التحكم بالبيانات الجديدة ----------
r = c.get("/dashboard/stats", headers=H)
st = r.json()
check(r.status_code == 200 and st.get("total_patients", 0) >= 10,
      f"لوحة التحكم: {st.get('total_patients')} مريض / {st.get('total_appointments')} موعد / "
      f"{st.get('revenue_paid')} ر.س محصلة")

print("\n" + "=" * 50)
print(f"النتيجة: {ok} ناجح ✅ / {fail} فاشل ❌")
print("=" * 50)
sys.exit(1 if fail else 0)
