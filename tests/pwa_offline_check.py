# فحص PWA + الاستعداد للعمل دون اتصال: التسجيل، الكاش المسبق، استراتيجية الطابور، الـ manifest
import json

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=30)
fails = []
total = 0


def ok(name, cond, extra=""):
    global total
    total += 1
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# ===== 1) الصفحة تُسجّل العامل وكشف التطبيق =====
ui = c.get("/ui/")
ui_js = c.get("/ui/app.js")
ok("الصفحة تُخدَّم على /ui/", ui.status_code == 200)
ok("ملفات الوجهة المجزّأة app.css/app.js تصل 200",
   c.get("/ui/app.css").status_code == 200 and ui_js.status_code == 200)
ok("تسجيل service worker على /ui/sw.js",
   "serviceWorker.register('/ui/sw.js')" in ui_js.text)
ok("ربط manifest.json", "manifest.json" in ui.text)
ok("أيقونة التطبيق متاحة", c.get("/ui/icon.svg").status_code == 200)

# ===== 2) ملف العامل + اسم الكاش =====
sw = c.get("/ui/sw.js")
ok("sw.js يُخدَّم 200", sw.status_code == 200)
ok("اسم الكاش hms-shell-v6", "hms-shell-v6" in sw.text)
ok("skipWaiting: العامل الجديد يستلم فورًا", "skipWaiting" in sw.text)
ok("cleanup old caches عند activate", "caches.delete" in sw.text)

# ===== 3) الكاش المسبق: كل هدف يجب أن ينجح 200 وإلا فشل التثبيت offline =====
# استخراج SHELL (الآن خمسة: الصفحة + app.css + app.js + manifest + الأيقونة)
import re
m = re.search(r"const SHELL = \[([^\]]+)\]", sw.text)
targets = re.findall(r"'([^']+)'", m.group(1)) if m else []
ok("قائمة SHELL بخمسة أهداف", len(targets) == 5, str(targets))
for t in targets:
    r = c.get(t)
    ok(f"الهدف المسبق {t} ⇒ 200", r.status_code == 200, str(r.status_code))

# ===== 4) استراتيجية الطابور: شبكة أولًا مع احتياط من الكاش =====
ok("الطابور network-first مع fallback للكاش",
   "/appointments/queue" in sw.text and "caches.match" in sw.text)
ok("ملفات /ui/ runtime cache (احتياط عند انقطاع الشبكة)",
   "url.pathname.startsWith('/ui/')" in sw.text)
q = c.get("/appointments/queue",
          headers={"Authorization": "Bearer " + c.post(
              "/auth/login", json={"username": "admin",
                                   "password": "admin123"}).json()["access_token"]})
ok("بيانات الطابور تصل 200 (يُكشَّن دون اتصال)", q.status_code == 200,
   str(q.status_code))

# ===== 5) manifest صالح للتثبيت كتطبيق =====
mf = c.get("/ui/manifest.json")
ok("manifest 200", mf.status_code == 200)
try:
    data = json.loads(mf.text)
    ok("manifest JSON صالح", True)
except Exception as e:
    data = {}
    ok("manifest JSON صالح", False, str(e)[:60])
ok("start_url و scope = /ui/",
   data.get("start_url") == "/ui/" and data.get("scope") == "/ui/")
ok("display=standalone + lang=ar + dir=rtl",
   data.get("display") == "standalone" and data.get("lang") == "ar"
   and data.get("dir") == "rtl")
ok("أيقونة واحدة على الأقل", len(data.get("icons", [])) >= 1)
ok("أيقونة الـ manifest تصل 200",
   bool(data.get("icons")) and c.get(data["icons"][0]["src"]).status_code == 200)

# ===== 6) لا كاش للمتصفح على /ui/ حتى يسري التحديث فورًا =====
cc = ui.headers.get("cache-control", "")
ok("/ui/ يمنع الكاش (no-store)",
   "no-store" in cc or "no-cache" in cc, cc)

print(f"\n== PWA/OFFLINE RESULT: {total - len(fails)} passed, {len(fails)} failed ==")
raise SystemExit(1 if fails else 0)
