"""فحص موحّد لأي نشرة (stack) — SQLite/PostgreSQL، محلي/حاوية/إنتاج.

يُستخدم بعد التجربة النظيفة (seed_demo.py) وبعد أي نشر جديد، وينطبق على قاعدة
فارغة أو مزروعة (يكشف التلقائيًا ويتخطّى فرضيات البذر إن كانت فارغة).
سكربت قراءة فقط (دخول + قراءات) — لا يُنشئ ولا يعدّل أي بيانات، فيصلح
لاختبار قاعدة إنتاج دون تلوّثها. يلزم حساب **مدير** لجميع الفحوصات.

التشغيل:
    python tests/stack_check.py                                    # localhost:8001
    BASE_URL=http://127.0.0.1:8000 python tests/stack_check.py     # docker compose
    WAIT=90 python tests/stack_check.py                             # انتظار الجاهزية (ثانية)
    STACK_USER=admin STACK_PASS=... python tests/stack_check.py     # اعتماد مخصّص (مدير)

ملاحظة: أسماء STACK_USER/STACK_PASS مقصودة — متغيّر USERNAME محجوز في Windows/PowerShell.

الناتج: ملخص PASS/FAIL لكل محور + كود خروج 0 عند نجاح الكل.
"""
import os
import sys
import time

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8001").rstrip("/")
STACK_USER = os.environ.get("STACK_USER", "admin")
STACK_PASS = os.environ.get("STACK_PASS", "admin123")
WAIT = int(os.environ.get("WAIT", "0"))
PASSED = FAILED = 0


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {extra}")


def wait_ready(c) -> bool:
    if WAIT <= 0:
        return True
    print(f"— انتظار جاهزية الخادم حتى {WAIT} ثانية …")
    deadline = time.time() + WAIT
    while time.time() < deadline:
        try:
            if c.get("/health", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    c = httpx.Client(base_url=BASE, timeout=30)
    print(f"الفحص الموحد على: {BASE}")

    ready = wait_ready(c)
    check("الخادم جاهز (/health 200)", ready and c.get("/health").status_code == 200)
    if not ready:
        print(f"\n==== STACK RESULT: {PASSED} passed, {FAILED} failed ====")
        sys.exit(1)

    # 0) حالة النظام العامة (دون توكن)
    st = c.get("/status")
    sd = st.json() if st.status_code == 200 else {}
    check("/status عام دون توكن + قاعدة متصلة",
          st.status_code == 200 and sd.get("database", {}).get("connected") is True,
          str(st.status_code))
    check("/status يحمل الإصدار والعدادات والتنبيهات",
          bool(sd.get("version")) and isinstance(sd.get("counts"), dict)
          and isinstance(sd.get("alerts"), dict)
          and isinstance(sd.get("reminders"), dict)
          and isinstance(sd.get("backups"), dict))

    # 0b) لوحة المراقبة المرئية (دون توكن)
    mon = c.get("/monitor")
    check("لوحة المراقبة /monitor (200 + HTML عربية)",
          mon.status_code == 200 and "لوحة مراقبة" in mon.text,
          str(mon.status_code))

    # 1) الأمان والواجهة
    check("المسارات محمية بدون توكن (401)", c.get("/patients/").status_code == 401)
    ui = c.get("/ui/")
    check("الواجهة تُقدَّم (200 + تسجيل الدخول)",
          ui.status_code == 200 and "تسجيل الدخول" in ui.text)
    check("الواجهة فيها مسارات المفاقيد الأربع",
          all(f'data-view="{v}"' in ui.text
              for v in ("lab", "pharmacy", "payroll", "audit")))
    check("القائمة تفصل المبيعات عن الحسابات",
          'data-view="sales"' in ui.text and 'data-view="accounts"' in ui.text
          and "async sales(main)" in ui.text
          and "async accounts(main)" in ui.text)
    check("قسم المخزون في القائمة والعرض",
          'data-view="inventory"' in ui.text
          and "async inventory(main)" in ui.text
          and "inventory: 'المخزون'" in ui.text
          and "/inventory/summary" in ui.text
          and "function adjustStock(" in ui.text)
    check("الواجهة فيها زر تغيير كلمة المرور", "changePassword" in ui.text)
    check("أزرار التقارير PDF وCSV في الواجهة",
          all(s in ui.text for s in ("/reports/lab/pdf", "/reports/pharmacy/pdf",
                                     "downloadPayroll('pdf')",
                                     "/reports/lab/csv", "/reports/pharmacy/csv",
                                     "downloadPayroll('csv')")))
    check("واجهة إنجليزية: زر التبديل toggleLang", "toggleLang" in ui.text)
    check("واجهة التقويم الشهري (renderCalendar + calNav)",
          "renderCalendar" in ui.text and "calNav" in ui.text)
    check("واجهة إدارة المستخدمين والاستعادة",
          'data-view="users"' in ui.text and "setRole" in ui.text
          and "restoreBackup" in ui.text)
    check("PWA: manifest + service worker في الصفحة",
          "manifest.json" in ui.text and "sw.js" in ui.text)
    check("الوثائق /api/docs (200)", c.get("/api/docs").status_code == 200)

    # 2) الدخول (مدير)
    r = c.post("/auth/login", json={"username": STACK_USER, "password": STACK_PASS})
    check(f"دخول {STACK_USER}", r.status_code == 200, r.text[:120])
    if r.status_code != 200:
        print(f"\n==== STACK RESULT: {PASSED} passed, {FAILED} failed ====")
        sys.exit(1)
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    ru = c.get("/auth/users", headers=h)
    check("GET /auth/users 200 + حقول الصلاحيات",
          ru.status_code == 200 and isinstance(ru.json(), list) and ru.json()
          and all(k in ru.json()[0] for k in ("username", "role", "is_active")),
          str(ru.status_code))

    # 3) الإحصاءات — تكيّف: بذر أو قاعدة نظيفة
    s = c.get("/dashboard/stats", headers=h).json()
    seeded = s.get("total_patients", 0) > 0
    print(f"  ℹ️ وضع القاعدة: {'مزروعة (seed)' if seeded else 'نظيفة/فارغة'}")
    check("إحصاءات dashboard متماسكة (حقول + محصّل ≤ إجمالي)",
          all(k in s for k in ("total_patients", "total_doctors", "total_appointments",
                               "revenue_total", "revenue_paid"))
          and s["revenue_paid"] <= s["revenue_total"] + 0.01)
    if seeded:
        check(f"بذر: مرضى > 0 (={s['total_patients']})", s["total_patients"] > 0)
        check(f"بذر: أطباء > 0 (={s['total_doctors']})", s["total_doctors"] > 0)
        check(f"بذر: مواعيد > 0 (={s['total_appointments']})", s["total_appointments"] > 0)
        check(f"بذر: أقسام > 0 (={s.get('total_departments', 0)})",
              s.get("total_departments", 0) > 0)
    else:
        check("قاعدة نظيفة: كل العدّادات ≥ 0",
              s["total_patients"] >= 0 and s["total_doctors"] >= 0)

    # 4) كل المحاور ترد 200
    modules = ("/patients/", "/doctors/", "/appointments/", "/appointments/queue",
               "/invoices/", "/medical-records/", "/beds/", "/departments/",
               "/staff/", "/attachments/", "/notifications/",
               "/lab-orders/", "/medications/", "/dispenses/",
               "/payroll/", "/audit-logs/?limit=5", "/reports/",
               "/inventory/", "/inventory/summary", "/inventory/movements")
    for p in modules:
        rr = c.get(p, headers=h)
        check(f"GET {p} -> 200", rr.status_code == 200, str(rr.status_code))

    # 5) التقارير PDF العربية (إحصائي + متخصصة) + تحقق الفترة
    for p in ("/dashboard/report/pdf", "/reports/lab/pdf",
              "/reports/pharmacy/pdf", "/reports/payroll/pdf"):
        rr = c.get(p, headers=h)
        check(f"{p} -> %PDF",
              rr.status_code == 200 and rr.content[:4] == b"%PDF", str(rr.status_code))
    rr = c.get("/reports/payroll/pdf?period=bad", headers=h)
    check("فترة رواتب خاطئة -> 400", rr.status_code == 400, str(rr.status_code))

    # 5c) التقارير الإنجليزية (lang=en) — محور واحد: الأربعة معًا
    en_rs = [c.get(p, headers=h)
             for p in ("/dashboard/report/pdf?lang=en",
                       "/reports/lab/pdf?lang=en",
                       "/reports/pharmacy/pdf?lang=en",
                       "/reports/payroll/pdf?lang=en")]
    check("تقارير PDF إنجليزية lang=en (4 × %PDF)",
          all(x.status_code == 200 and x.content[:4] == b"%PDF" for x in en_rs),
          str([x.status_code for x in en_rs]))
    rr = c.get("/reports/lab/pdf?lang=fr", headers=h)
    check("لغة تقرير مجهولة -> 400", rr.status_code == 400, str(rr.status_code))

    # 5b) التقارير CSV المتخصصة (BOM يفتح عربيًا في Excel)
    for p in ("/reports/lab/csv", "/reports/pharmacy/csv", "/reports/payroll/csv"):
        rr = c.get(p, headers=h)
        check(f"{p} -> CSV + BOM",
              rr.status_code == 200 and rr.content[:3] == b"\xef\xbb\xbf",
              str(rr.status_code))
    rr = c.get("/reports/payroll/csv?period=bad", headers=h)
    check("فترة رواتب CSV خاطئة -> 400", rr.status_code == 400, str(rr.status_code))

    # 6) تصدير CSV بالعناوين العربية
    rr = c.get("/patients/export.csv", headers=h)
    check("تصدير المرضى + عمود الهوية",
          rr.status_code == 200
          and "الهوية الوطنية" in rr.content.decode("utf-8-sig", "ignore"),
          str(rr.status_code))
    rr = c.get("/invoices/export.csv", headers=h)
    check("تصدير الفواتير + عمود الإجمالي",
          rr.status_code == 200
          and "الإجمالي" in rr.content.decode("utf-8-sig", "ignore"),
          str(rr.status_code))

    # 7) سلوك التدقيق: لا يسجّل عمليات GET مطلقًا + تحليل الاستخدام
    rr = c.get("/audit-logs/?limit=100", headers=h)
    methods = {l.get("method") for l in (rr.json() if rr.status_code == 200 else [])}
    check("التدقيق: لا عمليات GET مسجّلة",
          rr.status_code == 200 and methods <= {"POST", "PUT", "PATCH", "DELETE"})
    rr = c.get("/audit-logs/stats", headers=h)
    st = rr.json() if rr.status_code == 200 else {}
    check("/audit-logs/stats (تحليل استخدام النظام)",
          rr.status_code == 200 and all(
              k in st for k in ("total", "by_method", "top_users",
                                "top_paths", "recent_errors",
                                "login_failures")),
          str(rr.status_code))

    # 8) النسخ الاحتياطي: 200 على SQLite — أو 400 موجّه على PostgreSQL
    rr = c.get("/backup", headers=h)
    check("النسخ الاحتياطي (200 SQLite أو 400 موجّه PostgreSQL)",
          rr.status_code in (200, 400)
          and (rr.status_code == 400
               or all("restorable" in f for f in rr.json())),
          str(rr.status_code))

    # 8.5) الحسابات والمبيعات: endpoints تعمل و401 بدون توكن
    rr = c.get("/accounts/summary", headers=h)
    check("/accounts/summary", rr.status_code == 200
          and all(k in rr.json() for k in ("period", "total_sales", "total_paid", "count")),
          str(rr.status_code))
    rr = c.get("/accounts/sales", headers=h)
    check("/accounts/sales", rr.status_code == 200 and isinstance(rr.json(), list), str(rr.status_code))
    rr = c.get("/accounts/sales/999999", headers=h)
    check("/accounts/sales/999999", rr.status_code == 404, str(rr.status_code))
    rr = c.put("/accounts/sales/999999/payment", headers=h,
                json={"paid_amount": 1, "payment_method": "cash"})
    check("/accounts/sales/999999/payment", rr.status_code == 404, str(rr.status_code))
    rr = c.get("/reports/accounts/sales/csv")
    check("/reports/accounts/sales/csv", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/reports/accounts/sales/pdf")
    check("/reports/accounts/sales/pdf", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/accounts/sales/999999/receipt", headers=h)
    check("/accounts/sales/999999/receipt", rr.status_code == 404, str(rr.status_code))
    rr = c.get("/accounts/sales/1/receipt")
    check("/accounts/sales/1/receipt بدون توكن", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/accounts/statement/999999", headers=h)
    check("/accounts/statement/999999", rr.status_code == 404, str(rr.status_code))
    rr = c.get("/accounts/statement/1")
    check("/accounts/statement/1 بدون توكن", rr.status_code == 401, str(rr.status_code))
    rr = c.get("/accounts/statement/999999/print", headers=h,
               params={"lang": "zz"})
    check("/accounts/statement/999999/print لغة خاطئة", rr.status_code == 400,
          str(rr.status_code))

    # 8.6) المخزون: الملخّص والحركات وفحوص المدخلات (لا تُغيّر أي بيانات)
    rr = c.get("/inventory/summary", headers=h)
    check("/inventory/summary", rr.status_code == 200
          and all(k in rr.json() for k in ("items", "units", "total_value",
                                           "low", "out", "expired", "expiring")),
          str(rr.status_code))
    rr = c.get("/inventory/", headers=h)
    check("/inventory/ قائمة 200 + حقول محسوبة",
          rr.status_code == 200 and isinstance(rr.json(), list)
          and all(("value" in x and "status" in x) for x in rr.json()[:5]),
          str(rr.status_code))
    rr = c.get("/inventory/movements", headers=h, params={"limit": 5})
    check("/inventory/movements", rr.status_code == 200
          and isinstance(rr.json(), list), str(rr.status_code))
    rr = c.get("/inventory/", headers=h, params={"status": "bogus"})
    check("فلتر حالة خاطئ ⇒ 400", rr.status_code == 400, str(rr.status_code))
    rr = c.get("/inventory/", headers=h, params={"expiring_days": -1})
    check("expiring_days سالب ⇒ 400", rr.status_code == 400, str(rr.status_code))
    rr = c.get("/inventory/movements", headers=h, params={"type": "bogus"})
    check("نوع حركة خاطئ ⇒ 400", rr.status_code == 400, str(rr.status_code))
    rr = c.get("/inventory/")
    check("/inventory بدون توكن ⇒ 401", rr.status_code == 401, str(rr.status_code))
    rr = c.post("/inventory/999999/restock", headers=h, json={"quantity": 5})
    check("restock صنف غير موجود ⇒ 404", rr.status_code == 404, str(rr.status_code))
    rr = c.post("/inventory/999999/restock", json={"quantity": 5})
    check("restock بدون توكن ⇒ 401", rr.status_code == 401, str(rr.status_code))
    rr = c.put("/inventory/999999/adjust", headers=h, json={"quantity": 5})
    check("جرد صنف غير موجود ⇒ 404", rr.status_code == 404, str(rr.status_code))
    rr = c.put("/inventory/999999/adjust", json={"quantity": 5})
    check("جرد بدون توكن ⇒ 401", rr.status_code == 401, str(rr.status_code))

    # 9) حماية الدخول: قفل مؤقت (في الذاكرة — مستخدم وهمي لا يمسّ البيانات)
    lk = {"username": "stack_lock_dummy", "password": "badpass1"}
    lk_codes = [c.post("/auth/login", json=lk).status_code for _ in range(5)]
    rr = c.post("/auth/login", json=lk)
    check("قفل الدخول بعد 5 محاولات فاشلة (401×5 ثم 429)",
          lk_codes == [401, 401, 401, 401, 401] and rr.status_code == 429,
          f"{lk_codes} → {rr.status_code}")

    print(f"\n==== STACK RESULT: {PASSED} passed, {FAILED} failed ====")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
