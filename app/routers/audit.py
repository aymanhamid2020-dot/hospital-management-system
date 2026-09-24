from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogInDB

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit"],
    dependencies=[Depends(require_admin)],  # سجل التدقيق للمدير فقط
)


@router.get("/", response_model=List[AuditLogInDB], summary="عرض سجل التدقيق")
async def list_audit_logs(
    username: Optional[str] = Query(None, description="فلترة حسب المستخدم"),
    method: Optional[str] = Query(None, description="POST / PUT / DELETE"),
    limit: int = Query(100, ge=1, le=500, description="الحد الأقصى للسجلات"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """آخر العمليات التعديلية في النظام (من الـ middleware) — للمدير فقط"""
    q = db.query(AuditLog)
    if username:
        q = q.filter(AuditLog.username == username)
    if method:
        q = q.filter(AuditLog.method == method.upper())
    return q.order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/stats", summary="إحصاءات استخدام النظام")
async def audit_stats(
    days: int = Query(7, ge=1, le=90, description="نافذة الأيام للتجميعات"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تحليل استخدام النظام من سجل التدقيق (المدير فقط): توزيع الطرق،
    أكثر المستخدمين نشاطًا، أكثر المسارات طلبًا (مطبّعة)، الأخطاء الأخيرة،
    ومحاولات الدخول الفاشلة."""
    import re
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func

    # التوقيت المخزّن في القواعد SQLite/Postgres هنا بلا منطقة زمنية (UTC)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    total = db.query(func.count(AuditLog.id)).scalar() or 0
    recent = (db.query(func.count(AuditLog.id))
              .filter(AuditLog.created_at >= since).scalar() or 0)

    by_method = dict(
        db.query(AuditLog.method, func.count(AuditLog.id))
        .group_by(AuditLog.method).all()
    )

    top_users = [
        {"username": u or "anonymous", "count": c}
        for u, c in (db.query(AuditLog.username, func.count(AuditLog.id))
                     .filter(AuditLog.created_at >= since)
                     .group_by(AuditLog.username)
                     .order_by(func.count(AuditLog.id).desc())
                     .limit(10).all())
    ]

    # تطبيع المسارات: /patients/123?page=2 ← /patients/:id
    norm: dict = {}
    for path, c in (db.query(AuditLog.path, func.count(AuditLog.id))
                    .filter(AuditLog.created_at >= since)
                    .group_by(AuditLog.path).all()):
        key = re.sub(r"/\d+", "/:id", (path or "").split("?")[0])[:120] or "/"
        norm[key] = norm.get(key, 0) + c
    top_paths = [{"path": p, "count": c}
                 for p, c in sorted(norm.items(), key=lambda kv: -kv[1])[:10]]

    recent_errors = [
        {"method": r.method, "path": r.path, "status_code": r.status_code,
         "time": f"{r.created_at:%Y-%m-%d %H:%M}" if r.created_at else ""}
        for r in (db.query(AuditLog)
                  .filter(AuditLog.status_code >= 400,
                          AuditLog.created_at >= since)
                  .order_by(AuditLog.created_at.desc()).limit(10).all())
    ]

    # محاولات الدخول الفاشلة (POST /auth/login بحالة ≥400 في سجل التدقيق)
    since_24 = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    lf_q = (db.query(AuditLog)
            .filter(AuditLog.path.like("/auth/login%"),
                    AuditLog.status_code >= 400))
    login_failures = {
        "total": lf_q.count(),
        "last_24h": lf_q.filter(AuditLog.created_at >= since_24).count(),
        "recent": [
            {"time": f"{r.created_at:%Y-%m-%d %H:%M}" if r.created_at else "",
             "username": r.username or "anonymous",
             "status_code": r.status_code}
            for r in (lf_q.order_by(AuditLog.created_at.desc()).limit(5).all())
        ],
    }

    return {
        "window_days": days,
        "total": total,
        "recent": recent,
        "by_method": by_method,
        "top_users": top_users,
        "top_paths": top_paths,
        "recent_errors": recent_errors,
        "login_failures": login_failures,
    }
