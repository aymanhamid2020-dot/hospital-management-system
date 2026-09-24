from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

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


def get_db():
    """Dependency لحصول كل endpoint على جلسة قاعدة بيانات"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()