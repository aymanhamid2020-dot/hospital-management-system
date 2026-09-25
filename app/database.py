from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import time
from contextlib import contextmanager

from app.config import DATABASE_URL

_IS_SQLITE = "sqlite" in DATABASE_URL

# توازن اتصالات يكفي العمل المتزامن (كانت 5+10 = 15 تكفي حتى 10 مستخدمين
# ثم تنفد عند 20-30 متزامن فتنتهي كل طلبات بانتظار 30 ثانية)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15} if _IS_SQLITE else {},
    pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
    max_overflow=int(os.getenv("DB_POOL_MAX_OVERFLOW", "30")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_pre_ping=True,
    echo=os.getenv("SQL_ECHO", "False").lower() == "true",
)

if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        """إعدادات SQLite لكل اتصال: FK + وضع WAL.

        WAL يمنع تعارض القرّاء مع الكاتب: في الوضع العادي (delete) كان أي
        كتابة (تذكير/تدقيق) يوقف كل الاستعلامات على حلقة الأحداث حتى /health.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# أعمدة جديدة تُضاف للجداول القائمة عند الترقية (بدون حذف البيانات)
PENDING_COLUMNS = {
    "invoices": {
        "appointment_id": "INTEGER",
        "record_id": "INTEGER",
        "payment_method": "VARCHAR",
        "paid_at": "TIMESTAMP",
        "insurer": "VARCHAR",
        "policy_number": "VARCHAR",
        "discount": "FLOAT NOT NULL DEFAULT 0",
        "tax_rate": "FLOAT NOT NULL DEFAULT 0",
        "paid_amount": "FLOAT NOT NULL DEFAULT 0",
    },
    "patients": {
        "national_id": "VARCHAR",
        "insurer": "VARCHAR",
        "policy_number": "VARCHAR",
        # الملف الشخصي والإداري + التاريخ الطبي (شاشة ملف المريض)
        "nationality": "VARCHAR",
        "smoking_status": "VARCHAR",
        "emergency_contact_name": "VARCHAR",
        "emergency_contact_phone": "VARCHAR",
        "emergency_contact_relation": "VARCHAR",
        "insurance_grade": "VARCHAR",
        "insurance_copay": "FLOAT",
        "chronic_conditions": "TEXT",
        "past_surgeries": "TEXT",
        "family_history": "TEXT",
        "allergies": "TEXT",
        "medical_warnings": "TEXT",
    },
    "medical_records": {
        # شكوى المريض في كل زيارة
        "chief_complaint": "VARCHAR",
    },
    "appointments": {
        "checked_in_at": "TIMESTAMP",
        "queue_number": "INTEGER",
    },
    "dispenses": {
        "total_price": "FLOAT NOT NULL DEFAULT 0",
        "payment_method": "VARCHAR NOT NULL DEFAULT 'cash'",
        "status": "VARCHAR NOT NULL DEFAULT 'UNPAID'",
        "paid_amount": "FLOAT NOT NULL DEFAULT 0",
        "paid_at": "TIMESTAMP",
        # تطوير الصيدلية: توجيه الاستخدام + الإرجاع + ربط الوصفة
        "dosage": "VARCHAR",
        "frequency": "VARCHAR",
        "duration": "VARCHAR",
        "instructions": "VARCHAR",
        "prescription_id": "INTEGER",
        "returned_at": "TIMESTAMP",
        "return_reason": "VARCHAR",
        "returned_by": "VARCHAR",
    },
    "notifications": {
        # تنبيه الوصفات المعلّقة: ربط الإشعار بالوصفة لمنع التكرار
        "prescription_id": "INTEGER",
    },
    "staff": {
        # ملف الموارد البشرية يُحفظ JSON نصيًا ليعمل SQLite وPostgreSQL معًا
        "hr_profile": "TEXT NOT NULL DEFAULT '{}'",
    },
}

# إعادة بناء جدول الفواتير مع مفاتيح FK سليمة (ALTER TABLE لا يدعم REFERENCES في SQLite)
_INVOICES_REBUILD_DDL = """
CREATE TABLE _invoices_rebuild (
    id INTEGER NOT NULL PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    appointment_id INTEGER,
    record_id INTEGER,
    amount FLOAT NOT NULL,
    description VARCHAR,
    status VARCHAR,
    payment_method VARCHAR,
    paid_at TIMESTAMP,
    insurer VARCHAR,
    policy_number VARCHAR,
    discount FLOAT NOT NULL DEFAULT 0,
    tax_rate FLOAT NOT NULL DEFAULT 0,
    paid_amount FLOAT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(patient_id) REFERENCES patients (id) ON DELETE CASCADE,
    FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL,
    FOREIGN KEY(record_id) REFERENCES medical_records (id) ON DELETE SET NULL
)
"""

_INVOICES_COPY_SQL = """
INSERT INTO _invoices_rebuild
    (id, patient_id, appointment_id, record_id, amount, description, status,
     payment_method, paid_at, insurer, policy_number,
     discount, tax_rate, paid_amount, created_at, updated_at)
SELECT id, patient_id,
       CASE WHEN appointment_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.id = i.appointment_id)
            THEN NULL ELSE appointment_id END,
       CASE WHEN record_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM medical_records m WHERE m.id = i.record_id)
            THEN NULL ELSE record_id END,
       amount, description, status, payment_method, paid_at, insurer, policy_number,
       COALESCE(discount, 0), COALESCE(tax_rate, 0),
       COALESCE(paid_amount, CASE WHEN status = 'PAID' THEN amount ELSE 0 END),
       created_at, updated_at
FROM invoices i
"""


def _rebuild_invoices():
    """إعادة بناء جدول الفواتير لإضافة مفاتيح FK + تنظيف الروابط المكسورة."""
    with engine.begin() as conn:
        conn.execute(text(_INVOICES_REBUILD_DDL))
        conn.execute(text(_INVOICES_COPY_SQL))
        conn.execute(text("DROP TABLE invoices"))
        conn.execute(text("ALTER TABLE _invoices_rebuild RENAME TO invoices"))
        conn.execute(text("CREATE INDEX ix_invoices_id ON invoices (id)"))


def ensure_columns():
    """ترحيل خفيف: إضافة الأعمدة المفقودة + ضمان مفاتيح FK في الفواتير.

    idempotent — آمن تشغيله في كل إقلاع، لا يحذف بيانات موجودة.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    added = set()  # (table, column) أُضيفت للتو

    # أعمدة عامة تُضاف بـ ALTER (جداول أخرى)
    with engine.begin() as conn:
        for table, columns in PENDING_COLUMNS.items():
            if table not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    added.add((table, name))

    # الفواتير: إعادة بناء إن كان عمود الربط بلا FK (أُضيف عبر ALTER سابقًا)
    if "invoices" in tables:
        fks = insp.get_foreign_keys("invoices")
        has_appt_fk = any(fk.get("referred_table") == "appointments" for fk in fks)
        if not has_appt_fk:
            _rebuild_invoices()

    # تعبئة المدفوع للفواتير القديمة المدفوعة عند إضافة العمود الجديد
    if ("invoices", "paid_amount") in added:
        from app.models import Invoice, InvoiceStatus  # استيراد متأخر لتفادي الدورة
        db = SessionLocal()
        try:
            q = db.query(Invoice).filter(Invoice.status == InvoiceStatus.PAID)
            for inv in q:
                inv.paid_amount = round(
                    (inv.amount or 0) - (inv.discount or 0)
                    + round(((inv.amount or 0) - (inv.discount or 0))
                            * (inv.tax_rate or 0) / 100.0, 2), 2)
            db.commit()
        finally:
            db.close()


# فهارس للأعمدة الأكثر فلترة/ترتيبًا — تُنشأ ما لم تكن موجودة (idempotent)
INDEXES = {
    "appointments": ["appointment_date", "patient_id", "doctor_id", "status"],
    "invoices": ["patient_id", "status", "appointment_id"],
    "medical_records": ["patient_id", "doctor_id"],
    "attachments": ["patient_id", "record_id"],
    "notifications": ["is_read", "appointment_id", "patient_id", "prescription_id"],
    "lab_orders": ["patient_id", "status"],
    "dispenses": ["patient_id", "medication_id", "created_at", "prescription_id"],
    "stock_movements": ["medication_id", "created_at"],
    "prescriptions": ["patient_id", "status", "doctor_id"],
    "prescription_items": ["prescription_id", "medication_id"],
    "payroll": ["staff_id", "period"],
    "staff_documents": ["staff_id", "uploaded_at"],
    "audit_logs": ["created_at", "username"],
    "patients": ["national_id"],
    "service_requests": ["service_type", "patient_id", "status", "created_at"],
    "nursing_tasks": ["patient_id", "department_id", "status", "due_at"],
    "surgeries": ["patient_id", "surgeon_id", "status", "scheduled_at"],
    "admissions": ["patient_id", "bed_id", "status", "admission_date"],
    "blood_units": ["blood_group", "status", "expiry_date"],
    "maintenance_orders": ["status", "priority", "scheduled_at"],
    "sterilization_cycles": ["status", "started_at"],
    "safety_events": ["category", "status", "created_at"],
    "physiotherapy_cases": ["patient_id", "status", "therapist_id"],
    "nutrition_cases": ["patient_id", "status"],
    "emergency_cases": ["patient_id", "status", "arrival_at"],
    "home_health_cases": ["patient_id", "status", "next_visit_at"],
    "wellness_programs": ["patient_id", "status"],
    "housekeeping_tasks": ["room_number", "status", "priority"],
    "vital_signs": ["patient_id", "recorded_at"],
    "insurance_claims": ["patient_id", "status", "invoice_id"],

    "budgets": ["fiscal_year", "department"],
}


def ensure_indexes():
    """إنشاء الفهارس الناقصة على الجداول الساخنة (CREATE INDEX IF NOT EXISTS).

    يعمل على SQLite وPostgreSQL معًا، ويتجاوز أي جدول/عمود غير موجود
    بدل أن يفشل الإقلاع — idempotent في كل بدء تشغيل.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, columns in INDEXES.items():
            if table not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col in columns:
                if col not in have:
                    continue
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} "
                    f"ON {table} ({col})"))


@contextmanager
def migrations_lock():
    """قفل يمنع تصادم الترحيل بين عمّال uvicorn المتعددين (--workers).

    بدونه ينافس كل عامل على create_all/ensure_columns/ensure_indexes،
    ويفشل أحدهم على PostgreSQL بـ«CREATE TYPE ... already exists» فيفشل
    إقلاعه ويُسقط الأب كله (حدث فعليًا في مكدّس الإنتاج).
    — PostgreSQL: advisory lock على الجلسة (يُ解放 تلقائيًا عند موت العملية).
    — SQLite: ملف قفل ذرّي (O_EXCL) مع سرقة بعد انتظار120 ثانية.
    """
    if _IS_SQLITE:
        lock_path = (engine.url.database or ":memory:") + ".migrate.lock"
        deadline = time.time() + 120
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                break
            except FileExistsError:
                if time.time() > deadline:
                    # قفل مهجور (عملية ماتت أثناء الترحيل) — اسحبه وأعد المحاولة
                    try:
                        os.remove(lock_path)
                    except OSError:
                        pass
                    try:
                        fd = os.open(
                            lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd)
                        break
                    except FileExistsError:
                        pass
                time.sleep(0.2)
        try:
            yield
        finally:
            try:
                os.remove(lock_path)
            except OSError:
                pass
    else:
        conn = engine.connect()
        try:
            conn.execute(text("SELECT pg_advisory_lock(8152001)"))
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(8152001)"))
        finally:
            conn.close()


def acquire_leader_lease():
    """تأجير قيادة المهام الخلفية لعامل واحد — يرجع دالة الإرجاع أو None.

    إن عادت دالة: هذا العامل هو «القائد» ويبدأ حلقات التذكير/النسخ؛
    None = تابع (لا يشغّل الحلقات — تجنب التكرار مع عدة عمّال).
    — PostgreSQL: pg_try_advisory_lock على جلسة مثبتة (آمن مع إعادة التشغيل).
    — SQLite: ملف قفل ذرّي مع سرقة القفل الأقدم من6 ساعات (best-effort).
    """
    if _IS_SQLITE:
        lock_path = (engine.url.database or ":memory:") + ".leader"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > 6 * 3600:
                    os.remove(lock_path)
                    fd = os.open(
                        lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                else:
                    return None
            except (OSError, FileExistsError):
                return None

        def _release():
            try:
                os.remove(lock_path)
            except OSError:
                pass

        return _release

    if "postgres" not in DATABASE_URL:
        return None  # محرك آخر: لا قفل — الحلقات تعمل كBehaviour اليوم

    conn = engine.connect()
    got = conn.execute(text("SELECT pg_try_advisory_lock(8152002)")).scalar()
    if not got:
        conn.close()
        return None

    def _release():
        try:
            conn.execute(text("SELECT pg_advisory_unlock(8152002)"))
        except Exception:  # noqa: BLE001 — الجلسة تُغلق على أي حال
            pass
        finally:
            conn.close()

    return _release


def get_db():
    """Dependency لحصول كل endpoint على جلسة قاعدة بيانات"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()