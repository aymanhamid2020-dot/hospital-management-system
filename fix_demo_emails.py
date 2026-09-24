"""إصلاح نطاق البريد التجريبي: .local محجوز في التحقق من البريد (EmailStr).

يستبدل @demo.local بنطاق صالح في جداول: patients, doctors, staff, users.
آمن التكرار (LIKE يحدّد النطاق القديم فقط).
"""
from pydantic import EmailStr, TypeAdapter

from app.database import SessionLocal, engine
from sqlalchemy import text

OLD = "@demo.local"
CANDIDATES = ["hospital-demo.com", "demo-hospital.org", "clinic-demo.net"]

domain = None
for d in CANDIDATES:
    try:
        TypeAdapter(EmailStr).validate_python(f"test@{d}")
        domain = "@" + d
        break
    except Exception as e:
        print(f"  مرفوض: {d} — {e}")
if not domain:
    raise SystemExit("لا يوجد نطاق صالح من المرشحين")

print(f"النطاق الجديد: {domain}")

db = SessionLocal()
try:
    total = 0
    for table in ("patients", "doctors", "staff", "users"):
        res = db.execute(text(
            f"UPDATE {table} SET email = replace(email, :old, :new) "
            f"WHERE email LIKE :pat"
        ), {"old": OLD, "new": domain, "pat": f"%{OLD}"})
        total += res.rowcount or 0
        print(f"  {table}: {res.rowcount or 0} صف")
    db.commit()
    print(f"✅ تم تحديث {total} بريدًا")
finally:
    db.close()
