"""اختبار حي شامل داخل حاوية Docker (قاعدة fresh).

التشغيل:
    docker run -d --name hms-test -p 18080:8000 hms-hospital:test
    python tests/live_container_test.py
    docker rm -f hms-test

يغطي: الصحة + المصادقة + دورة كاملة (طبيب ← مريض ← موعد ← فاتورة
← دفع/تأمين) + تصدير/استيراد CSV + تقارير PDF + إحصاءات + إشعارات
+ حالة النظام العامة /status (JSON دون توكن).
"""
import os
import sys

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("LIVE_BASE", "http://127.0.0.1:18080")
PASSED = FAILED = 0


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {extra}")


def main():
    global PASSED, FAILED
    c = httpx.Client(base_url=BASE, timeout=30.0)

    # ===== 1) الحاوية والواجهة =====
    r = c.get("/health")
    check("health -> 200 healthy", r.status_code == 200
          and r.json().get("status") == "healthy"
          and r.json().get("service") == "hospital-management-system",
          r.text[:120])
    ui = c.get("/ui/")
    # بعد تجزئة الواجهة: JS صار في /ui/app.js — المؤشرات تفحص HTML + JS معًا
    ui_all = ui.text + c.get("/ui/app.js").text
    check("UI served", ui.status_code == 200)
    check("UI has export button", "export.csv" in ui_all)
    check("UI has complete-appointment button", "completed')" in ui_all)
    check("UI has doctor report gate", "isAdmin() || isDoctor()" in ui_all)

    # ===== 2) المصادقة =====
    check("no token -> 401", c.get("/patients/").status_code == 401)
    r = c.post("/auth/login", json={"username": "admin", "password": "admin123"})
    check("seeded admin login", r.status_code == 200, r.text[:150])
    if r.status_code != 200:
        print(f"\n==== LIVE CONTAINER RESULT: {PASSED} passed, {FAILED} failed ====")
        return 1
    h = {"Authorization": "Bearer " + r.json()["access_token"]}

    # ===== 3) طبيب =====
    r = c.post("/doctors/", headers=h, json={
        "full_name": "د. اختبار الحاوية", "specialty": "باطنة",
        "license_number": "CNT-0001", "phone": "0501111111",
        "email": "container_doc@hospital-demo.com"})
    check("create doctor", r.status_code == 200, r.text[:150])
    doctor_id = r.json().get("id")

    # ===== 4) مريض =====
    r = c.post("/patients/", headers=h, json={
        "full_name": "مريض الاختبار الحي", "date_of_birth": "1990-05-15T00:00:00",
        "gender": "ذكر", "phone": "0502222222",
        "email": "container_pat@hospital-demo.com",
        "address": "الرياض", "blood_type": "O+"})
    check("create patient", r.status_code == 200, r.text[:150])
    patient_id = r.json().get("id")

    # ===== 5) دورة الموعد =====
    aid = None
    if doctor_id and patient_id:
        r = c.post("/appointments/", headers=h, json={
            "patient_id": patient_id, "doctor_id": doctor_id,
            "appointment_date": "2032-03-03T09:00:00", "reason": "اختبار الحاوية"})
        check("create appointment (pending)", r.status_code == 200, r.text[:150])
        aid = r.json().get("id")
        if aid:
            r1 = c.put(f"/appointments/{aid}", headers=h, json={"status": "confirmed"})
            check("pending -> confirmed", r1.status_code == 200
                  and r1.json()["status"] == "confirmed")
            r2 = c.put(f"/appointments/{aid}", headers=h, json={"status": "completed"})
            check("confirmed -> completed", r2.status_code == 200
                  and r2.json()["status"] == "completed")

    # ===== 6) فاتورة + دفع + قاعدة التأمين =====
    inv_paid = inv_desc = None
    if patient_id:
        inv_desc = "فحص داخل الحاوية"
        r = c.post("/invoices/", headers=h, json={
            "patient_id": patient_id, "amount": 250.5, "description": inv_desc})
        check("create invoice", r.status_code == 200, r.text[:150])
        inv_paid = r.json().get("id")
        if inv_paid:
            rp = c.post(f"/invoices/{inv_paid}/pay", headers=h, json={"method": "cash"})
            check("pay cash -> paid", rp.status_code == 200
                  and rp.json().get("status") == "paid", rp.text[:150])
        r = c.post("/invoices/", headers=h, json={
            "patient_id": patient_id, "amount": 100, "description": "بانتظار التأمين"})
        inv2 = r.json().get("id") if r.status_code == 200 else None
        if inv2:
            rp = c.post(f"/invoices/{inv2}/pay", headers=h, json={"method": "insurance"})
            check("insurance without insurer -> 400", rp.status_code == 400,
                  str(rp.status_code))

    # ===== 7) تصدير CSV =====
    r = c.get("/patients/export.csv", headers=h)
    check("patients export 200 + BOM", r.status_code == 200
          and r.content[:3] == "\ufeff".encode("utf-8"))
    text = r.content.decode("utf-8-sig")
    check("patients export has created patient", "مريض الاختبار الحي" in text)
    r = c.get("/invoices/export.csv", headers=h, params={"status": "paid"})
    check("paid invoices export contains invoice", r.status_code == 200
          and inv_desc and inv_desc in r.content.decode("utf-8-sig"))

    # ===== 8) استيراد CSV (roundtrip + تكرار) =====
    email = "container_imp@hospital-demo.com"
    csv_body = (
        "الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد الإلكتروني,العنوان,مجموعة الدم\r\n"
        f"عميل استيراد الحاوية,1992-06-06,male,0563334444,{email},الدمام,A-\r\n"
    )
    files = {"file": ("p.csv", csv_body.encode("utf-8"), "text/csv")}
    r = c.post("/patients/import", headers=h, files=files)
    d = r.json() if r.status_code == 200 else {}
    check("import created=1", r.status_code == 200 and d.get("created") == 1,
          r.text[:200])
    r = c.post("/patients/import", headers=h, files=files)
    check("re-import skipped>=1", r.status_code == 200
          and r.json().get("skipped", 0) >= 1, r.text[:200])
    found = c.get("/patients/", headers=h, params={"search": "عميل استيراد الحاوية"}).json()
    check("imported patient exists", bool(found))
    if found:
        check("gender normalized to ذكر", found[0]["gender"] == "ذكر",
              found[0]["gender"])

    # ===== 9) تقارير PDF عربية داخل الحاوية =====
    r = c.get("/dashboard/report/pdf", headers=h)
    check("hospital report PDF", r.status_code == 200
          and r.content[:5] == b"%PDF-", str(r.status_code))
    r = c.get("/dashboard/report/pdf", headers=h, params={"month": "bad"})
    check("bad month -> 400", r.status_code == 400)
    r = c.get("/dashboard/report/pdf", headers=h, params={"lang": "en"})
    check("english report PDF lang=en", r.status_code == 200
          and r.content[:5] == b"%PDF-", str(r.status_code))
    if patient_id:
        r = c.get(f"/patients/{patient_id}/pdf", headers=h)
        check("patient PDF (Arabic)", r.status_code == 200
              and r.content[:5] == b"%PDF-", str(r.status_code))
    if inv_paid:
        r = c.get(f"/invoices/{inv_paid}/print", headers=h)
        check("invoice print HTML", r.status_code == 200
              and "html" in (r.headers.get("content-type") or ""),
              r.headers.get("content-type", ""))
        r = c.get(f"/invoices/{inv_paid}/pdf", headers=h)
        check("invoice PDF (Arabic)", r.status_code == 200
              and r.content[:5] == b"%PDF-", str(r.status_code))

    # ===== 10) إحصاءات + إشعارات + مرفقات =====
    r = c.get("/dashboard/stats", headers=h)
    if r.status_code == 200:
        s = r.json()
        check("stats patients>=1", s.get("total_patients", 0) >= 1)
        check("stats doctors>=1", s.get("total_doctors", 0) >= 1)
        check("revenue_paid >= 250.5", s.get("revenue_paid", 0) >= 250.5, str(s.get("revenue_paid")))
    else:
        check("dashboard stats 200", False, str(r.status_code))
    check("notifications list 200", c.get("/notifications/", headers=h).status_code == 200)
    check("unread-count 200", c.get("/notifications/unread-count", headers=h).status_code == 200)
    check("attachments list 200", c.get("/attachments/", headers=h).status_code == 200)

    # ===== 11) المحاور الجديدة: مختبر + صيدلية + طابور + رواتب + كلمة مرور + تدقيق =====
    check("UI has lab nav", 'data-view="lab"' in ui.text)
    check("UI has pharmacy nav", 'data-view="pharmacy"' in ui.text)
    check("UI has payroll nav", 'data-view="payroll"' in ui.text)
    check("UI has audit nav", 'data-view="audit"' in ui.text)
    check("UI has inventory nav + view",
          'data-view="inventory"' in ui.text
          and "async inventory(main)" in ui_all
          and "inventory: 'المخزون'" in ui_all)

    if patient_id and doctor_id:
        # مختبر: إنشاء → منع جاهزية بلا نتيجة → جاهزة + إشعار
        r = c.post("/lab-orders/", headers=h, json={
            "patient_id": patient_id, "doctor_id": doctor_id,
            "test_type": "lab", "test_name": "CBC حية", "price": 45})
        check("create lab order", r.status_code == 200, r.text[:150])
        lab_id = r.json().get("id") if r.status_code == 200 else None
        if lab_id:
            rr = c.put(f"/lab-orders/{lab_id}", headers=h, json={"status": "ready"})
            check("lab ready blocked without result -> 400", rr.status_code == 400,
                  str(rr.status_code))
            rr = c.put(f"/lab-orders/{lab_id}", headers=h,
                       json={"status": "ready", "result": "طبيعي"})
            check("lab ready with result", rr.status_code == 200
                  and rr.json().get("result_at"), rr.text[:150])
            rns = c.get("/notifications/", headers=h, params={"limit": 50}).json()
            check("lab_result notification created", any(
                n.get("type") == "lab_result" for n in rns))

        # صيدلية: دواء → صرف → انخفاض المخزون → كمية زائدة مرفوضة
        r = c.post("/medications/", headers=h, json={
            "code": "CNTMED1", "name": "باراسيتامول حي", "quantity": 12,
            "unit": "علبة", "price": 3, "min_quantity": 10})
        check("create medication", r.status_code == 200, r.text[:150])
        med_id = r.json().get("id") if r.status_code == 200 else None
        if med_id:
            rd = c.post("/dispenses/", headers=h, json={
                "medication_id": med_id, "patient_id": patient_id, "quantity": 4})
            check("dispense medication", rd.status_code == 200, rd.text[:150])
            rm = c.get(f"/medications/{med_id}", headers=h)
            check("stock decremented 12->8", rm.status_code == 200
                  and rm.json().get("quantity") == 8, rm.text[:150])
            rd = c.post("/dispenses/", headers=h, json={
                "medication_id": med_id, "patient_id": patient_id, "quantity": 99})
            check("over-dispense -> 400", rd.status_code == 400, str(rd.status_code))

            # ===== قسم المخزون: القيمة والحالة =====
            ri = c.get("/inventory/", headers=h, params={"search": "CNTMED1"})
            check("inventory list 200 + الحالة", ri.status_code == 200, ri.text[:150])
            row = next((x for x in ri.json() if x.get("id") == med_id), None) \
                if ri.status_code == 200 else None
            check("قيمة الصنف = كمية × سعر", row is not None
                  and row["value"] == 8 * 3, str(row and row.get("value")))
            check("حالة الصنف low (8 ≤ 10)", row is not None
                  and row["status"] == "low", str(row and row.get("status")))

            rs = c.get("/inventory/summary", headers=h)
            check("inventory summary 200 + مفاتيح", rs.status_code == 200
                  and all(k in rs.json() for k in (
                      "items", "units", "total_value", "low", "out",
                      "expired", "expiring", "expiring_days")), rs.text[:200])

            check("فلتر حالة خاطئ ⇒ 400",
                  c.get("/inventory/", headers=h,
                        params={"status": "bogus"}).status_code == 400)
            check("inventory بدون توكن ⇒ 401", c.get("/inventory/").status_code == 401)

            # توريد: 8 + 7 = 15 وحركة in
            rr = c.post(f"/inventory/{med_id}/restock", headers=h,
                        json={"quantity": 7, "note": "توريد حي"})
            check("restock 8->15", rr.status_code == 200
                  and rr.json().get("quantity") == 15, rr.text[:150])
            rmm = c.get(f"/medications/{med_id}", headers=h)
            check("المخزون بعد التوريد = 15",
                  rmm.json().get("quantity") == 15, rmm.text[:100])
            rmo = c.get("/inventory/movements", headers=h,
                        params={"medication_id": med_id, "type": "in"})
            check("حركة in مسجّلة (12 + 7)", rmo.status_code == 200
                  and any(m.get("change") == 7 and m.get("quantity_after") == 15
                          for m in rmo.json()), rmo.text[:200])

            # جرد مطلق: 15 ⇒ 10 => حركة adjust بفرق -5
            rr = c.put(f"/inventory/{med_id}/adjust", headers=h,
                       json={"quantity": 10, "note": "جرد حي"})
            check("adjust 15->10", rr.status_code == 200
                  and rr.json().get("quantity") == 10, rr.text[:150])
            rmo = c.get("/inventory/movements", headers=h,
                        params={"medication_id": med_id, "type": "adjust"})
            check("حركة adjust بفرق -5", rmo.status_code == 200
                  and any(m.get("change") == -5 and m.get("quantity_after") == 10
                          for m in rmo.json()), rmo.text[:200])

            check("restock كمية ≤ 0 ⇒ 422",
                  c.post(f"/inventory/{med_id}/restock", headers=h,
                         json={"quantity": 0}).status_code == 422)
            check("restock صنف غير موجود ⇒ 404",
                  c.post("/inventory/999999/restock", headers=h,
                         json={"quantity": 5}).status_code == 404)
            check("جرد سالب ⇒ 422",
                  c.put(f"/inventory/{med_id}/adjust", headers=h,
                        json={"quantity": -2}).status_code == 422)
            check("type حركات خاطئ ⇒ 400",
                  c.get("/inventory/movements", headers=h,
                        params={"type": "bogus"}).status_code == 400)
            check("restock بدون توكن ⇒ 401",
                  c.post(f"/inventory/{med_id}/restock",
                         json={"quantity": 5}).status_code == 401)

            # حركات الصرف الظاهرة في دفتر المخزون
            rmo = c.get("/inventory/movements", headers=h,
                        params={"medication_id": med_id, "type": "out"})
            check("حركة out من الصرف (-4)", rmo.status_code == 200
                  and any(m.get("change") == -4 and m.get("quantity_after") == 8
                          for m in rmo.json()), rmo.text[:200])

        # طابور: موعد مستقل → تسجيل وصول → رقم طابور → منع التكرار
        r = c.post("/appointments/", headers=h, json={
            "patient_id": patient_id, "doctor_id": doctor_id,
            "appointment_date": "2032-03-04T10:00:00", "reason": "طابور حي"})
        qaid = r.json().get("id") if r.status_code == 200 else None
        check("queue appointment created", r.status_code == 200, r.text[:150])
        if qaid:
            rc = c.post(f"/appointments/{qaid}/checkin", headers=h)
            check("check-in -> queue_number 1", rc.status_code == 200
                  and rc.json().get("queue_number") == 1, rc.text[:150])
            rc2 = c.post(f"/appointments/{qaid}/checkin", headers=h)
            check("double check-in -> 400", rc2.status_code == 400,
                  str(rc2.status_code))
            rq = c.get("/appointments/queue", headers=h,
                       params={"date": "2032-03-04"})
            check("queue list contains appointment", rq.status_code == 200
                  and any(a.get("id") == qaid for a in rq.json()), rq.text[:150])

    # فاتورة بخصم + ضريبة (مجاميع محسوبة)
    if patient_id:
        r = c.post("/invoices/", headers=h, json={
            "patient_id": patient_id, "amount": 100, "discount": 20,
            "tax_rate": 15, "description": "فاتورة ضريبية حية"})
        check("invoice discount+tax totals", r.status_code == 200
              and r.json().get("subtotal") == 80
              and r.json().get("tax") == 12
              and r.json().get("total") == 92, r.text[:200])

    # رواتب: موظف → قيد (صافي محسوب) → صرف
    r = c.post("/staff/", headers=h, json={
        "full_name": "موظف حي", "position": "فني", "phone": "0577777777",
        "email": "container_staff@hospital-demo.com",
        "hire_date": "2025-01-01", "salary": 4000})
    check("create staff for payroll", r.status_code == 200, r.text[:150])
    staff_id = r.json().get("id") if r.status_code == 200 else None
    if staff_id:
        rp = c.post("/payroll/", headers=h, json={
            "staff_id": staff_id, "period": "2032-01",
            "base_salary": 4000, "bonus": 200, "deduction": 100})
        check("payroll net = 4100", rp.status_code == 200
              and rp.json().get("net") == 4100, rp.text[:150])
        pay_id = rp.json().get("id") if rp.status_code == 200 else None
        if pay_id:
            rpay = c.post(f"/payroll/{pay_id}/pay", headers=h)
            check("payroll paid", rpay.status_code == 200
                  and rpay.json().get("status") == "paid", rpay.text[:150])

    # تغيير كلمة مرور ذاتي لمستخدم حي
    r = c.post("/auth/register", json={
        "username": "cnt_pw_user", "email": "cnt_pw@hospital-demo.com",
        "full_name": "مستخدم حي", "password": "oldpass123"})
    check("register password-test user", r.status_code in (200, 201), r.text[:150])
    if r.status_code in (200, 201):
        rl = c.post("/auth/login", json={"username": "cnt_pw_user",
                                         "password": "oldpass123"})
        if rl.status_code == 200:
            hp = {"Authorization": "Bearer " + rl.json()["access_token"]}
            rb = c.post("/auth/change-password", headers=hp, json={
                "current_password": "wrong", "new_password": "newpass456"})
            check("wrong current password -> 400", rb.status_code == 400,
                  str(rb.status_code))
            rb = c.post("/auth/change-password", headers=hp, json={
                "current_password": "oldpass123", "new_password": "newpass456"})
            check("change password -> 200", rb.status_code == 200, rb.text[:150])
            rl2 = c.post("/auth/login", json={"username": "cnt_pw_user",
                                              "password": "newpass456"})
            check("login with new password", rl2.status_code == 200,
                  str(rl2.status_code))

    # سجل التدقيق
    r = c.get("/audit-logs/", headers=h, params={"limit": 50})
    if r.status_code == 200:
        logs = r.json()
        check("audit has POST /patients", any(
            l.get("method") == "POST" and l.get("path", "").startswith("/patients")
            for l in logs), str(len(logs)))
        check("audit never logs GET", all(l.get("method") != "GET" for l in logs))
    else:
        check("audit-logs 200", False, str(r.status_code))

    # ===== 12) تقارير PDF المتخصصة: مختبر + صيدلية + رواتب =====
    r = c.get("/reports/lab/pdf", headers=h)
    check("lab report PDF", r.status_code == 200 and r.content[:4] == b"%PDF",
          str(r.status_code))
    r = c.get("/reports/pharmacy/pdf", headers=h)
    check("pharmacy report PDF", r.status_code == 200 and r.content[:4] == b"%PDF",
          str(r.status_code))
    r = c.get("/reports/payroll/pdf", headers=h, params={"period": "2032-01"})
    check("payroll report PDF (period)", r.status_code == 200
          and r.content[:4] == b"%PDF", str(r.status_code))
    r = c.get("/reports/payroll/pdf", headers=h, params={"period": "bad"})
    check("payroll report bad period -> 400", r.status_code == 400,
          str(r.status_code))

    # ===== 13) حالة النظام العامة (JSON عام دون توكن) =====
    r = c.get("/status")
    sd = r.json() if r.status_code == 200 else {}
    check("/status public + db connected + counts",
          r.status_code == 200 and sd.get("database", {}).get("connected") is True
          and sd.get("counts", {}).get("patients", 0) >= 1, str(r.status_code))

    # ===== 14) لوحة المراقبة + تقارير CSV المتخصصة + تحليل الاستخدام =====
    r = c.get("/monitor")
    check("monitor page /monitor", r.status_code == 200
          and "لوحة مراقبة" in r.text, str(r.status_code))
    for p in ("/reports/lab/csv", "/reports/pharmacy/csv", "/reports/payroll/csv"):
        r = c.get(p, headers=h)
        check(f"{p} CSV + BOM", r.status_code == 200
              and r.content[:3] == b"\xef\xbb\xbf", str(r.status_code))
    r = c.get("/audit-logs/stats", headers=h)
    check("/audit-logs/stats analysis", r.status_code == 200
          and "top_paths" in r.json()
          and "login_failures" in r.json(), str(r.status_code))

    # ===== 14b) إدارة المستخدمين: قائمة + تغيير دور + تفعيل/تعطيل =====
    # اسم فريد لكل تشغيل حتى لا يتعارض مع تشغيل سابق على نفس القاعدة
    import time as _time
    _uname = f"livemgr{int(_time.time()) % 1000000}"
    users = c.get("/auth/users", headers=h)
    ulist = users.json() if users.status_code == 200 else []
    r = c.post("/auth/register", json={
        "username": _uname, "email": f"{_uname}@t.com",
        "full_name": "Live Role Test", "password": "RolePass123",
        "role": "موظف استقبال"})
    uid = r.json().get("id") if r.status_code == 200 else None
    r2 = (c.put(f"/auth/users/{uid}/role", headers=h, json={"role": "doctor"})
          if uid else r)
    r3 = (c.put(f"/auth/users/{uid}/toggle", headers=h) if uid else r)
    check("users list + role change + toggle",
          users.status_code == 200
          and any(u["username"] == "admin" for u in ulist)
          and r.status_code == 200 and r2.status_code == 200
          and r2.json().get("role") == "doctor"
          and r3.status_code == 200
          and r3.json().get("is_active") is False,
          f"{users.status_code}/{r.status_code}/{r2.status_code}/{r3.status_code}")

    # ===== 14c) النسخ الاحتياطي: SQLite = إنشاء + استعادة كاملة؛
    #             PostgreSQL = إنشاء/استعادة مرفوضان برسالة 400 موجّهة =====
    rb = c.post("/backup", headers=h)
    if rb.status_code == 200:
        fname = rb.json().get("file", "")
        pm = c.post("/patients/", headers=h, json={
            "full_name": "Restore Marker", "date_of_birth": "1990-01-01",
            "gender": "ذكر", "phone": "0555202020",
            "email": "restore_marker@t.com"})
        marker = pm.json().get("id") if pm.status_code == 200 else None
        rs = (c.post(f"/backup/{fname}/restore", headers=h) if fname else rb)
        gone = (c.get(f"/patients/{marker}", headers=h).status_code == 404
                if marker else False)
        # القائمة بعد الاستعادة حتى تتضمّن نسخة الأمان المصنوعة أثناءها
        lst = c.get("/backup", headers=h)
        lst_json = lst.json() if lst.status_code == 200 else []
        ok = (rs.status_code == 200
              and rs.json().get("safety_copy", "").startswith("auto_")
              and rs.json().get("safety_copy") in {f["file"] for f in lst_json}
              and gone
              and all("restorable" in f for f in lst_json))
        detail = f"sqlite {rb.status_code}/{rs.status_code}/{lst.status_code}"
    else:
        rs = c.post("/backup/whatever.db/restore", headers=h)
        lst = c.get("/backup", headers=h)
        ok = (rb.status_code == 400 and rs.status_code == 400
              and "SQLite" in rb.json().get("detail", "")
              and lst.status_code in (200, 400))
        detail = f"pg {rb.status_code}/{rs.status_code}/{lst.status_code}"
    check("backup create/restore (SQLite) أو رفض موجّه 400 (PG)", ok, detail)

    # ===== 14d) الحسابات والمبيعات =====
    rr = c.get("/accounts/summary", headers=h)
    check("/accounts/summary", rr.status_code == 200
          and all(k in rr.json() for k in ("period", "total_sales", "total_paid", "count")), str(rr.status_code))
    rr = c.get("/accounts/sales", headers=h)
    check("/accounts/sales", rr.status_code == 200 and isinstance(rr.json(), list), str(rr.status_code))
    rr = c.put("/accounts/sales/999999/payment",
               json={"paid_amount": 1, "payment_method": "cash"})
    check("/accounts/sales/999999/payment بدون توكن", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/reports/accounts/sales/csv")
    check("/reports/accounts/sales/csv بدون توكن", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/reports/accounts/sales/pdf")
    check("/reports/accounts/sales/pdf بدون توكن", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/accounts/sales/1/receipt")
    check("إيصال البيع بدون توكن ⇒ 401", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/accounts/statement/1")
    check("كشف الحساب بدون توكن ⇒ 401", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/accounts/statement/999999", headers=h)
    check("كشف حساب مريض غير موجود ⇒ 404", rr.status_code == 404, str(rr.status_code))
    rr = c.get("/accounts/statement/1/pdf", headers=h)
    check("PDF كشف الحساب ⇒ %PDF",
          rr.status_code == 200 and rr.content[:4] == b"%PDF", str(rr.status_code))
    rr = c.get("/accounts/statement/1/pdf", headers=h, params={"lang": "en"})
    check("PDF كشف الحساب إنجليزي ⇒ %PDF",
          rr.status_code == 200 and rr.content[:4] == b"%PDF", str(rr.status_code))
    rr = c.get("/accounts/statement/1/pdf", headers=h, params={"lang": "zz"})
    check("PDF كشف الحساب لغة خاطئة ⇒ 400", rr.status_code == 400, str(rr.status_code))
    rr = c.get("/accounts/statement/1/pdf")
    check("PDF كشف الحساب بدون توكن ⇒ 401", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/ui/")
    # بعد التجزئة: JS في /ui/app.js — يُفحص مع HTML
    rr_all = rr.content + c.get("/ui/app.js").content
    check("واجهة المبيعات والحسابات في /ui",
          b"async sales(main)" in rr_all
          and b"async accounts(main)" in rr_all
          and 'data-view="sales"'.encode() in rr_all
          and 'data-view="accounts"'.encode() in rr_all)
    check("إيصال + كشف حساب في الواجهة",
          b"function openReceipt(" in rr_all
          and b"async function showStatement(" in rr_all)
    check("نافذة التسديد في /ui", b'id="modal-back"' in rr_all
          and b"function submitPay(" in rr_all and b"function payAll(" in rr_all)
    check("منع كاش الواجهة (no-cache)",
          "no-cache" in (rr.headers.get("cache-control") or ""),
          str(rr.headers.get("cache-control")))
    check("واجهة المخزون في /ui",
          b"async inventory(main)" in rr_all
          and b"/inventory/summary" in rr_all
          and b"function adjustStock(" in rr_all)
    rr = c.get("/ui/sw.js")
    check("عامل الخدمة network-first + إصدار الكاش v5",
          b"hms-shell-v6" in rr.content
          and "الشبكة أولًا".encode() in rr.content)
    rr = c.get("/")
    check("صفحة الجذر CSS سليم (بدون {{)", b"body { font-family" in rr.content
          and b"body {{" not in rr.content)

    # ===== 15) PWA + واجهة إنجليزية =====
    r = c.get("/ui/")
    # بعد التجزئة: toggleLang/register/renderCalendar صارت في /ui/app.js
    r_all = r.text + c.get("/ui/app.js").text
    check("UI i18n toggle + PWA markers", r.status_code == 200
          and all(s in r_all for s in ("toggleLang", "manifest.json",
                                        "serviceWorker.register",
                                        "renderCalendar",
                                        'data-view="users"')),
          str(r.status_code))
    r = c.get("/ui/manifest.json")
    check("PWA manifest start_url=/ui/", r.status_code == 200
          and r.json().get("start_url") == "/ui/", str(r.status_code))

    print(f"\n==== LIVE CONTAINER RESULT: {PASSED} passed, {FAILED} failed ====")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
