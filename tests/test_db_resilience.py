"""صلابة قاعدة البيانات: WAL + توازن الاتصالات + الفهارس + اتساق النسخ تحت WAL.

حالات تمنع تكرار حادثتَين حقيقيتين:
1) QueuePool limit ... reached وتجمّد /health — عولج بـ WAL + بركة 20+30.
2) نسخة احتياطية بـ shutil.copy كانت تفوّق صفوف WAL الحديثة فيرفض الاستعادة —
   عُوّضت بـ sqlite backup API.
"""
import os
import sqlite3
import uuid

from sqlalchemy import text

from app.database import engine


def test_journal_mode_wal(client):
    """SQLite في وضع WAL — القرّاء لا يتوقفون خلف الكاتب (سبب أزمة الحمل)."""
    assert engine.url.get_backend_name() == "sqlite"
    con = sqlite3.connect(engine.url.database)
    try:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()
    assert mode.lower() == "wal"


def test_connection_pool_tuned(client):
    """بركة اتصالات موسّعة (20+30) — تجاوزها كان ينتج TimeoutError تحت الحمل."""
    assert engine.pool.size() == int(os.getenv("DB_POOL_SIZE", "20"))
    assert engine.pool._max_overflow == int(
        os.getenv("DB_POOL_MAX_OVERFLOW", "30"))


def test_indexes_created_on_hot_tables(client):
    """فهارس الجداول الساخنة أُنشئت عند الإقلاع عبر ensure_indexes()."""
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'"))}
    for iname in (
        "ix_appointments_appointment_date",
        "ix_invoices_patient_id",
        "ix_medical_records_patient_id",
        "ix_lab_orders_status",
        "ix_dispenses_medication_id",
        "ix_notifications_is_read",
        "ix_stock_movements_medication_id",
        "ix_audit_logs_created_at",
        "ix_payroll_staff_id",
        "ix_attachments_patient_id",
        "ix_patients_national_id",
    ):
        assert iname in names, iname


def test_ensure_indexes_idempotent(client):
    """استدعاء مزدوج لـ ensure_indexes() لا يفشل (CREATE INDEX IF NOT EXISTS)."""
    from app.database import ensure_indexes
    ensure_indexes()
    ensure_indexes()


def test_backup_under_wal_contains_latest_rows(client, admin):
    """تحت WAL: نسخة sqlite backup API تحوي أحدث صفوف + quick_check ok ثم تنظيف."""
    marker = f"wal_marker_{uuid.uuid4().hex[:8]}@t.com"
    p = client.post("/patients/", headers=admin, json={
        "full_name": "علامة WAL", "date_of_birth": "1995-05-05",
        "gender": "ذكر", "phone": "0555000111", "email": marker})
    assert p.status_code == 200, p.text
    pid = p.json()["id"]
    try:
        rb = client.post("/backup", headers=admin)
        assert rb.status_code == 200, rb.text
        path = rb.json()["path"]
        try:
            con = sqlite3.connect(path)
            try:
                qc = con.execute("PRAGMA quick_check").fetchone()[0]
                found = con.execute(
                    "SELECT COUNT(*) FROM patients WHERE email = ?",
                    (marker,)).fetchone()[0]
            finally:
                con.close()
            assert qc == "ok", qc
            assert found == 1, "الصف الحديث (WAL) غائب عن النسخة"
        finally:
            if os.path.exists(path):
                os.remove(path)
    finally:
        client.delete(f"/patients/{pid}", headers=admin)
