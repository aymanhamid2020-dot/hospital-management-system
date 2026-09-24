"""اختبارات العمليات: المراقبة المرئية، التصدير المتخصص CSV،
الإشعارات الفورية، النسخ التلقائي المجدول، وتحليل استخدام التدقيق."""
import os

from conftest import login
from test_advanced import _register, _make_linked_doctor, _make_patient_with


# ================= المراقبة =================
def test_monitor_page_and_extended_status(client):
    """صفحة /monitor تعمل دون توكن، و/status يحمل التنبيهات والإعدادات."""
    r = client.get("/monitor")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "لوحة مراقبة" in r.text

    d = client.get("/status").json()
    assert d["status"] == "ok"
    for k in ("low_stock", "lab_pending", "appointments_today", "unpaid_invoices"):
        assert isinstance(d["alerts"].get(k), int) and d["alerts"][k] >= 0
    assert d["reminders"]["enabled"] in (True, False)
    assert d["reminders"]["interval_minutes"] >= 0
    assert d["reminders"]["hours_before"] >= 0
    assert "interval_hours" in d["backups"] and "retention" in d["backups"]


# ================= تصدير CSV المتخصص =================
def test_specialized_report_csv_exports(client, admin):
    """مختبر/صيدلية/رواتب: CSV بـBOM وعناوين عربية + صلاحيات وفترة."""
    _, _, h_rec = _register(client, prefix="csvr")
    _, h_doc = _make_linked_doctor(client, admin, "csvdoc")

    # المختبر: المدير (الكل) والطبيب (طلباته) فقط
    r = client.get("/reports/lab/csv", headers=admin)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.content.decode("utf-8-sig")
    assert "المريض" in body and "التحليل" in body and "الحالة" in body
    assert client.get("/reports/lab/csv").status_code == 401
    assert client.get("/reports/lab/csv", headers=h_rec).status_code == 403
    assert client.get("/reports/lab/csv", headers=h_doc).status_code == 200

    # الصيدلية: للمدير + قسمان صحيحان وقسم خاطئ مرفوض
    r = client.get("/reports/pharmacy/csv", headers=admin)
    assert r.status_code == 200 and "الرمز" in r.content.decode("utf-8-sig")
    r = client.get("/reports/pharmacy/csv", headers=admin,
                   params={"section": "dispenses"})
    assert r.status_code == 200 and "المريض" in r.content.decode("utf-8-sig")
    r = client.get("/reports/pharmacy/csv", headers=admin,
                   params={"section": "bad"})
    assert r.status_code == 400
    assert client.get("/reports/pharmacy/csv", headers=h_rec).status_code == 403

    # الرواتب: للمدير + تحقق صيغة الفترة
    r = client.get("/reports/payroll/csv", headers=admin)
    assert r.status_code == 200 and "الصافي" in r.content.decode("utf-8-sig")
    r = client.get("/reports/payroll/csv", headers=admin, params={"period": "bad"})
    assert r.status_code == 400 and "YYYY-MM" in r.json()["detail"]
    assert client.get("/reports/payroll/csv", headers=h_rec).status_code == 403


# ================= الإشعارات الفورية =================
def test_notify_without_config_is_silent_noop(monkeypatch):
    """بلا إعداد: لا إرسال ولا استثناء — يرجع False."""
    from app import notifier
    calls = []
    monkeypatch.setattr(notifier, "_http_post_json",
                        lambda *a, **k: calls.append(a))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    assert notifier.notify("lab_result", "اختبار") is False
    assert calls == []


def test_notify_webhook_payload_and_failure_graceful(monkeypatch):
    """ويبهوك مضبوط: payload صحيح + إخفاق الشبكة لا يُصعّد."""
    from app import notifier
    calls = []
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.test/x")
    monkeypatch.setattr(notifier, "_http_post_json",
                        lambda url, payload, timeout=5: calls.append((url, payload)))
    assert notifier.notify("low_stock", "مخزون منخفض لدواء X") is True
    assert calls and calls[0][0] == "https://hooks.test/x"
    assert calls[0][1]["kind"] == "low_stock"
    assert "مخزون" in calls[0][1]["text"]
    assert calls[0][1]["service"] == "hospital-management-system"

    def boom(*a, **k):
        raise OSError("انقطاع الشبكة")
    monkeypatch.setattr(notifier, "_http_post_json", boom)
    assert notifier.notify("low_stock", "مرة أخرى") is False  # لا يُصعّد


# ================= النسخ التلقائي المجدول =================
def test_auto_backup_creates_and_prunes(client, tmp_path):
    """5 نسخ بحد احتفاظ3: تبقى الأحدث وتحتوي جداول حقيقية."""
    import sqlite3
    from app.tasks import create_auto_backup

    d = str(tmp_path)
    made = []
    for _ in range(5):
        p = create_auto_backup(backup_dir=d, retention=3)
        assert p and os.path.exists(p), "النسخة التلقائية لم تُنشأ"
        made.append(p)

    autos = sorted(n for n in os.listdir(d)
                   if n.startswith("auto_") and n.endswith(".db"))
    assert len(autos) == 3, f"التقليم أبقى {len(autos)} بدل 3"
    oldest = sorted(os.path.basename(m) for m in made)
    assert oldest[0] not in autos and oldest[1] not in autos  # القديم محذوف
    assert oldest[-1] in autos  # الأحدث باقٍ

    # اللقطة سليمة فعليًا (جداول موجودة)
    con = sqlite3.connect(os.path.join(d, oldest[-1]))
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "patients" in tables and "users" in tables


def test_auto_backup_disabled_for_non_sqlite(monkeypatch, tmp_path):
    """PostgreSQL: لا نسخ تلقائي (None) ولا ملفات تُنشأ."""
    import app.config as cfg
    from app.tasks import create_auto_backup

    monkeypatch.setattr(cfg, "DATABASE_URL",
                        "postgresql://hospital:pass@db:5432/hospital")
    assert create_auto_backup(backup_dir=str(tmp_path)) is None
    assert os.listdir(tmp_path) == []


# ================= تحليل استخدام التدقيق =================
def test_audit_stats_analysis(client, admin):
    """/audit-logs/stats: توزيع الطرق + مستخدمون ومسارات مطبّعة + أخطاء."""
    _register(client, prefix="astat")
    # بعض عمليات POST/PUT من هذا الاختبار نفسه تظهر في التحليل
    r = client.get("/audit-logs/stats", headers=admin)
    assert r.status_code == 200
    d = r.json()
    assert d["window_days"] >= 1
    assert d["total"] >= 1 and d["recent"] >= 1
    assert d["by_method"].get("POST", 0) >= 1
    assert isinstance(d["top_users"], list) and d["top_users"]
    assert d["top_users"][0]["count"] >= 1
    # المسارات مطبّعة: لا نصوص استعلام ولا معرفات خام في القمة
    assert isinstance(d["top_paths"], list)
    assert all("?" not in p["path"] for p in d["top_paths"])
    assert isinstance(d["recent_errors"], list)
    # محاولات الدخول الفاشلة تظهر ضمن التحليل (قسم جديد)
    lf = d.get("login_failures") or {}
    assert isinstance(lf.get("total"), int)
    assert isinstance(lf.get("last_24h"), int)
    assert isinstance(lf.get("recent"), list)

    # المدير فقط
    _, _, h_rec = _register(client, prefix="astx")
    assert client.get("/audit-logs/stats", headers=h_rec).status_code == 403
    assert client.get("/audit-logs/stats").status_code == 401


# ================= الأمان: قفل الدخول وقوة كلمة المرور =================
def test_login_lockout_and_recovery(client, monkeypatch):
    """5 محاولات فاشلة → قفل 429 (حتى بال كلمة الصحيحة) ثم فتح بالنافذة 0."""
    r = client.post("/auth/register", json={
        "username": "lockuser1", "email": "lock1@t.com",
        "full_name": "مستخدم اختبار قفل", "password": "secret123"})
    assert r.status_code == 200, r.text

    bad = {"username": "lockuser1", "password": "badpass1"}
    codes = [client.post("/auth/login", json=bad).status_code
             for _ in range(5)]
    assert codes == [401, 401, 401, 401, 401]

    # السادس: مقفول — حتى بصحة كلمة المرور
    r = client.post("/auth/login", json=bad)
    assert r.status_code == 429
    assert "ثانية" in r.json()["detail"]
    good = {"username": "lockuser1", "password": "secret123"}
    assert client.post("/auth/login", json=good).status_code == 429

    # نافذة صفر = تعطيل القفل → دخول صحيح فوري ويُصفّر العدّاد
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "0")
    r = client.post("/auth/login", json=good)
    assert r.status_code == 200, r.text
    # وعادت الحماية تعمل بعد إعادة التفعيل
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "15")
    for _ in range(5):
        client.post("/auth/login", json=bad)
    assert client.post("/auth/login", json=bad).status_code == 429
    monkeypatch.delenv("LOGIN_LOCKOUT_MINUTES", raising=False)
    # تنظيف: نافذة انتهت لا تُفتح بالوصول — نُصفّر العدّاد عبر النافذة المؤقتة
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "0")
    assert client.post("/auth/login", json=good).status_code == 200


def test_password_strength_validation(client):
    """قوة كلمة المرور عند التسجيل وتغيير كلمة المرور."""
    def register(u, pw):
        return client.post("/auth/register", json={
            "username": u, "email": f"{u}@t.com",
            "full_name": "اختبار قوة", "password": pw})

    assert register("strpw1", "12345678").status_code == 400   # بلا حرف
    assert register("strpw2", "abcdefgh").status_code == 400   # بلا رقم
    # قصيرة: يرفضها إما فحص القوة (400) أو قيد المخطط في Pydantic (422)
    assert register("strpw3", "abc").status_code in (400, 422)
    r = register("strgood", "abcd1234")
    assert r.status_code == 200, r.text

    h = login(client, "strgood", "abcd1234")
    # تغيير كلمة المرور يفرض القوة أيضًا
    r = client.post("/auth/change-password", headers=h, json={
        "current_password": "abcd1234", "new_password": "weak"})
    assert r.status_code in (400, 422)
    r = client.post("/auth/change-password", headers=h, json={
        "current_password": "abcd1234", "new_password": "strong99"})
    assert r.status_code == 200


# ================= الواجهة: اللغة الإنجليزية + PWA =================
def test_i18n_toggle_markers_in_ui(client):
    """زر تبديل اللغة + قاموس الترجمة + تبديل اتجاه LTR موجودان في الواجهة."""
    html = client.get("/ui/").text
    assert "toggleLang" in html
    assert "AR2EN" in html and "lang-btn" in html
    assert "applyI18n" in html and "localStorage.getItem('hms_lang')" in html


def test_pwa_manifest_and_service_worker(client):
    """ملفات PWA تُقدَّم ومسجّلتها في الصفحة."""
    m = client.get("/ui/manifest.json")
    assert m.status_code == 200
    data = m.json()
    assert data["start_url"] == "/ui/" and data["display"] == "standalone"
    assert data["theme_color"] == "#2c7be5"
    assert data["icons"][0]["src"] == "/ui/icon.svg"

    sw = client.get("/ui/sw.js")
    assert sw.status_code == 200
    assert "caches" in sw.text and "/appointments/queue" in sw.text
    assert "serviceWorker.register('/ui/sw.js')" in client.get("/ui/").text
    assert client.get("/ui/icon.svg").status_code == 200


# ================= التقارير الإنجليزية (lang=en) =================
def test_english_reports_pdf(client, admin):
    """التقارير الأربعة تُصدر بالإنجليزية مع lang=en ويرفض لغة مجهولة."""
    for p in ("/dashboard/report/pdf", "/reports/lab/pdf",
              "/reports/pharmacy/pdf", "/reports/payroll/pdf"):
        r = client.get(p, headers=admin, params={"lang": "en"})
        assert r.status_code == 200, f"{p}: {r.status_code} {r.text[:120]}"
        assert r.content[:4] == b"%PDF"
        assert "_en" in r.headers.get("content-disposition", "")
    # العربية هي الافتراض
    r = client.get("/reports/lab/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert "lab_report.pdf" in r.headers.get("content-disposition", "")
    # لغة مجهولة مرفوضة
    r = client.get("/reports/lab/pdf", headers=admin, params={"lang": "fr"})
    assert r.status_code == 400


# ================= استعادة النسخ الاحتياطي =================
def test_backup_restore_roundtrip(client, admin):
    """إنشاء نسخة → إضافة مريض → استعادة → يختفي المريض مع نسخة أمان."""
    r = client.post("/backup", headers=admin)
    assert r.status_code == 200, r.text
    fname = r.json()["file"]

    p = client.post("/patients/", headers=admin, json={
        "full_name": "مريض قبل الاستعادة", "date_of_birth": "1995-05-05",
        "gender": "ذكر", "phone": "0555101010",
        "email": "restore_marker@t.com"})
    assert p.status_code == 200, p.text
    pid = p.json()["id"]

    r = client.post(f"/backup/{fname}/restore", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restored"] == fname
    assert body["safety_copy"].startswith("auto_")

    # المريض المضاف بعد النسخة اختفى بعد الاستعادة
    assert client.get(f"/patients/{pid}", headers=admin).status_code == 404
    # نسخة الأمان ظاهرة في القائمة + حقل restorable في كل عنصر
    lst = client.get("/backup", headers=admin)
    assert lst.status_code == 200
    names = {f["file"] for f in lst.json()}
    assert body["safety_copy"] in names
    assert all("restorable" in f for f in lst.json())


def test_restore_rejects_bad_files(client, admin):
    """استعادة: غير موجود 404 + اقتحام مسار مرفوض + ملف غير صالح 400."""
    r = client.post("/backup/nope_does_not_exist.db/restore", headers=admin)
    assert r.status_code == 404
    r = client.post("/backup/..%2Fhospital.db/restore", headers=admin)
    assert r.status_code in (400, 404)

    # ملف مزيّف باسم ‎.db‎ يُرفض قبل المساس بالقاعدة
    from app.routers import backup as backup_mod
    os.makedirs(backup_mod.BACKUP_DIR, exist_ok=True)
    fake = os.path.join(backup_mod.BACKUP_DIR, "_fake_restore_test.db")
    with open(fake, "wb") as fh:
        fh.write(b"this is not a sqlite database")
    try:
        r = client.post("/backup/_fake_restore_test.db/restore", headers=admin)
        assert r.status_code == 400, r.text
    finally:
        if os.path.exists(fake):
            os.remove(fake)

    # غير المدير ممنوع
    _, _, h_rec = _register(client, prefix="resx")
    assert client.post("/backup/x.db/restore",
                       headers=h_rec).status_code == 403


# ================= الواجهة: التقويم + إدارة المستخدمين =================
def test_calendar_markers_in_ui(client):
    """تقويم المواعيد الشهري: دوال التبديل والتنقل والعرض في الواجهة."""
    html = client.get("/ui/").text
    for marker in ("renderCalendar", "calNav", "toggleCal",
                   "CAL_MONTHS", "cal-grid"):
        assert marker in html, marker


def test_users_admin_view_markers_in_ui(client):
    """شاشة إدارة المستخدمين: الرابط + الدوال + زر استعادة النسخ."""
    html = client.get("/ui/").text
    for marker in ('data-view="users"', "async users(main)", "setRole",
                   "toggleUser", "saveUser", "restoreBackup"):
        assert marker in html, marker


# ================= إدارة الأدوار من الواجهة (الواجهة الخلفية) =================
def test_user_role_management(client, admin):
    """تغيير دور: نجاح + منع الذات + لغة دور مجهولة + تفعيل/تعطيل + صلاحيات."""
    r = client.post("/auth/register", json={
        "username": "roletest1", "email": "role1@t.com",
        "full_name": "مستخدم تجربة دور", "password": "RolePass123",
        "role": "موظف استقبال"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]

    # القائمة للمدير فقط
    users = client.get("/auth/users", headers=admin)
    assert users.status_code == 200
    ulist = users.json()
    assert any(u["id"] == uid for u in ulist)
    assert client.get("/auth/users").status_code == 401

    # تغيير الدور إلى طبيب
    r = client.put(f"/auth/users/{uid}/role", headers=admin, json={"role": "doctor"})
    assert r.status_code == 200 and r.json()["role"] == "doctor"

    # منع الذات + لغة دور مجهولة + غير موجود
    admin_id = next(u["id"] for u in ulist if u["username"] == "admin")
    r = client.put(f"/auth/users/{admin_id}/role", headers=admin,
                   json={"role": "doctor"})
    assert r.status_code == 400 and "حسابك" in r.json()["detail"]
    assert client.put(f"/auth/users/{uid}/role", headers=admin,
                      json={"role": "superuser"}).status_code == 422
    assert client.put("/auth/users/999999/role", headers=admin,
                      json={"role": "doctor"}).status_code == 404

    # تفعيل/تعطيل
    r = client.put(f"/auth/users/{uid}/toggle", headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = client.put(f"/auth/users/{uid}/toggle", headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is True

    # غير المدير ممنوع
    _, _, h_rec = _register(client, prefix="rolx")
    assert client.put(f"/auth/users/{uid}/role", headers=h_rec,
                      json={"role": "doctor"}).status_code == 403


# ================= حماية الـIP لمحاولات الدخول =================
def test_ip_login_limiter(client, monkeypatch):
    """حد الـIP: 5 محاولات فاشلة بأسماء مختلفة → 429 حتى بال الدخول الصحيح."""
    from app.routers import auth as auth_mod

    monkeypatch.setenv("AUTH_IP_FAIL_MAX", "5")
    monkeypatch.setenv("AUTH_IP_WINDOW_MINUTES", "15")
    auth_mod._ip_failed_logins.clear()
    try:
        codes = []
        for i in range(5):
            r = client.post("/auth/login", json={
                "username": f"ghost_{i}", "password": "badpass1"})
            codes.append(r.status_code)
        assert codes == [401] * 5, codes

        # السادس باسم مختلف (تدوير الأسماء): قفل الـIP وليس قفل المستخدم
        r = client.post("/auth/login", json={
            "username": "ghost_final", "password": "badpass1"})
        assert r.status_code == 429
        assert "من هذا العنوان" in r.json()["detail"]

        # حتى دخول صحيح يُمنع خلال النافذة
        r = client.post("/auth/login", json={
            "username": "admin", "password": "admin123"})
        assert r.status_code == 429
    finally:
        auth_mod._ip_failed_logins.clear()
        monkeypatch.delenv("AUTH_IP_FAIL_MAX", raising=False)
        monkeypatch.delenv("AUTH_IP_WINDOW_MINUTES", raising=False)


# ================= الحسابات والمبيعات =================
def test_accounts_summary_no_token(client):
    assert client.get("/accounts/summary").status_code == 401
    assert client.get("/accounts/sales").status_code == 401


def test_accounts_sale_payment_flow(client, admin):
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC100", "name": "اختبار حساب", "quantity": 100,
        "unit": "علبة", "price": 25.5, "min_quantity": 10})
    assert r.status_code == 200
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض الحسابات", "0555101010", "1990-01-01")
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 2})
    assert r.status_code == 200
    d = r.json()
    assert d["total_price"] == 51.0 and d["status"] == "UNPAID"
    disp_id = d["id"]
    assert client.get("/accounts/summary", headers=admin).json()["total_sales"] >= 51.0
    pr = client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                       json={"paid_amount": 20.0, "payment_method": "cash"}).json()
    assert pr["status"] == "PARTIAL"
    s = client.get("/accounts/summary", headers=admin).json()
    assert s["count"] >= 1 and s["total_sales"] >= 51.0
    pr2 = client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                        json={"paid_amount": 51.0, "payment_method": "card"}).json()
    assert pr2["status"] == "PAID" and pr2["paid_amount"] == 51.0
    assert client.get("/accounts/summary", headers=admin).json()["total_paid"] >= 51.0


def test_accounts_repaid_forbidden(client, admin):
    """صلاحية أدق: لا يُسمح بإعادة تسديد عملية مسدّدة بالكامل (409)."""
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC710", "name": "لمنع الإعادة", "quantity": 20,
        "unit": "علبة", "price": 4.0, "min_quantity": 2})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض مسدّد", "0555818181", "1992-03-03")
    d = client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 2}).json()
    disp_id = d["id"]
    ok = client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                    json={"paid_amount": 8.0, "payment_method": "cash"})
    assert ok.status_code == 200 and ok.json()["status"] == "PAID"
    again = client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                       json={"paid_amount": 8.0, "payment_method": "cash"})
    assert again.status_code == 409, "إعادة تسديد عملية مسدّدة ⇒ 409"
    # حتى المبلغ الصغير يُمنع بعد اكتمال الدفع
    less = client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                      json={"paid_amount": 1.0, "payment_method": "cash"})
    assert less.status_code == 409


def test_accounts_receipt_html(client, admin):
    """إيصال الدفعة: HTML قابل للطباعة بالعربية والإنجليزية."""
    assert client.get("/accounts/sales/999999/receipt").status_code == 401
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC720", "name": "لإيصال", "quantity": 30,
        "unit": "علبة", "price": 9.0, "min_quantity": 3})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض الإيصال", "0555828282", "1988-08-08")
    d = client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 3}).json()
    disp_id = d["id"]
    rc = client.get(f"/accounts/sales/{disp_id}/receipt", headers=admin)
    assert rc.status_code == 200 and "html" in rc.headers["content-type"].lower()
    assert rc.text.startswith("<!DOCTYPE html>")
    for needle in ("إيصال دفعة", "27.00", "المريض", "الإجمالي"):
        assert needle in rc.text, needle
    en = client.get(f"/accounts/sales/{disp_id}/receipt", headers=admin,
                    params={"lang": "en"})
    assert en.status_code == 200 and "Payment receipt" in en.text
    assert "SAR" in en.text
    assert client.get(f"/accounts/sales/{disp_id}/receipt", headers=admin,
                      params={"lang": "fr"}).status_code == 400
    assert client.get("/accounts/sales/999999/receipt",
                      headers=admin).status_code == 404


def test_accounts_patient_statement(client, admin):
    """كشف حساب مريض: JSON + طباعة HTML (عربي/إنجليزي)."""
    assert client.get("/accounts/statement/1").status_code == 401
    assert client.get("/accounts/statement/999999",
                      headers=admin).status_code == 404
    assert client.get("/accounts/statement/999999/print",
                      headers=admin).status_code == 404
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC730", "name": "لكشف", "quantity": 40,
        "unit": "علبة", "price": 11.0, "min_quantity": 4})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض كشف حساب", "0555838383", "1995-05-05")
    client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 2})
    st = client.get(f"/accounts/statement/{pid}", headers=admin)
    assert st.status_code == 200
    body = st.json()
    assert body["patient"]["id"] == pid
    assert body["patient"]["full_name"] == "مريض كشف حساب"
    t = body["totals"]
    assert t["sales_total"] >= 22.0
    assert abs(t["dues"] - (t["sales_total"] + t["inv_total"])) < 0.02
    assert isinstance(body["sales"], list) and isinstance(body["invoices"], list)
    # طباعة HTML
    pr = client.get(f"/accounts/statement/{pid}/print", headers=admin)
    assert pr.status_code == 200 and pr.text.startswith("<!DOCTYPE html>")
    assert "كشف حساب مريض" in pr.text and "مريض كشف حساب" in pr.text
    assert "مبيعات الصيدلية" in pr.text
    en = client.get(f"/accounts/statement/{pid}/print", headers=admin,
                    params={"lang": "en"})
    assert en.status_code == 200 and "Patient statement" in en.text
    assert client.get(f"/accounts/statement/{pid}/print", headers=admin,
                      params={"lang": "de"}).status_code == 400
    # PDF الكشف: عربي + إنجليزي + أخطاء اللغة والتوكن
    pdf = client.get(f"/accounts/statement/{pid}/pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert "patient_statement_" in pdf.headers["content-disposition"]
    enpdf = client.get(f"/accounts/statement/{pid}/pdf", headers=admin,
                       params={"lang": "en"})
    assert enpdf.status_code == 200 and enpdf.content[:4] == b"%PDF"
    assert "_en.pdf" in enpdf.headers["content-disposition"]
    assert client.get(f"/accounts/statement/{pid}/pdf", headers=admin,
                      params={"lang": "de"}).status_code == 400
    assert client.get(f"/accounts/statement/999999/pdf",
                      headers=admin).status_code == 404
    assert client.get(f"/accounts/statement/{pid}/pdf").status_code == 401
    assert "PDF الكشف" in client.get("/ui/").text


def test_accounts_payment_validation(client, admin):
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC200", "name": "للتحقق", "quantity": 50,
        "unit": "علبة", "price": 10.0, "min_quantity": 5})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض تحقق", "0555202020", "1985-05-05")
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 1})
    disp_id = r.json()["id"]
    assert client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                       json={"paid_amount": 100, "payment_method": "cash"}).status_code == 400
    assert client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                       json={"paid_amount": -5, "payment_method": "cash"}).status_code == 422
    assert client.put("/accounts/sales/999999/payment", headers=admin,
                       json={"paid_amount": 10, "payment_method": "cash"}).status_code == 404


def test_accounts_filters(client, admin):
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC300", "name": "للفلترة", "quantity": 30,
        "unit": "علبة", "price": 5.0, "min_quantity": 5})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض فلتر", "0555303030", "1970-01-01")
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 1})
    disp_id = r.json()["id"]
    client.put(f"/accounts/sales/{disp_id}/payment", headers=admin,
                json={"paid_amount": 5.0, "payment_method": "insurance"})
    assert any(x["id"] == disp_id for x in client.get("/accounts/sales", headers=admin, params={"patient_id": pid}).json())
    assert any(x["id"] == disp_id for x in client.get("/accounts/sales", headers=admin, params={"status": "PAID"}).json())
    assert any(x["id"] == disp_id for x in client.get("/accounts/sales", headers=admin, params={"payment_method": "insurance"}).json())


def test_accounts_csv_pdf_admin_only(client, admin):
    assert client.get("/reports/accounts/sales/csv").status_code == 401
    _, _, h_nonadmin = _register(client, prefix="csvr")
    assert client.get("/reports/accounts/sales/csv", headers=h_nonadmin).status_code == 403
    assert client.get("/reports/accounts/sales/csv", headers=admin).status_code == 200
    assert client.get("/reports/accounts/sales/pdf", headers=admin).status_code == 200


def test_accounts_summary_by_period(client, admin):
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC400", "name": "للفترة", "quantity": 20,
        "unit": "علبة", "price": 7.0, "min_quantity": 5})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض فترة", "0555404040", "1992-03-03")
    client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 3})
    assert client.get("/accounts/summary", headers=admin, params={"period": "2026-09"}).json()["total_sales"] >= 21.0
    assert client.get("/reports/accounts/sales/csv", headers=admin, params={"period": "2026-09"}).status_code == 200
    assert client.get("/reports/accounts/sales/pdf", headers=admin, params={"period": "2026-09"}).status_code == 200


def test_accounts_revenue_curve(client, admin):
    assert client.get("/accounts/revenue").status_code == 401
    r = client.get("/accounts/revenue", headers=admin)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        assert all(set(("date", "sales", "collected", "count")) <= set(x) for x in rows)
        assert all(x["collected"] <= x["sales"] + 0.01 for x in rows)
        days = [x["date"] for x in rows]
        assert days == sorted(days)
    # تجميع شهري + صيغ خاطئة
    m = client.get("/accounts/revenue", headers=admin, params={"group": "month"})
    assert m.status_code == 200
    assert all(len(x["date"]) == 7 for x in m.json())
    assert client.get("/accounts/revenue", headers=admin,
                      params={"group": "bad"}).status_code == 400
    assert client.get("/accounts/revenue", headers=admin,
                      params={"period": "bad"}).status_code == 400


def test_accounts_revenue_grows(client, admin):
    """الإيراد اليومي يعكس عملية صرف جديدة"""
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC500", "name": "لإيراد", "quantity": 40,
        "unit": "علبة", "price": 4.0, "min_quantity": 5})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض إيراد", "0555505050", "1995-05-05")
    before = sum(x["sales"] for x in
                 client.get("/accounts/revenue", headers=admin).json())
    client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 5})
    after = sum(x["sales"] for x in
                client.get("/accounts/revenue", headers=admin).json())
    assert after >= before + 20.0


def test_accounts_debtors(client, admin):
    assert client.get("/accounts/debtors").status_code == 401
    r = client.post("/medications/", headers=admin, json={
        "code": "ACC600", "name": "لمدين", "quantity": 30,
        "unit": "علبة", "price": 6.0, "min_quantity": 5})
    med_id = r.json()["id"]
    pid = _make_patient_with(client, admin, "مريض مدين اختبار", "0555606060", "1980-02-02")
    d = client.post("/dispenses/", headers=admin, json={
        "medication_id": med_id, "patient_id": pid, "quantity": 2}).json()
    assert d["status"] == "UNPAID" and d["total_price"] == 12.0

    rows = client.get("/accounts/debtors", headers=admin).json()
    me = next((x for x in rows if x["patient_id"] == pid), None)
    assert me is not None, "المريض غير المسدّد يجب أن يظهر في المدينين"
    assert me["full_name"] == "مريض مدين اختبار"
    assert me["operations"] >= 1
    assert abs(me["total"] - me["paid"] - me["outstanding"]) < 0.02
    assert me["outstanding"] >= 12.0
    # ترتيب تنازلي + استبعاد المسدّد بالكامل
    outs = [x["outstanding"] for x in rows]
    assert outs == sorted(outs, reverse=True)
    assert all(x["outstanding"] > 0 for x in rows)
    # رفع الحد الأدنى يقصّ الصغار
    high = client.get("/accounts/debtors", headers=admin,
                      params={"min_outstanding": me["outstanding"] + 1000}).json()
    assert all(x["outstanding"] >= me["outstanding"] + 1000 for x in high)
    # سالب ⇒ 422
    assert client.get("/accounts/debtors", headers=admin,
                      params={"min_outstanding": -1}).status_code == 422

    # بعد التسديد الكامل يختفي من المدينين
    client.put(f"/accounts/sales/{d['id']}/payment", headers=admin,
               json={"paid_amount": 12.0, "payment_method": "cash"})
    rows2 = client.get("/accounts/debtors", headers=admin).json()
    assert all(x["patient_id"] != pid for x in rows2)

