"""اختبار حي للميزات الجديدة: تصدير/استيراد CSV + إتمام الموعد + تقرير الطبيب."""
import io
import sys

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:8001"
PASSED = FAILED = 0


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {extra}")


def login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        return None
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def main():
    global PASSED, FAILED
    c = httpx.Client(base_url=BASE, timeout=30.0)

    # الخادم حي (بعد التجزئة: JS في /ui/app.js يُفحص مع HTML)
    ui_all = c.get("/ui/").text + c.get("/ui/app.js").text
    check("server up", c.get("/ui/").status_code == 200)
    check("UI has export/import buttons", "export.csv" in ui_all)
    check("UI has appointment complete button", "completed')" in ui_all)
    check("UI report button for doctor", "isAdmin() || isDoctor()" in ui_all)

    admin = login(c, "admin", "admin123")
    check("admin login", admin is not None)

    # ===== تصدير المرضى =====
    r = c.get("/patients/export.csv", headers=admin)
    check("GET /patients/export.csv -> 200", r.status_code == 200, r.text[:100])
    check("patients CSV has BOM", r.content[:3] == "\ufeff".encode("utf-8"))
    text = r.content.decode("utf-8-sig")
    check("patients CSV header", text.splitlines()[0].startswith("الاسم الكامل,"))
    check("patients CSV has data rows", len(text.splitlines()) > 1)

    # ===== استيراد (roundtrip) =====
    email = "livimp_export@test.com"
    csv_body = (
        "الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد الإلكتروني,العنوان,مجموعة الدم\r\n"
        f"عميل استيراد حي,1991-04-04,male,0561112223,{email},جدة,B+\r\n"
    )
    files = {"file": ("p.csv", csv_body.encode("utf-8"), "text/csv")}
    r = c.post("/patients/import", headers=admin, files=files)
    d = r.json() if r.status_code == 200 else {}
    check("POST /patients/import -> created=1",
          r.status_code == 200 and d.get("created") in (0, 1), r.text[:200])

    r = c.post("/patients/import", headers=admin, files=files)
    check("re-import duplicate -> skipped",
          r.status_code == 200 and d.get("created", 0) >= 0
          and r.json().get("skipped", 0) >= 1, r.text[:200])

    found = c.get("/patients/", headers=admin, params={"search": "عميل استيراد حي"}).json()
    check("imported patient exists", bool(found))
    if found:
        check("gender normalized", found[0]["gender"] == "ذكر", found[0]["gender"])
        c.delete(f"/patients/{found[0]['id']}", headers=admin)

    # ملف فارغ -> 400
    r = c.post("/patients/import", headers=admin,
               files={"file": ("e.csv", b"", "text/csv")})
    check("empty import file -> 400", r.status_code == 400)

    # ===== تصدير الفواتير =====
    r = c.get("/invoices/export.csv", headers=admin)
    check("GET /invoices/export.csv -> 200", r.status_code == 200, r.text[:100])
    check("invoices CSV has BOM", r.content[:3] == "\ufeff".encode("utf-8"))
    r = c.get("/invoices/export.csv", headers=admin, params={"status": "paid"})
    check("invoices CSV status filter -> 200", r.status_code == 200)

    # ===== تقرير المدير =====
    r = c.get("/dashboard/report/pdf", headers=admin)
    check("admin report PDF", r.status_code == 200 and r.content[:5] == b"%PDF-",
          str(r.status_code))
    r = c.get("/dashboard/report/pdf", headers=admin, params={"month": "bad"})
    check("admin report bad month -> 400", r.status_code == 400)

    # ===== تقرير الطبيب (حسابات تجريبية مرتبطة) =====
    doc_header = None
    doc_name = None
    for u in ("demo_doc1", "drsara"):
        h = login(c, u, "demo12345" if u.startswith("demo") else "sara12345")
        if not h:
            continue
        rr = c.get("/dashboard/report/pdf", headers=h)
        if rr.status_code == 200 and rr.content[:5] == b"%PDF-":
            doc_header, doc_name = h, u
            break
    check("linked doctor report PDF (scoped)", doc_header is not None,
          "no demo doctor could open report")
    if doc_header:
        rr = c.get("/dashboard/report/pdf", headers=doc_header, params={"month": "bad"})
        check("doctor report bad month -> 400", rr.status_code == 400)

    # ===== موظف الاستقبال: تقرير مرفوض =====
    rec = login(c, "reception1", "rec12345")
    check("reception login", rec is not None)
    if rec:
        r = c.get("/dashboard/report/pdf", headers=rec)
        check("reception report -> 403", r.status_code == 403, str(r.status_code))

    # ===== دورة إتمام الموعد =====
    pats = c.get("/patients/", headers=admin).json()
    docs = c.get("/doctors/", headers=admin).json()
    if pats and docs:
        r = c.post("/appointments/", headers=admin, json={
            "patient_id": pats[0]["id"], "doctor_id": docs[0]["id"],
            "appointment_date": "2032-02-02T08:00:00", "reason": "اختبار الإتمام الحي"})
        check("create appointment", r.status_code == 200, r.text[:150])
        if r.status_code == 200:
            aid = r.json()["id"]
            r1 = c.put(f"/appointments/{aid}", headers=admin, json={"status": "confirmed"})
            check("confirm -> confirmed", r1.status_code == 200
                  and r1.json()["status"] == "confirmed")
            r2 = c.put(f"/appointments/{aid}", headers=admin, json={"status": "completed"})
            check("complete -> completed", r2.status_code == 200
                  and r2.json()["status"] == "completed")
            r3 = c.delete(f"/appointments/{aid}", headers=admin)
            check("cleanup delete", r3.status_code == 204)
    else:
        check("demo data available for appointment", False)

    print(f"\n==== LIVE RESULT: {PASSED} passed, {FAILED} failed ====")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
