"""تنظيف حسابات الاختبار المؤقتة من قاعدة التطوير عبر `DELETE /auth/users/{id}`.

الفحوصات الحية (`*_flow_check.py`، اختبارات E2E، سكربتات اليدوي) تُنشئ حسابات
زائلة تبقى في `hospital.db` بعد انتهاء الجلسة — وهذا الأداة يجمعها ببصمات
اسمية معروفة ويحذفها محترمًا حارسَي الخادم (الذات وآخر مدير نشط).

الوضع الافتراضي **تجريبي (dry-run)**: يعرض القائمة فقط. اضغط التحذف بـ`--apply`.

    python tests/cleanup_temp_users.py --base http://127.0.0.1:8000 --apply
    python tests/cleanup_temp_users.py --pattern '^qa_' --pattern '^dev_' --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# بصمات حسابات الاختبار المعروفة في هذا المستودع (لا تُسند أبدًا لـ demo_*)
DEFAULT_PATTERNS = (
    r"^uadm",                 # tests/e2e/users-admin.spec.ts
    r"^livedel",              # فحص الحذف الحيّ
    r"^del[A-C]_",            # tests/test_user_admin.py
    r"^livemgr",              # فحص تغيير الأدوار حيًّا
    r"^cnt_pw_user$",         # فحص قفل الدخول
    r"^recph_", r"^recp_",    # فحص الوصفات/الصيدلية (استقبال)
    r"^own_", r"^oth_", r"^nolink_",   # فحص ملفات الطبيب
    r"^qsQ", r"^qrQ", r"^qnQ",         # فحص البحث العام
    r"^cash_", r"^fin_",       # فحص الحسابات والمبيعات
)

PROTECTED = ("admin",)


def collect_temp_users(rows, patterns=DEFAULT_PATTERNS, protected=PROTECTED):
    """حسابات الاختبار المرشحة للحذف من قائمة مستخدمين.

    `rows`: قوائم/مسجّلات فيها `.id` و`.username` (استجابة `GET /auth/users`).
    لا يُعيد الحسابات المحميّة حتى لو طابقت بصمة، وتُطابق البصمات أوّلًا
    بالتعبير الكامل على اسم المستخدم كي لا يبتلع حدّأً مثل `^del`.
    """
    rx = [re.compile(p) for p in patterns]
    keep = set(protected)
    out = []
    for r in rows:
        uname = (r.get("username") if isinstance(r, dict) else getattr(r, "username", "")) or ""
        uid = r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
        if uname in keep:
            continue
        if any(p.search(uname) for p in rx):
            out.append({"id": uid, "username": uname})
    return out


def _login(base: str, user: str, password: str) -> str:
    import httpx
    r = httpx.post(f"{base}/auth/login",
                   json={"username": user, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="حذف حسابات الاختبار المؤقتة")
    ap.add_argument("--base", default=os.environ.get("LIVE_BASE", "http://127.0.0.1:8000"),
                    help="عنوان الخادم (افتراضي من LIVE_BASE ثم 8000)")
    ap.add_argument("--user", default=os.environ.get("STACK_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("STACK_PASS", "admin123"))
    ap.add_argument("--pattern", action="append", default=None,
                    help="بصمة اسم مستخدم (تكرارها متاح) — إن وُجدت غيّرت البصمات الافتراضية")
    ap.add_argument("--apply", action="store_true",
                    help="تنفيذ الحذف فعليًا (الافتراضي: عرض فقط)")
    a = ap.parse_args(argv)

    patterns = tuple(a.pattern) if a.pattern else DEFAULT_PATTERNS
    try:
        import httpx
        tok = _login(a.base, a.user, a.password)
        h = {"Authorization": f"Bearer {tok}"}
        rows = httpx.get(f"{a.base}/auth/users", headers=h, timeout=30)
        rows.raise_for_status()
        users = rows.json()
    except Exception as e:                                   # noqa: BLE001
        print(f"[FAIL] تعذّر الوصول إلى {a.base}: {e}", file=sys.stderr)
        return 1

    victims = collect_temp_users(users, patterns)
    print(f"حسابات الاختبار المرشّحة من أصل {len(users)}: {len(victims)}")
    for v in victims:
        print(f"  - #{v['id']} {v['username']}")

    if not victims:
        print("لا شيء لتنظيفه ✅")
        return 0
    if not a.apply:
        print("وضع تجريبي: أعد الأمر بـ --apply للحذف الفعلي.")
        return 0

    ok = fail = 0
    for v in victims:
        r = httpx.delete(f"{a.base}/auth/users/{v['id']}", headers=h, timeout=30)
        if r.status_code == 204:
            ok += 1
        else:
            fail += 1
            print(f"  [FAIL] #{v['id']} {v['username']} ⇒ {r.status_code} {r.text[:120]}",
                  file=sys.stderr)
    print(f"حُذف {ok} حسابًا، وفشل {fail} — المتبقي من حسابات النظام: "
          f"{len(users) - len(victims)}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
