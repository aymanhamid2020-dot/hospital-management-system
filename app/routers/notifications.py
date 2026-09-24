from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Notification, User
from app.schemas import NotificationInDB
from app.auth import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=List[NotificationInDB], summary="قائمة الإشعارات")
async def list_notifications(
    unread_only: bool = Query(False, description="غير المقروءة فقط"),
    limit: int = Query(50, ge=1, le=200, description="الحد الأقصى"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/unread-count", summary="عدد غير المقروءة")
async def unread_count(db = Depends(get_db), _ = Depends(get_current_user)):
    from sqlalchemy import func
    count = db.query(func.count(Notification.id)).filter(Notification.is_read.is_(False)).scalar() or 0
    return {"unread": count}


@router.put("/{notif_id}/read", response_model=NotificationInDB, summary="تعليم كمقروء")
async def mark_read(
    notif_id: int,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    n = db.query(Notification).filter(Notification.id == notif_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


@router.put("/read-all", summary="تعليم الكل كمقروء")
async def mark_all_read(db = Depends(get_db), _ = Depends(get_current_user)):
    db.query(Notification).filter(Notification.is_read.is_(False)).update({"is_read": True})
    db.commit()
    return {"message": "تم تعليم كل الإشعارات كمقروءة"}


@router.delete("/{notif_id}", status_code=204, summary="حذف إشعار")
async def delete_notification(
    notif_id: int,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    n = db.query(Notification).filter(Notification.id == notif_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    db.delete(n)
    db.commit()
    return None
