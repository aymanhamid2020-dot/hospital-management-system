import os
from dotenv import load_dotenv

load_dotenv()

# إعدادات قاعدة البيانات
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./hospital.db"
)

# إعدادات CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

# إعدادات التطبيق
APP_NAME = os.getenv("APP_NAME", "Hospital Management System")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# إعدادات الأمان
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# إعدادات البريد SMTP
# MAIL_ENABLED=false → يُحفظ البريد في مجلد outbox/ بدل الإرسال (وضع تجريبي/تطوير)
MAIL_ENABLED = os.getenv("MAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER or "noreply@hospital.com")
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"

# مهمة التذكير بالمواعيد (بالدقائق — 0 لتعطيلها)
REMINDER_INTERVAL_MINUTES = int(os.getenv("REMINDER_INTERVAL_MINUTES", "5"))
REMINDER_HOURS_BEFORE = int(os.getenv("REMINDER_HOURS_BEFORE", "24"))

# تنبيه الوصفات المعلّقة: وصفة PENDING أقدم من هذه الساعات → إشعار
# (0 لتعطيل التنبيه) — يعمل ضمن حلقة التذكير نفسها
STALE_RX_HOURS = int(os.getenv("STALE_RX_HOURS", "24"))