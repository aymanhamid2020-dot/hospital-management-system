from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import RadiologyRoom, User
from app.schemas import RadiologyRoomCreate, RadiologyRoomInDB, RadiologyRoomUpdate

router = APIRouter(prefix="/radiology-rooms", tags=["Lab & Radiology"])


@router.get("/", response_model=List[RadiologyRoomInDB], summary="قائمة غرف/أجهزة الأشعة")
async def list_radiology_rooms(
    modality: Optional[str] = Query(None, pattern="^(XRAY|CT|MRI|ULTRASOUND)$",
                                    description="فلترة بنوع الجهاز"),
    active_only: bool = Query(False, description="الغرف المفعّلة فقط"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """قائمة غرف الأشعة والأجهزة (XRAY/CT/MRI/ULTRASOUND) مع حالتها"""
    q = db.query(RadiologyRoom)
    if modality:
        q = q.filter(RadiologyRoom.modality == modality)
    if active_only:
        q = q.filter(RadiologyRoom.is_active.is_(True))
    return q.order_by(RadiologyRoom.modality, RadiologyRoom.name).all()


@router.post("/", response_model=RadiologyRoomInDB, status_code=status.HTTP_201_CREATED,
             summary="إضافة غرفة/جهاز أشعة")
async def create_radiology_room(
    payload: RadiologyRoomCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تعريف غرفة أشعة جديدة مع نوع الجهاز (مدير فقط)"""
    name = payload.name.strip()
    if db.query(RadiologyRoom).filter(RadiologyRoom.name == name).first():
        raise HTTPException(status_code=409, detail="اسم الغرفة مستخدم مسبقًا")
    row = RadiologyRoom(**payload.model_dump())
    row.name = name
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{room_id}", response_model=RadiologyRoomInDB, summary="تحديث غرفة/جهاز أشعة")
async def update_radiology_room(
    room_id: int,
    payload: RadiologyRoomUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تحديث جزئي — الحقول غير المرسلة تبقى كما هي (مدير فقط)"""
    row = db.query(RadiologyRoom).filter(RadiologyRoom.id == room_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا توجد غرفة بالمعرف المحدد")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="اسم الغرفة مطلوب")
        clash = (db.query(RadiologyRoom)
                 .filter(RadiologyRoom.name == name, RadiologyRoom.id != room_id).first())
        if clash:
            raise HTTPException(status_code=409, detail="اسم الغرفة مستخدم مسبقًا")
        data["name"] = name

    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف غرفة/جهاز أشعة")
async def delete_radiology_room(
    room_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف غرفة — الطلبات المجدولة فيها تبقى بلا غرفة (FK SET NULL) (مدير فقط)"""
    row = db.query(RadiologyRoom).filter(RadiologyRoom.id == room_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا توجد غرفة بالمعرف المحدد")
    db.delete(row)
    db.commit()
    return None