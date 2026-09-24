"""اختبار حمل خفيف: عمليات متزامنة على أهم المسارات + قياس زمن الاستجابة.

التشغيل:
    python tests/load_test.py                                  # localhost:8001
    BASE_URL=http://127.0.0.1:8000 python tests/load_test.py   # حاوية/نشر
    USERS=20 REQUESTS=30 python tests/load_test.py             # ضغط أعلى
    LOAD_USER=admin LOAD_PASS=... python tests/load_test.py    # حساب مخصّص
    P95_BUDGET_MS=500 python tests/load_test.py                # حد زمن p95

سكربت قراءة غالبًا (لا ينشئ ولا يعدّل بيانات) — يحكم PASS إذا: صفر أخطاء
وزمن p95 ≤ P95_BUDGET_MS. كود الخروج 0 عند نجاح الحكم.
"""
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8001").rstrip("/")
USERS = int(os.environ.get("USERS", "10"))
REQUESTS = int(os.environ.get("REQUESTS", "20"))
LOAD_USER = os.environ.get("LOAD_USER", "admin")
LOAD_PASS = os.environ.get("LOAD_PASS", "admin123")
P95_BUDGET_MS = float(os.environ.get("P95_BUDGET_MS", "700"))

# خليط قراءات تمثيلية (الحالة العامة + لوحة التحكم + القوائم الأساسية)
READS = [
    "/status",
    "/health",
    "/dashboard/stats",
    "/patients/",
    "/appointments/queue",
    "/notifications/unread-count",
]


def pct(vals, p):
    """المئين p من قائمة قيم مرتّبة."""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[k]


def worker(idx, token):
    """عامل واحد: REQUESTS طلبات تقرأ بالتناوب → (زمن، أخطاء، إجمالي)."""
    lat, errs, n = [], 0, 0
    with httpx.Client(
        base_url=BASE,
        timeout=30.0,
        headers={"Authorization": "Bearer " + token},
    ) as c:
        for i in range(REQUESTS):
            path = READS[(idx + i) % len(READS)]
            t0 = time.perf_counter()
            try:
                ok = c.get(path).status_code == 200
            except Exception:
                ok = False
            dt = (time.perf_counter() - t0) * 1000
            n += 1
            if ok:
                lat.append(dt)
            else:
                errs += 1
    return lat, errs, n


def main():
    r = httpx.post(
        BASE + "/auth/login",
        json={"username": LOAD_USER, "password": LOAD_PASS},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"فشل الدخول: {r.status_code} {r.text[:160]}")
        return 1
    token = r.json()["access_token"]

    total_planned = USERS * REQUESTS
    print(f"🔥 اختبار حمل على {BASE} — {USERS} متزامن × {REQUESTS} طلب "
          f"= {total_planned} طلب")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        results = [f.result() for f in
                   [ex.submit(worker, i, token) for i in range(USERS)]]
    wall = time.perf_counter() - t0

    lat = [x for xs, _, _ in results for x in xs]
    errs = sum(e for _, e, _ in results)
    total = sum(n for _, _, n in results)

    print(f"— الزمن الكلي: {wall:.2f}s | معدل الإنجاز: {total / wall:.1f} طلب/ث")
    print(f"— الطلبات: {total} | الناجحة: {len(lat)} | الفاشلة: {errs}")
    if lat:
        print(f"— زمن الاستجابة (ms): متوسط {statistics.mean(lat):.1f} | "
              f"p50 {pct(lat, 50):.1f} | p95 {pct(lat, 95):.1f} | "
              f"أقصى {max(lat):.1f}")

    verdict = errs == 0 and bool(lat) and pct(lat, 95) <= P95_BUDGET_MS
    print(f"— الحكم (صفر أخطاء + p95 ≤ {P95_BUDGET_MS:.0f}ms): "
          f"{'PASS ✅' if verdict else 'FAIL ❌'}")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
