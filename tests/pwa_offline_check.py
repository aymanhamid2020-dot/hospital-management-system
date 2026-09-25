# فحص PWA + الاستعداد للعمل دون اتصال: التسجيل، الكاش المسبق، استراتيجية الطابور، الـ manifest
# BASE_URL قابل للضبط (مثل بقية السكربتات) — الافتراضي 8001 محليًا، وCI يمرّره على 8000
import json
import os
import re

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8001")
c = httpx.Client(base_url=BASE_URL, timeout=30)
fails = []
total = 0


def ok(name, cond, extra=""):
    global total
    total += 1
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# ===== 1) الصفحة تُسجّل العامل وكشف التطبيق =====
ui = c.get("/")
ui_js = c.get("/app.js")
ok("الصفحة تُخدَّم على /", ui.status_code == 200)
ok("ملفات الوجهة المجزّأة app.css/app.js تصل 200",
   c.get("/app.css").status_code == 200 and ui_js.status_code == 200)
ok("تسجيل service worker على /sw.js",
   "serviceWorker.register('/sw.js'" in ui_js.text)
ok("ربط manifest.json", "manifest.json" in ui.text)
ok("أيقونة التطبيق متاحة", c.get("/icon.svg").status_code == 200)

# ===== 2) ملف العامل + اسم الكاش =====
sw = c.get("/sw.js")
ok("sw.js يُخدَّم 200", sw.status_code == 200)
_cache = re.search(r"const CACHE = '([^']+)'", sw.text)
ok("اسم الكاش hms-shell-v* (وتقدُّم بين الإصدارات)",
   bool(_cache) and _cache.group(1).startswith("hms-shell-v"),
   _cache.group(1) if _cache else "غير معروف")
ok("skipWaiting: العامل الجديد يستلم فورًا", "skipWaiting" in sw.text)
ok("cleanup old caches عند activate", "caches.delete" in sw.text)

# ===== 3) الكاش المسبق: كل هدف يجب أن ينجح 200 وإلا فشل التثبيت offline =====
# استخراج SHELL — يتحقق من تضمّن الخمس الأساسية (يتكيف مع إضافة أهداف جديدة دون كسر الفحص)
m = re.search(r"const SHELL = \[([^\]]+)\]", sw.text)
targets = re.findall(r"'([^']+)'", m.group(1)) if m else []
_CORE = {"/", "/app.css", "/app.js", "/manifest.json", "/icon.svg"}
ok("قائمة SHELL تضمّ الخمس الأساسية", _CORE <= set(targets), str(targets))
for t in targets:
    r = c.get(t)
    ok(f"الهدف المسبق {t} ⇒ 200", r.status_code == 200, str(r.status_code))

# ===== 4) استراتيجية الطابور: شبكة أولًا مع احتياط من الكاش =====
ok("الطابور network-first مع fallback للكاش",
   "/appointments/queue" in sw.text and "caches.match" in sw.text)
ok("ملفات القشرة network-first مع احتياط كاش (عند انقطاع الشبكة)",
   "SHELL.includes(url.pathname)" in sw.text)
q = c.get("/appointments/queue",
          headers={"Authorization": "Bearer " + c.post(
              "/auth/login", json={"username": "admin",
                                   "password": "admin123"}).json()["access_token"]})
ok("بيانات الطابور تصل 200 (يُكشَّن دون اتصال)", q.status_code == 200,
   str(q.status_code))

# ===== 5) manifest صالح للتثبيت كتطبيق =====
mf = c.get("/manifest.json")
ok("manifest 200", mf.status_code == 200)
try:
    data = json.loads(mf.text)
    ok("manifest JSON صالح", True)
except Exception as e:
    data = {}
    ok("manifest JSON صالح", False, str(e)[:60])
ok("start_url و scope = /",
   data.get("start_url") == "/" and data.get("scope") == "/")
ok("display=standalone + lang=ar + dir=rtl",
   data.get("display") == "standalone" and data.get("lang") == "ar"
   and data.get("dir") == "rtl")
ok("أيقونة واحدة على الأقل", len(data.get("icons", [])) >= 1)
ok("أيقونة الـ manifest تصل 200",
   bool(data.get("icons")) and c.get(data["icons"][0]["src"]).status_code == 200)

# ===== 6) لا كاش للمتصفح على / حتى يسري التحديث فورًا =====
cc = ui.headers.get("cache-control", "")
ok("/ يمنع الكاش (no-store)",
   "no-store" in cc or "no-cache" in cc, cc)

print(f"\n== PWA/OFFLINE RESULT: {total - len(fails)} passed, {len(fails)} failed ==")
raise SystemExit(1 if fails else 0)
