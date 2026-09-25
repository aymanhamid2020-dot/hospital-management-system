# فحص حي لقسم الحسابات في الواجهة (يقرأ static/index.html ويتحقق من الخادم الشغّال)
import httpx

HTML = open("static/index.html", "rb").read()
# بعد تجزئة الواجهة: مؤشرات JS/CSS صارت في app.js/app.css — تُفحص مع HTML
HTML_ALL = (HTML + open("static/app.js", "rb").read()
            + open("static/app.css", "rb").read())
NEEDLES = [
    # تقسيم القائمة: مبيعات + حسابات منفصلتان
    'data-view="sales"',
    'data-view="accounts"',
    "🛒 المبيعات",
    "🧾 الحسابات",
    "async sales(main)",
    "async accounts(main)",
    "sales: 'المبيعات'",
    "accounts: 'الحسابات'",
    "/accounts/summary",
    "/accounts/sales",
    "/accounts/sales/' + id + '/payment'",
    "/reports/accounts/sales/",
    # إيصال الدفعة + كشف حساب المريض
    "/accounts/sales/' + id + '/receipt",
    "/accounts/statement/",
    "/print?lang=",
    "function openReceipt(",
    "function openPrint(",
    "async function showStatement(",
    "'طباعة الكشف': 'Print statement'",
    "function periodRange",
    "function loadAccounts",
    "function pay(",
    "function openModal(",
    "function payPreview(",
    "async function submitPay(",
    "async function payAll(",
    "ACC_ROWS = sales",
    "pay-after",
    "id=\"modal-back\"",
    "'سدّد الكل': 'Settle all'",
    "'لا يمكن أن يتجاوز المبلغ المتبقي'",
    "function setAccGroup",
    "/accounts/revenue",
    "/accounts/debtors",
    "منحنى الإيراد",
    "المدينون",
    "accGroup",
    "'غير مدفوع': 'Unpaid'",
    "'لا توجد مبيعات في هذه الفترة'",
]
print("== static/index.html ==")
bad = 0
for n in NEEDLES:
    ok = n.encode("utf-8") in HTML_ALL
    bad += 0 if ok else 1
    print(("  [PASS] " if ok else "  [FAIL] ") + n)

print("== live server ==")
c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
tok = c.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()
H = {"Authorization": "Bearer " + tok["access_token"]}
idx = c.get("/")
# بعد تجزئة الواجهة: JS صار في /app.js — مؤشرات الدوال تفحص الملفين
idx_js = c.get("/app.js").content
checks = [
    ("GET / يخدم الواجهة", idx.status_code == 200),
    ("الواجهة تحتوي عرض المبيعات",
     "async sales(main)".encode() in idx_js),
    ("الواجهة تحتوي قسم الحسابات",
     "async accounts(main)".encode() in idx_js),
    ("قائمة منفصلة: مبيعات + حسابات",
     'data-view="sales"'.encode() in idx.content
     and 'data-view="accounts"'.encode() in idx.content),
    ("وظيفة إيصال + كشف حساب",
     b"function openReceipt(" in idx_js
     and b"async function showStatement(" in idx_js),
    ("ملف CSS/JS محدّث", len(idx.content) == len(HTML)),
    ("/accounts/summary 200", c.get("/accounts/summary", headers=H).status_code == 200),
    ("/accounts/sales 200", c.get("/accounts/sales", headers=H).status_code == 200),
    ("فلتر status=PAID 200",
     c.get("/accounts/sales", headers=H, params={"status": "PAID"}).status_code == 200),
    ("فلتر payment_method 200",
     c.get("/accounts/sales", headers=H, params={"payment_method": "cash"}).status_code == 200),
    ("فلتر تواريخ 200",
     c.get("/accounts/sales", headers=H,
           params={"from_date": "2026-09-01", "to_date": "2026-09-30"}).status_code == 200),
    ("CSV+BOM", c.get("/reports/accounts/sales/csv", headers=H).content[:3] == b"\xef\xbb\xbf"),
    ("PDF %PDF", c.get("/reports/accounts/sales/pdf", headers=H).content[:4] == b"%PDF"),
    ("PDF en %PDF", c.get("/reports/accounts/sales/pdf", headers=H,
                          params={"lang": "en"}).content[:4] == b"%PDF"),
    ("غير مسجّل ⇒ 401", c.get("/accounts/summary").status_code == 401),
    ("غير مسجّل إيصال ⇒ 401",
     c.get("/accounts/sales/1/receipt").status_code == 401),
    ("غير مسجّل كشف حساب ⇒ 401",
     c.get("/accounts/statement/1").status_code == 401),
    ("كشف حساب مريض موجود ⇒ 200",
     (lambda r: r.status_code == 200
      and r.json()["totals"]["sales_total"] >= 0)(
         c.get("/accounts/statement/1", headers=H))),
    ("طباعة كشف الحساب ⇒ HTML",
     (lambda r: r.status_code == 200
      and r.text.startswith("<!DOCTYPE html>"))(
         c.get("/accounts/statement/1/print", headers=H))),
    ("لغة خاطئة في الكشف ⇒ 400",
     c.get("/accounts/statement/1/print", headers=H,
           params={"lang": "xx"}).status_code == 400),
    ("PDF كشف الحساب ⇒ %PDF",
     c.get("/accounts/statement/1/pdf", headers=H).content[:4] == b"%PDF"),
    ("PDF كشف الحساب إنجليزي ⇒ %PDF",
     c.get("/accounts/statement/1/pdf", headers=H,
           params={"lang": "en"}).content[:4] == b"%PDF"),
    ("لغة خاطئة في PDF الكشف ⇒ 400",
     c.get("/accounts/statement/1/pdf", headers=H,
           params={"lang": "xx"}).status_code == 400),
    ("PDF الكشف غير مسجّل ⇒ 401",
     c.get("/accounts/statement/1/pdf").status_code == 401),
    ("زر PDF الكشف في الواجهة",
     "'⬇️ PDF الكشف'" in c.get("/").text + c.get("/app.js").text),
]
for name, ok in checks:
    bad += 0 if ok else 1
    print(("  [PASS] " if ok else "  [FAIL] ") + name)

print(f"\n== UI CHECK RESULT: {len(NEEDLES) + len(checks) - bad} passed, {bad} failed ==")
raise SystemExit(1 if bad else 0)
