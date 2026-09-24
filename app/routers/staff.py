from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Staff, User
from app.schemas import StaffCreate, StaffUpdate, StaffInDB
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get("/", response_model=List[StaffInDB], summary="عرض قائمة الموظفين")
async def list_staff(db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب كل الموظفين"""
    staff = db.query(Staff).all()
    return staff


@router.get("/{staff_id}", response_model=StaffInDB, summary="عرض موظف معين")
async def get_staff(staff_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب موظف بواسطة المعرف"""
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موظف بالمعرف المحدد"
        )
    return staff


@router.post("/", response_model=StaffInDB, summary="إضافة موظف جديد")
async def create_staff(staff: StaffCreate, db = Depends(get_db), _ = Depends(get_current_user)):
    """إضافة موظف جديد"""
    # التحقق من عدم تكرار البريد الإلكتروني
    existing_staff = db.query(Staff).filter(Staff.email == staff.email).first()
    if existing_staff:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا البريد الإلكتروني مسجل بالفعل"
        )
    
    db_staff = Staff(
        full_name=staff.full_name,
        position=staff.position,
        phone=staff.phone,
        email=staff.email,
        hire_date=staff.hire_date,
        salary=staff.salary,
    )
    db.add(db_staff)
    db.commit()
    db.refresh(db_staff)
    return db_staff


@router.put("/{staff_id}", response_model=StaffInDB, summary="تحديث بيانات موظف")
async def update_staff(staff_id: int, staff: StaffUpdate, db = Depends(get_db), _ = Depends(get_current_user)):
    """تحديث بيانات موظف"""
    db_staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not db_staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موظف بالمعرف المحدد"
        )
    
    update_data = staff.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_staff, field, value)
    
    db.commit()
    db.refresh(db_staff)
    return db_staff


@router.delete("/{staff_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف موظف")
async def delete_staff(staff_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف موظف (للمدير فقط)"""
    db_staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not db_staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موظف بالمعرف المحدد"
        )
    
    db.delete(db_staff)
    db.commit()
    return None