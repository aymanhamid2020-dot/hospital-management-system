"""إحصائيات مشتركة: TAT، أكثر الفحوصات طلبًا، إيرادات — للمختبر والأشعة."""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import LabOrder, LabStatus, TestType, User
from app.schemas import LabOrderInDB

router = APIRouter(prefix="/shared/stats", tags=["Shared Statistics"])


@router.get("/tat", summary="متوسط زمن الإنجاز (TAT) بالساعات")
async def tat_stats(
    from_date: Optional[datetime] = Query(None, description="من تاريخ"),
    to_date: Optional[datetime] = Query(None, description="إلى تاريخ"),
    test_type: Optional[TestType] = Query(None, description="lab | radiology"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    متوسط زمن الإنجاز (Turn-Around Time) بين ordered_at و result_at
    للطلبات التي اكتملت (result_at غير فارغ).
    """
    q = db.query(LabOrder).filter(LabOrder.result_at.isnot(None))
    if from_date:
        q = q.filter(LabOrder.ordered_at >= from_date)
    if to_date:
        q = q.filter(LabOrder.ordered_at <= to_date)
    if test_type:
        q = q.filter(LabOrder.test_type == test_type)

    orders = q.all()
    if not orders:
        return {"count": 0, "avg_hours": 0, "median_hours": 0,
                "min_hours": 0, "max_hours": 0, "p95_hours": 0}

    tats = [(o.result_at - o.ordered_at).total_seconds() / 3600 for o in orders]
    tats.sort()
    n = len(tats)
    median = tats[n // 2] if n % 2 == 1 else (tats[n // 2 - 1] + tats[n // 2]) / 2
    p95_idx = min(int(n * 0.95), n - 1)
    p95 = tats[p95_idx]

    return {
        "count": n,
        "avg_hours": round(sum(tats) / n, 2),
        "median_hours": round(median, 2),
        "min_hours": round(tats[0], 2),
        "max_hours": round(tats[-1], 2),
        "p95_hours": round(p95, 2),
    }


@router.get("/top-tests", summary="أكثر الفحوصات طلبًا")
async def top_tests(
    limit: int = Query(10, ge=1, le=50, description="أعلى N"),
    from_date: Optional[datetime] = Query(None, description="من تاريخ"),
    to_date: Optional[datetime] = Query(None, description="إلى تاريخ"),
    test_type: Optional[TestType] = Query(None, description="lab | radiology"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """أكثر الفحوصات طلبًا مع عدد الطلبات لكل منها."""
    q = db.query(LabOrder)
    if from_date:
        q = q.filter(LabOrder.ordered_at >= from_date)
    if to_date:
        q = q.filter(LabOrder.ordered_at <= to_date)
    if test_type:
        q = q.filter(LabOrder.test_type == test_type)

    from collections import Counter
    counter = Counter()
    for o in q.all():
        counter[o.test_name] += 1

    top = counter.most_common(limit)
    return [{"test_name": name, "count": count} for name, count in top]


@router.get("/revenue", summary="إيرادات المختبر والأشعة")
async def revenue_stats(
    from_date: Optional[datetime] = Query(None, description="من تاريخ"),
    to_date: Optional[datetime] = Query(None, description="إلى تاريخ"),
    test_type: Optional[TestType] = Query(None, description="lab | radiology"),
    status_filter: Optional[LabStatus] = Query(None, description="فلترة بالحالة"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    إجمالي الإيرادات + تفصيل حسب النوع/الحالة.
    """
    q = db.query(LabOrder)
    if from_date:
        q = q.filter(LabOrder.ordered_at >= from_date)
    if to_date:
        q = q.filter(LabOrder.ordered_at <= to_date)
    if test_type:
        q = q.filter(LabOrder.test_type == test_type)
    if status_filter:
        q = q.filter(LabOrder.status == status_filter)

    orders = q.all()
    total = sum(o.price or 0 for o in orders)

    by_type = {"lab": 0.0, "radiology": 0.0}
    by_status = {}
    for o in orders:
        by_type[o.test_type.value] = by_type.get(o.test_type.value, 0) + (o.price or 0)
        by_status[o.status.value] = by_status.get(o.status.value, 0) + (o.price or 0)

    return {
        "total_revenue": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "by_status": {k: round(v, 2) for k, v in by_status.items()},
        "orders_count": len(orders),
    }


@router.get("/delivery", summary="إحصائيات التسليم")
async def delivery_stats(
    from_date: Optional[datetime] = Query(None, description="من تاريخ"),
    to_date: Optional[datetime] = Query(None, description="إلى تاريخ"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إحصائيات قنوات التسليم (pdf, portal, whatsapp, sms, email)."""
    q = db.query(LabOrder).filter(LabOrder.delivered_at.isnot(None))
    if from_date:
        q = q.filter(LabOrder.delivered_at >= from_date)
    if to_date:
        q = q.filter(LabOrder.delivered_at <= to_date)

    orders = q.all()
    if not orders:
        return {"total_delivered": 0, "by_channel": {}}

    from collections import Counter
    ch = Counter(o.delivery_channel or "pdf" for o in orders)
    return {
        "total_delivered": len(orders),
        "by_channel": dict(ch),
    }


from collections import Counter