from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Bed, Department, Patient, User
from app.schemas import BedCreate, BedUpdate, BedFullInDB
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/beds", tags=["Beds"])


@router.get("/", response_model=List[BedFullInDB], summary="عرض قائمة الأسرّة")
async def list_beds(db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب كل الأسرّة"""
    return db.query(Bed).all()


@router.get("/{bed_id}", response_model=BedFullInDB, summary="عرض سرير معين")
async def get_bed(bed_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    bed = db.query(Bed).filter(Bed.id == bed_id).first()
    if not bed:
        raise HTTPException(status_code=404, detail="لا يوجد سرير بالمعرف المحدد")
    return bed


@router.post("/", response_model=BedFullInDB, summary="إضافة سرير جديد")
async def create_bed(
    bed: BedCreate,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """إضافة سرير لقسم (للمدير فقط)"""
    if not db.query(Department).filter(Department.id == bed.department_id).first():
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    if bed.patient_id and not db.query(Patient).filter(Patient.id == bed.patient_id).first():
        raise HTTPException(status_code=404, detail="المريض غير موجود")
    db_bed = Bed(**bed.model_dump())
    db.add(db_bed)
    db.commit()
    db.refresh(db_bed)
    return db_bed


@router.put("/{bed_id}", response_model=BedFullInDB, summary="تحديث سرير")
async def update_bed(
    bed_id: int,
    bed: BedUpdate,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """تحديث حالة السرير / تخصيصه لمريض"""
    db_bed = db.query(Bed).filter(Bed.id == bed_id).first()
    if not db_bed:
        raise HTTPException(status_code=404, detail="لا يوجد سرير بالمعرف المحدد")
    data = bed.model_dump(exclude_unset=True)
    if "patient_id" in data and data["patient_id"] is not None:
        if not db.query(Patient).filter(Patient.id == data["patient_id"]).first():
            raise HTTPException(status_code=404, detail="المريض غير موجود")
    for field, value in data.items():
        setattr(db_bed, field, value)
    db.commit()
    db.refresh(db_bed)
    return db_bed


@router.delete("/{bed_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف سرير")
async def delete_bed(
    bed_id: int,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    db_bed = db.query(Bed).filter(Bed.id == bed_id).first()
    if not db_bed:
        raise HTTPException(status_code=404, detail="لا يوجد سرير بالمعرف المحدد")
    db.delete(db_bed)
    db.commit()
    return None
