"""إرسال البريد الإلكتروني — SMTP حقيقي أو وضع صندوق وارد تجريبي.

عندما MAIL_ENABLED=false (الافتراضي) يُحفظ كل بريد كملف .eml في مجلد outbox/
للمراجعة أثناء التطوير بدون خادم بريد حقيقي.
"""
import os
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

from app.config import (
    MAIL_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USER,
    SMTP_PASSWORD, MAIL_FROM, MAIL_USE_TLS,
)

OUTBOX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outbox")


def _build_message(to: str, subject: str, body: str, html: bool = False) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr(("نظام إدارة المستشفيات", MAIL_FROM))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
    if html:
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)
    return msg


def _save_to_outbox(msg: EmailMessage) -> str:
    """حفظ البريد في outbox/ (وضع التطوير)."""
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_to = (msg["To"] or "unknown").replace("@", "_at_").replace("/", "_")
    path = os.path.join(OUTBOX_DIR, f"{timestamp}_{safe_to}.eml")
    with open(path, "wb") as f:
        f.write(bytes(msg))
    return path


def _send_smtp(msg: EmailMessage) -> None:
    """إرسال فعلي عبر SMTP."""
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        if MAIL_USE_TLS:
            server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def send_email(to: str, subject: str, body: str, html: bool = False) -> dict:
    """إرسال بريد — يرجع حالة الإرسال أو المسار في وضع outbox.

    لا يرمي استثناءات — يرجع dict فيها success/error لتسهيل التسجيل.
    """
    if not to:
        return {"success": False, "error": "لا يوجد بريد مُستلم"}

    msg = _build_message(to, subject, body, html)

    if not MAIL_ENABLED:
        try:
            path = _save_to_outbox(msg)
            return {"success": True, "mode": "outbox", "path": path}
        except OSError as e:
            return {"success": False, "error": str(e)}

    try:
        _send_smtp(msg)
        return {"success": True, "mode": "smtp"}
    except Exception as e:  # ن errors أي خطأ شبكة/مصادقة
        return {"success": False, "error": str(e)}


def send_email_async(to: str, subject: str, body: str, html: bool = False) -> threading.Thread:
    """إرسال بريد في خيط منفصل (لا يحجب الاستجابة)."""
    t = threading.Thread(target=send_email, args=(to, subject, body, html), daemon=True)
    t.start()
    return t


# ===== قوالب رسائل جاهزة =====
def appointment_created_email(patient_name: str, doctor_name: str, when: str) -> tuple[str, str]:
    subject = "تأكيد حجز موعد — نظام إدارة المستشفيات"
    body = f"""مرحبًا {patient_name}،

تم حجز موعدك بنجاح:

  👨‍⚕️ الطبيب: {doctor_name}
  📅 التاريخ والوقت: {when}

يرجى الحضور قبل الموعد بـ 15 دقيقة مع الهوية الشخصية.

مع تحيات فريق المستشفى
"""
    return subject, body


def appointment_reminder_email(patient_name: str, doctor_name: str, when: str) -> tuple[str, str]:
    subject = "تذكير بموعدك غدًا — نظام إدارة المستشفيات"
    body = f"""مرحبًا {patient_name}،

نذكّرك بموعدك القادم:

  👨‍⚕️ الطبيب: {doctor_name}
  📅 التاريخ والوقت: {when}

إذا تعذّر حضورك، يرجى إلغاء الموعد مسبقًا.

مع تحيات فريق المستشفى
"""
    return subject, body
