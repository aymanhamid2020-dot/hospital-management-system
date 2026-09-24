"""قسم المخزون — قائمة الأصناف بالقيمة والحالة، الملخّص، ودفتر الحركات.

الحركات تُقيَّد في جدول stock_movements من كل مسارات تعديل الكمية:
إنشاء دواء (رصيد افتتاحي)، تحديث كمية (جرد/تعديل)، صرف (out)،
توريد/جرد عبر هذا المحور (in/adjust) — فتكون الصورة موحّدة ومتسلسلة.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import Medication, StockMovement, User
from app.schemas import (
    AdjustIn, InventoryItem, InventorySummary, MedicationInDB, RestockIn, StockMovementInDB,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])

STATUSES = ("ok", "low", "out", "expiring", "expired")
MOVEMENT_TYPES = ("in", "out", "adjust")
DEFAULT_EXPIRING_DAYS = 30


def _days_to_expiry(med: Medication, now: datetime) -> Optional[int]:
    if not med.expiry_date:
        return None
    return (med.expiry_date - now).days


def _status_of(med: Medication, now: datetime, expiring_days: int) -> str:
    """حالة الصنف بترتيب أولوية: منتهي ← نافد ← قارب الانتهاء ← منخفض ← سليم."""
    days = _days_to_expiry(med, now)
    if days is not None and days < 0:
        return "expired"
    if med.quantity == 0:
        return "out"
    if days is not None and days <= expiring_days:
        return "expiring"
    if med.quantity <= med.min_quantity:
        return "low"
    return "ok"


def _item(med: Medication, now: datetime, expiring_days: int) -> InventoryItem:
    return InventoryItem(
        id=med.id,
        code=med.code,
        name=med.name,
        quantity=med.quantity,
        unit=med.unit,
        price=med.price,
        min_quantity=med.min_quantity,
        expiry_date=med.expiry_date,
        created_at=med.created_at,
        updated_at=med.updated_at,
        value=round(med.quantity * med.price, 2),
        status=_status_of(med, now, expiring_days),
        days_to_expiry=_days_to_expiry(med, now),
    )


def _check_expiring_days(expiring_days: int) -> None:
    if expiring_days < 0 or expiring_days > 365:
        raise HTTPException(
            status_code=400,
            detail="expiring_days يجب أن يكون بين 0 و365",
        )


@router.get("/", response_model=List[InventoryItem], summary="قائمة المخزون بالقيمة والحالة")
async def list_inventory(
    search: Optional[str] = Query(None, description="بحث بالاسم أو الرمز"),
    _status: Optional[str] = Query(
        None, alias="status", description="الحالة: ok|low|out|expiring|expired"),
    expiring_days: int = Query(
        DEFAULT_EXPIRING_DAYS, description="نافذة قرب الانتهاء بالأيام (0–365)"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """قائمة الأصناف مع قيمة محسوبة وحالة موحّدة (فلتر حالة خاطئ ⇒ 400)."""
    if _status is not None and _status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status يجب أن يكون ok أو low أو out أو expiring أو expired",
        )
    _check_expiring_days(expiring_days)
    q = db.query(Medication)
    if search:
        q = q.filter((Medication.name.contains(search)) | (Medication.code.contains(search)))
    now = datetime.now()
    items = [_item(m, now, expiring_days) for m in q.order_by(Medication.name.asc()).all()]
    if _status is not None:
        items = [i for i in items if i.status == _status]
    return items


@router.get("/summary", response_model=InventorySummary, summary="ملخّص حالة المخزون")
async def inventory_summary(
    expiring_days: int = Query(
        DEFAULT_EXPIRING_DAYS, description="نافذة قرب الانتهاء بالأيام (0–365)"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """عدّادات موحّدة: أصناف/قطع/قيمة + منخفض/نافد/منتهٍ/قارب الانتهاء."""
    _check_expiring_days(expiring_days)
    now = datetime.now()
    items = [_item(m, now, expiring_days) for m in db.query(Medication).all()]
    counts = {s: 0 for s in STATUSES}
    for i in items:
        counts[i.status] += 1
    return InventorySummary(
        items=len(items),
        units=sum(i.quantity for i in items),
        total_value=round(sum(i.value for i in items), 2),
        low=counts["low"],
        out=counts["out"],
        expired=counts["expired"],
        expiring=counts["expiring"],
        expiring_days=expiring_days,
    )


@router.get("/movements", response_model=List[StockMovementInDB], summary="دفتر حركات المخزون")
async def list_movements(
    medication_id: Optional[int] = Query(None, description="فلترة حسب الدواء"),
    movement_type: Optional[str] = Query(
        None, alias="type", description="نوع الحركة: in|out|adjust"),
    limit: int = Query(100, ge=1, le=500, description="أقصى عدد الحركات"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """حركات مرتبة تنازليًا (أحدث أولًا) — نوع خاطئ ⇒ 400."""
    if movement_type is not None and movement_type not in MOVEMENT_TYPES:
        raise HTTPException(status_code=400, detail="type يجب أن يكون in أو out أو adjust")
    q = db.query(StockMovement)
    if medication_id is not None:
        q = q.filter(StockMovement.medication_id == medication_id)
    if movement_type is not None:
        q = q.filter(StockMovement.type == movement_type)
    rows = q.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(limit).all()
    return [
        {
            "id": mv.id,
            "medication_id": mv.medication_id,
            "medication_name": mv.medication.name if mv.medication else "",
            "type": mv.type,
            "change": mv.change,
            "quantity_after": mv.quantity_after,
            "note": mv.note,
            "made_by": mv.made_by,
            "created_at": mv.created_at,
        }
        for mv in rows
    ]


@router.post("/{med_id}/restock", response_model=MedicationInDB, summary="توريد كمية إلى صنف")
async def restock(
    med_id: int,
    payload: RestockIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """زيادة كمية الصنف وتسجيل حركة in (كمية ≤ 0 ⇒ 422، صنف غير موجود ⇒ 404)."""
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="لا يوجد دواء بالمعرف المحدد")
    med.quantity += payload.quantity
    db.add(StockMovement(
        medication_id=med.id,
        type="in",
        change=payload.quantity,
        quantity_after=med.quantity,
        note=payload.note or "توريد",
        made_by=current_user.username,
    ))
    db.commit()
    db.refresh(med)
    return med


@router.put("/{med_id}/adjust", response_model=MedicationInDB, summary="جرد مطلق للكمية")
async def adjust(
    med_id: int,
    payload: AdjustIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """ضبط الكمية على قيمة جرد فعلية وتسجيل فرقها كحركة adjust."""
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="لا يوجد دواء بالمعرف المحدد")
    delta = payload.quantity - med.quantity
    med.quantity = payload.quantity
    db.add(StockMovement(
        medication_id=med.id,
        type="adjust",
        change=delta,
        quantity_after=med.quantity,
        note=payload.note or "جرد",
        made_by=current_user.username,
    ))
    db.commit()
    db.refresh(med)
    return med
