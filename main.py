from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
import os

from app.database import Base, engine, SessionLocal, get_db
from app import models  # noqa: F401 - لتسجيل الجداول
from app.auth import hash_password


def seed_admin():
    """إنشاء حساب مدير افتراضي عند أول تشغيل."""
    from app.models import User, UserRole
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.role == UserRole.ADMIN).first():
            admin = User(
                username="admin",
                email="admin@hospital.com",
                full_name="مدير النظام",
                role=UserRole.ADMIN,
                hashed_password=hash_password("admin123"),
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # إنشاء الجداول + ترحيل الأعمدة الجديدة عند بدء التشغيل
    from app.database import ensure_columns
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    seed_admin()

    # مهمة التذكير والنسخ التلقائي في الخلفية
    import asyncio
    from app.tasks import backup_loop, reminder_loop
    task = asyncio.create_task(reminder_loop())
    backup_task = asyncio.create_task(backup_loop())
    yield
    task.cancel()
    backup_task.cancel()

# قراءة إعدادات CORS من المتغيرات البيئية
cors_origins = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else ["*"]

app = FastAPI(
    title="نظام إدارة المستشفيات والعيادات",
    description="نظام شامل لإدارة المستشفيات والعيادات الطبية",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# إضافة Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مسارات الترحيب
INDEX_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>نظام إدارة المستشفيات والعيادات</title>
<style>
  body { font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: linear-gradient(135deg,#667eea,#764ba2); margin:0; padding:40px; min-height:100vh; color:#333; }
  .card { background:#fff; max-width:760px; margin:auto; border-radius:16px; padding:40px; box-shadow:0 20px 60px rgba(0,0,0,.3); text-align:center; }
  h1 { color:#2c7be5; margin-top:0; font-size:28px; }
  .version { color:#888; font-size:14px; }
  .links { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin-top:30px; }
  a.btn { display:block; padding:16px; background:#f0f6ff; color:#2c7be5; text-decoration:none; border-radius:10px; font-weight:bold; border:2px solid #dbeafe; transition:.2s; }
  a.btn:hover { background:#2c7be5; color:#fff; border-color:#2c7be5; }
  .creds { background:#fff8e1; border:1px dashed #f5b301; border-radius:10px; padding:14px; margin-top:26px; font-size:14px; direction:ltr; }
  .status { margin-top:18px; font-size:14px; color:#28a745; font-weight:bold; }
</style>
</head>
<body>
<div class="card">
  <h1>🏥 نظام إدارة المستشفيات والعيادات</h1>
  <div class="version">FastAPI — الإصدار 1.0.0</div>
    <div class="links">
    <a class="btn" href="/ui">🖥️ فتح لوحة التحكم</a>
    <a class="btn" href="/api/docs">📖 توثيق Swagger</a>
    <a class="btn" href="/api/redoc">📄 توثيق ReDoc</a>
    <a class="btn" href="/health">💚 فحص الحالة</a>
    <a class="btn" href="/status">🩺 حالة النظام (JSON)</a>
    <a class="btn" href="/monitor">📊 لوحة المراقبة</a>
    <a class="btn" href="/invoices/1/print">🖨️ طباعة فاتورة تجريبية</a>
  </div>
  <div class="creds">
    Default login:<br>
    <strong>admin</strong> / <strong>admin123</strong>
  </div>
  <div class="status">● System running</div>
</div>
</body>
</html>"""

from fastapi.responses import HTMLResponse


@app.get("/", tags=["عام"], response_class=HTMLResponse)
async def root():
    """صفحة ترحيب بروابط التوثيق"""
    return INDEX_HTML


@app.get("/api/info", tags=["عام"])
async def root_json():
    return {"message": "مرحباً بك في نظام إدارة المستشفيات والعيادات", "version": "1.0.0"}

@app.get("/health", tags=["عام"])
async def health_check():
    return {"status": "healthy", "service": "hospital-management-system"}


@app.get("/status", tags=["عام"], summary="حالة النظام العامة (JSON للمراقبة)")
async def system_status(db: Session = Depends(get_db)):
    """فحص مراقبة **دون توكن**: الإصدار + محرك القاعدة واتصالها + عدد السجلات"""
    from datetime import date, datetime, time as _time, timedelta, timezone
    from sqlalchemy import func, text
    from app.config import (APP_NAME, APP_VERSION, REMINDER_HOURS_BEFORE,
                            REMINDER_INTERVAL_MINUTES)
    from app.models import (Patient, Doctor, Appointment, Invoice, Medication,
                            LabOrder, LabStatus, InvoiceStatus)

    try:
        db.execute(text("SELECT 1"))
        connected = True
    except Exception:
        connected = False

    counts = {"patients": 0, "doctors": 0, "appointments": 0, "invoices": 0}
    alerts = {"low_stock": 0, "lab_pending": 0, "appointments_today": 0,
              "unpaid_invoices": 0, "expired_meds": 0, "expiring_meds": 0}
    if connected:
        counts = {
            "patients": db.query(func.count(Patient.id)).scalar() or 0,
            "doctors": db.query(func.count(Doctor.id)).scalar() or 0,
            "appointments": db.query(func.count(Appointment.id)).scalar() or 0,
            "invoices": db.query(func.count(Invoice.id)).scalar() or 0,
        }
        today_start = datetime.combine(date.today(), _time.min)
        tomorrow_start = datetime.combine(
            date.today() + timedelta(days=1), _time.min)
        alerts = {
            # أدوية بلغت أو نزلت تحت حد التنبيه
            "low_stock": db.query(func.count(Medication.id))
            .filter(Medication.quantity <= Medication.min_quantity)
            .scalar() or 0,
            # طلبات مختبر مسجّلة أو قيد التنفيذ (بلا نتيجة جاهزة بعد)
            "lab_pending": db.query(func.count(LabOrder.id))
            .filter(LabOrder.status.in_([LabStatus.PENDING, LabStatus.IN_PROGRESS]))
            .scalar() or 0,
            "appointments_today": db.query(func.count(Appointment.id))
            .filter(Appointment.appointment_date >= today_start,
                    Appointment.appointment_date < tomorrow_start)
            .scalar() or 0,
            "unpaid_invoices": db.query(func.count(Invoice.id))
            .filter(Invoice.status != InvoiceStatus.PAID)
            .scalar() or 0,
            # أدوية منتهية الصلاحية
            "expired_meds": db.query(func.count(Medication.id))
            .filter(Medication.expiry_date.isnot(None),
                    Medication.expiry_date < datetime.now())
            .scalar() or 0,
            # أدوية تنتهي خلال 30 يومًا
            "expiring_meds": db.query(func.count(Medication.id))
            .filter(Medication.expiry_date.isnot(None),
                    Medication.expiry_date >= datetime.now(),
                    Medication.expiry_date < datetime.now() + timedelta(days=30))
            .scalar() or 0,
        }

    return {
        "status": "ok" if connected else "degraded",
        "service": APP_NAME,
        "version": APP_VERSION,
        "database": {"engine": engine.url.get_backend_name(), "connected": connected},
        "counts": counts,
        "alerts": alerts,
        "reminders": {
            "enabled": REMINDER_INTERVAL_MINUTES > 0,
            "interval_minutes": REMINDER_INTERVAL_MINUTES,
            "hours_before": REMINDER_HOURS_BEFORE,
        },
        "backups": {
            "automatic": bool(engine.url.get_backend_name() == "sqlite"),
            "interval_hours": float(os.getenv("BACKUP_INTERVAL_HOURS", "24")),
            "retention": int(os.getenv("BACKUP_RETENTION", "7")),
        },
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

# تضمين المحاور
from app.routers.patients import router as patients_router
from app.routers.doctors import router as doctors_router
from app.routers.appointments import router as appointments_router
from app.routers.staff import router as staff_router
from app.routers.invoices import router as invoices_router
from app.routers.reports import router as reports_router
from app.routers.auth import router as auth_router
from app.routers.departments import router as departments_router
from app.routers.beds import router as beds_router
from app.routers.dashboard import router as dashboard_router
from app.routers.medical_records import router as medical_records_router
from app.routers.backup import router as backup_router
from app.routers.attachments import router as attachments_router
from app.routers.notifications import router as notifications_router
from app.routers.lab_orders import router as lab_orders_router
from app.routers.pharmacy import medications_router, dispenses_router
from app.routers.payroll import router as payroll_router
from app.routers.audit import router as audit_router
from app.routers.accounts import router as accounts_router
from app.routers.inventory import router as inventory_router

app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(doctors_router)
app.include_router(appointments_router)
app.include_router(staff_router)
app.include_router(invoices_router)
app.include_router(reports_router)
app.include_router(departments_router)
app.include_router(beds_router)
app.include_router(dashboard_router)
app.include_router(medical_records_router)
app.include_router(backup_router)
app.include_router(attachments_router)
app.include_router(notifications_router)
app.include_router(lab_orders_router)
app.include_router(medications_router)
app.include_router(dispenses_router)
app.include_router(payroll_router)
app.include_router(audit_router)
app.include_router(accounts_router)
app.include_router(inventory_router)


# ===== سجل التدقيق (يُسجّل كل عملية تعديلية) =====
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_audit_log = logging.getLogger("hms.audit")


class AuditMiddleware(BaseHTTPMiddleware):
    """تسجيل عمليات الإنشاء/التعديل/الحذف في جدول audit_logs دون تعطيل الطلب."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in _AUDIT_METHODS:
            return await call_next(request)

        username, user_id = None, None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            try:
                import jwt as _jwt
                from app.config import SECRET_KEY, ALGORITHM

                payload = _jwt.decode(
                    auth_header[7:], SECRET_KEY, algorithms=[ALGORITHM]
                )
                user_id = int(payload["sub"]) if payload.get("sub") else None
                username = payload.get("username")
            except Exception:
                pass

        response = await call_next(request)

        try:
            from app.models import AuditLog

            db = SessionLocal()
            try:
                db.add(AuditLog(
                    user_id=user_id,
                    username=username or "anonymous",
                    method=request.method,
                    path=request.url.path[:500],
                    status_code=response.status_code,
                ))
                db.commit()
            finally:
                db.close()
        except Exception as exc:  # السجل لا يُعطّل الطلب أبدًا
            _audit_log.warning("audit write failed: %s", exc)

        return response


app.add_middleware(AuditMiddleware)


class NoCacheUIMiddleware:
    """يمنع كاش المتصفح لملفات الواجهة حتى تظهر أي تعديلات فورًا."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/ui"):
            return await self.app(scope, receive, send)

        async def send_no_cache(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [(k, v) for k, v in headers
                           if k.lower() not in (b"cache-control", b"expires")]
                headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                message = dict(message, headers=headers)
            await send(message)

        return await self.app(scope, receive, send_no_cache)


app.add_middleware(NoCacheUIMiddleware)

# خدمة الواجهة الأمامية (SPA) على مسار /ui
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/ui", StaticFiles(directory=_static_dir, html=True), name="ui")


@app.get("/monitor", tags=["عام"], summary="لوحة المراقبة المرئية")
async def monitor_page():
    """صفحة مراقبة مرئية (دون توكن) — تعتمد على /status وتتحدث كل 15 ثانية"""
    from fastapi.responses import FileResponse
    path = os.path.join(_static_dir, "monitor.html")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="ملف اللوحة غير موجود")
    return FileResponse(path, media_type="text/html")