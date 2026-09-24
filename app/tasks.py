"""المهام الخلفية: تذكير بالمواعيد (إشعار داخلي + بريد + فوري) والنسخ التلقائي."""
import asyncio
import logging
from datetime import datetime, timedelta

from app.config import REMINDER_INTERVAL_MINUTES, REMINDER_HOURS_BEFORE, STALE_RX_HOURS

logger = logging.getLogger("hms.reminders")


def check_and_send_reminders() -> int:
    """فحص المواعيد القادمة وإنشاء التذكيرات — يرجع عدد التذكيرات الجديدة.

    تعمل مرة واحدة بشكل متزامن (مناسبة للاستدعاء من حلقة async عبر
    asyncio.to_thread أو اختبارات pytest المباشرة).
    """
    from app.database import SessionLocal
    from app.models import Appointment, Notification, AppointmentStatus
    from app.email_utils import send_email, appointment_reminder_email

    db = SessionLocal()
    try:
        now = datetime.now()
        window_end = now + timedelta(hours=REMINDER_HOURS_BEFORE)

        upcoming = (
            db.query(Appointment)
            .filter(
                Appointment.appointment_date >= now,
                Appointment.appointment_date <= window_end,
                Appointment.status.in_([
                    AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED
                ]),
            )
            .all()
        )

        sent = 0
        for appt in upcoming:
            # هل أُرسل تذكير من قبل لهذا الموعد؟
            already = (
                db.query(Notification)
                .filter(
                    Notification.appointment_id == appt.id,
                    Notification.type == "reminder",
                )
                .first()
            )
            if already:
                continue

            pat = appt.patient
            doc = appt.doctor
            when = f"{appt.appointment_date:%Y-%m-%d %H:%M}"

            db.add(Notification(
                type="reminder",
                title="تذكير بموعد قادم",
                message=f"موعد {pat.full_name if pat else '-'} مع {doc.full_name if doc else '-'} في {when}",
                appointment_id=appt.id,
                patient_id=appt.patient_id,
            ))
            db.commit()
            sent += 1

            # بريد التذكير (تعمل في خيط worker أصلاً عبر asyncio.to_thread)
            if pat and pat.email:
                subj, body = appointment_reminder_email(
                    pat.full_name if pat else "-",
                    doc.full_name if doc else "-", when)
                send_email(pat.email, subj, body)

            # إشعار فوري اختياري (تلغرام/ويبهوك) — لا يُصعّد أبدًا
            from app.notifier import notify
            notify("reminder",
                   f"تذكير موعد {when}: {pat.full_name if pat else '-'} "
                   f"مع {doc.full_name if doc else '-'}")

        if sent:
            logger.info(f"تم إنشاء {sent} تذكير جديد")
        return sent
    finally:
        db.close()


async def reminder_loop():
    """حلقة تعمل كل REMINDER_INTERVAL_MINUTES دقائق (0 = معطّلة).

    في كل دورة: تذكير المواعيد + تنبيه الوصفات المعلّقة (PENDING أقدم
    من STALE_RX_HOURS ساعة — 0 لتعطيل تنبيه الوصفات).
    """
    if REMINDER_INTERVAL_MINUTES <= 0:
        logger.info("مهمة التذكير معطّلة (REMINDER_INTERVAL_MINUTES=0)")
        return

    logger.info(
        f"بدء مهمة التذكير — كل {REMINDER_INTERVAL_MINUTES} دقيقة، "
        f"قبل الموعد بـ {REMINDER_HOURS_BEFORE} ساعة، "
        f"والوصفات المعلّقة بعد {STALE_RX_HOURS} ساعة"
    )
    while True:
        try:
            await asyncio.to_thread(check_and_send_reminders)
        except Exception:
            logger.exception("خطأ في مهمة التذكير")
        try:
            await asyncio.to_thread(notify_stale_prescriptions)
        except Exception:
            logger.exception("خطأ في تنبيه الوصفات المعلّقة")
        await asyncio.sleep(REMINDER_INTERVAL_MINUTES * 60)


def notify_stale_prescriptions() -> int:
    """تنبيه بالوصفات المعلّقة (PENDING أقدم من STALE_RX_HOURS ساعة).

    ينشئ إشعارًا داخليًا واحدًا لكل وصفة معلّقة (مرتبط بـ prescription_id
    لمنع التكرار عند كل دورة) + إشعار فوري اختياري مجمّع — يرجع عدد
    التنبيهات الجديدة. تعمل مرة واحدة متزامنة (مناسبة للاستدعاء من
    asyncio.to_thread أو اختبارات pytest المباشرة).
    """
    if STALE_RX_HOURS <= 0:
        return 0

    from app.database import SessionLocal
    from app.models import Notification, Prescription

    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(hours=STALE_RX_HOURS)
        stale = (
            db.query(Prescription)
            .filter(
                Prescription.status == "PENDING",
                Prescription.created_at <= cutoff,
            )
            .all()
        )
        if not stale:
            return 0

        sent = 0
        for rx in stale:
            already = (
                db.query(Notification)
                .filter(Notification.prescription_id == rx.id)
                .first()
            )
            if already:
                continue
            pat = rx.patient
            age_h = int((datetime.now() - rx.created_at).total_seconds() // 3600) \
                if rx.created_at else STALE_RX_HOURS
            db.add(Notification(
                type="rx_stale",
                title="وصفة معلّقة",
                message=f"وصفة #{rx.id} للمريض "
                        f"{pat.full_name if pat else '-'} لم تُصرف منذ "
                        f"{age_h} ساعة — بانتظار الصرف",
                patient_id=rx.patient_id,
                prescription_id=rx.id,
            ))
            sent += 1
        db.commit()

        if sent:
            logger.info(f"تنبيهات وصفات معلّقة جديدة: {sent}")
            from app.notifier import notify
            notify("rx_stale", f"{sent} وصفة معلّقة بانتظار الصرف منذ "
                               f"{STALE_RX_HOURS} ساعة")
        return sent
    finally:
        db.close()


# ===== النسخ الاحتياطي المجدول التلقائي (SQLite فقط) =====
backup_logger = logging.getLogger("hms.backup")


def _sqlite_db_path():
    """مسار ملف قاعدة SQLite الحالية — None لو كانت القاعدة غير مدعومة."""
    import os
    from app.config import DATABASE_URL
    if not DATABASE_URL.startswith("sqlite:///"):
        return None
    path = DATABASE_URL.replace("sqlite:///", "", 1)
    return path if os.path.exists(path) else None


def prune_backups(backup_dir, keep=None):
    """تقليم النسخ الزائدة داخل مجلد backups — يرجع أسماء المحذوفات.

    الاحتفاظ بآخر ``BACKUP_RETENTION`` (7 افتراضيًا) من كل بادئة على حدة:
    ``hospital_*.db`` (الإنشاء اليدوي والفحوصات) و``auto_*.db`` (المجدول)؛
    وأي ملف آخر (مثل ملفات الاختبار ``_*.db``) لا يُمسّ إطلاقًا.
    الأسماء تحوي طابعًا زمنيًا بترتيب تصاعدي، فالفرز التنازلي = الأحدث أولًا.
    """
    import os
    if keep is None:
        keep = int(os.getenv("BACKUP_RETENTION", "7"))
    keep = max(int(keep), 1)
    if not os.path.isdir(backup_dir):
        return []
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return []
    deleted = []
    for prefix in ("hospital_", "auto_"):
        group = sorted(
            (n for n in names
             if n.startswith(prefix) and n.endswith(".db")),
            reverse=True,
        )
        for old in group[keep:]:
            try:
                os.remove(os.path.join(backup_dir, old))
                deleted.append(old)
            except OSError:
                pass
    if deleted:
        backup_logger.info(
            "تقليم النسخ: حُذف %d زائدًا (الاحتفاظ بآخر %d لكل بادئة)",
            len(deleted), keep)
    return deleted


def create_auto_backup(backup_dir=None, retention=None):
    """نسخة متسقة للقاعدة (sqlite backup API) + تقليم القديم — يرجع المسار.

    الافتراضي: مجلد backups/ بجانب المشروع والاحتفاظ بآخر BACKUP_RETENTION
    (7) نسخ من كل بادئة (auto_* المجدول وhospital_* اليدوي عبر prune_backups).
    ترجع None عند عدم الدعم أو المصدر غير الموجود.
    """
    import os
    import sqlite3
    import sys
    from datetime import datetime as _dt

    src = _sqlite_db_path()
    if not src:
        return None
    if backup_dir is None:
        if getattr(sys, "frozen", False):
            # نسخة سطح المكتب (PyInstaller): النسخ بجانب الملف التنفيذي
            backup_dir = os.path.join(os.path.dirname(sys.executable), "backups")
        else:
            # مجلد backups/ بجانب main.py (نفس منطق app/backup.py)
            backup_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
    if retention is None:
        retention = int(os.getenv("BACKUP_RETENTION", "7"))
    os.makedirs(backup_dir, exist_ok=True)

    now = _dt.now()
    dest = os.path.join(
        backup_dir, f"auto_{now:%Y%m%d_%H%M%S}_{now.microsecond:06d}.db")
    src_con = sqlite3.connect(src, timeout=10)
    try:
        dst_con = sqlite3.connect(dest)
        try:
            src_con.backup(dst_con)  # لقطة متزامنة وصالحة حتى أثناء الكتابة
        finally:
            dst_con.close()
    finally:
        src_con.close()

    # تقليم موحّد حسب السياسة (آخر N من hospital_* وآخر N من auto_*)
    prune_backups(backup_dir, retention)
    backup_logger.info("نسخة تلقائية محفوظة: %s", dest)
    return dest


async def backup_loop():
    """نسخة تلقائية كل BACKUP_INTERVAL_HOURS ساعة (0 = معطّلة) — SQLite فقط."""
    import os
    interval_h = float(os.getenv("BACKUP_INTERVAL_HOURS", "24"))
    if interval_h <= 0:
        backup_logger.info("النسخ التلقائي معطّل (BACKUP_INTERVAL_HOURS=0)")
        return
    if _sqlite_db_path() is None:
        backup_logger.info(
            "النسخ التلقائي متاح لـSQLite — على PostgreSQL استخدم pg_dump مجدولًا")
        return

    backup_logger.info(
        "بدء النسخ التلقائي — كل %s ساعة، الاحتفاظ بآخر %s نسخ",
        interval_h, os.getenv("BACKUP_RETENTION", "7"))
    while True:
        try:
            await asyncio.to_thread(create_auto_backup)
        except Exception:  # noqa: BLE001 — حلقة الخلفية لا تنهار أبدًا
            backup_logger.exception("فشل دورة النسخ التلقائي")
        await asyncio.sleep(interval_h * 3600)
