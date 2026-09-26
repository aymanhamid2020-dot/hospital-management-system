"""مخزون عام — مستلزمات طبية ومواد غير دوائية مع حد إعادة طلب."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import GeneralStockItem, GeneralStockMovement, StockDocLine, User
from app.schemas import (
    GeneralStockItemCreate,
    GeneralStockItemInDB,
    GeneralStockItemUpdate,
)

router = APIRouter(prefix="/general-stock", tags=["General Stock"])


@router.get("/", response_model=List[GeneralStockItemInDB], summary="قائمة مخزون عام")
async def list_general_stock(
    search: Optional[str] = Query(None, description="بحث بالاسم أو الرمز"),
    category: Optional[str] = Query(None, description="فلترة بالتصنيف"),
    warehouse: Optional[str] = Query(None, description="فلترة بالمخزن"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """قائمة أصناف المخزون العام مع فلاتر اختيارية."""
    q = db.query(GeneralStockItem)
    if search:
        q = q.filter((GeneralStockItem.name.contains(search)) | (GeneralStockItem.code.contains(search)))
    if category:
        q = q.filter(GeneralStockItem.category == category)
    if warehouse:
        q = q.filter(GeneralStockItem.warehouse == warehouse)
    return q.order_by(GeneralStockItem.name.asc()).all()


@router.post("/", response_model=GeneralStockItemInDB, status_code=201, summary="إضافة صنف مخزون عام")
async def create_general_stock(
    payload: GeneralStockItemCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """إضافة صنف جديد للمخزون العام (مدير فقط) — كود مكرر ⇒ 409."""
    code = payload.code.strip()
    if db.query(GeneralStockItem).filter(GeneralStockItem.code == code).first():
        raise HTTPException(status_code=409, detail="كود الصنف مستخدم مسبقًا")
    row = GeneralStockItem(**payload.model_dump())
    row.code = code
    row.name = payload.name.strip()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{item_id}", response_model=GeneralStockItemInDB, summary="تحديث صنف مخزون عام")
async def update_general_stock(
    item_id: int,
    payload: GeneralStockItemUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تحديث جزئي — الحقول غير المرسلة تبقى كما هي (مدير فقط)."""
    row = db.query(GeneralStockItem).filter(GeneralStockItem.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد صنف بالمعرف المحدد")

    data = payload.model_dump(exclude_unset=True)
    if "code" in data:
        code = (data["code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="كود الصنف مطلوب")
        clash = (db.query(GeneralStockItem)
                 .filter(GeneralStockItem.code == code, GeneralStockItem.id != item_id).first())
        if clash:
            raise HTTPException(status_code=409, detail="كود الصنف مستخدم مسبقًا")
        data["code"] = code
    if "name" in data:
        data["name"] = (data["name"] or "").strip()

    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{item_id}", status_code=204, summary="حذف صنف مخزون عام")
async def delete_general_stock(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف صنف (مدير فقط).

    صنف له حركات في دفتر المخزون أو سطور في مستندات لا يُحذف: سطور المستندات
    مقيدة بـ RESTRICT فكان الحذف ينتهي بـ 500 (FOREIGN KEY) بدل رسالة مفهومة،
    والحركات سجل لا يُمحى. البديل تعطيله (is_active=false) فيبقى للتدقيق.
    صنف برصيد قديم بلا حركات يُحذف كسابقه (تُمسح أرصدته ودفعاته تاليًا).
    """
    row = db.query(GeneralStockItem).filter(GeneralStockItem.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد صنف بالمعرف المحدد")

    moves = (db.query(GeneralStockMovement)
             .filter(GeneralStockMovement.item_id == item_id).count())
    lines = db.query(StockDocLine).filter(StockDocLine.item_id == item_id).count()
    if moves or lines:
        raise HTTPException(
            status_code=409,
            detail="لا يمكن حذف صنف له حركات مخزون أو مستندات — اعطِله (is_active=false) بدل حذفه",
        )
    db.delete(row)
    db.commit()
    return None


@router.post("/{item_id}/restock", response_model=GeneralStockItemInDB, summary="توريد كمية")
async def restock_general_stock(
    item_id: int,
    payload: GeneralStockItemUpdate,  # reuse: only quantity needed
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """زيادة كمية الصنف (مدير فقط)."""
    row = db.query(GeneralStockItem).filter(GeneralStockItem.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد صنف بالمعرف المحدد")
    qty = payload.quantity
    if qty is None or qty <= 0:
        raise HTTPException(status_code=422, detail="الكمية يجب أن تكون > 0")
    row.quantity += qty
    # TODO: log movement in a general_stock_movements table if needed
    db.commit()
    db.refresh(row)
    return row


@router.put("/{item_id}/adjust", response_model=GeneralStockItemInDB, summary="جرد مطلق")
async def adjust_general_stock(
    item_id: int,
    payload: GeneralStockItemUpdate,  # reuse: only quantity needed
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """ضبط الكمية على قيمة جرد فعلية (مدير فقط)."""
    row = db.query(GeneralStockItem).filter(GeneralStockItem.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد صنف بالمعرف المحدد")
    qty = payload.quantity
    if qty is None or qty < 0:
        raise HTTPException(status_code=422, detail="الكمية يجب أن تكون ≥ 0")
    row.quantity = qty
    db.commit()
    db.refresh(row)
    return row


@router.post("/{item_id}/dispose", response_model=GeneralStockItemInDB, summary="إتلاف كمية")
async def dispose_general_stock(
    item_id: int,
    payload: GeneralStockItemUpdate,  # reuse: only quantity needed
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """إتلاف كمية منتهية (مدير فقط)."""
    row = db.query(GeneralStockItem).filter(GeneralStockItem.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد صنف بالمعرف المحدد")
    qty = payload.quantity
    if qty is None or qty <= 0:
        raise HTTPException(status_code=422, detail="الكمية يجب أن تكون > 0")
    if qty > row.quantity:
        raise HTTPException(status_code=400, detail="الكمية المُتلفة تتجاوز المتوفر")
    row.quantity -= qty
    db.commit()
    db.refresh(row)
    return row