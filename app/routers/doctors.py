from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Doctor, User
from app.schemas import DoctorCreate, DoctorUpdate, DoctorInDB
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.get("/", response_model=List[DoctorInDB], summary="عرض قائمة الأطباء")
async def list_doctors(db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب كل الأطباء"""
    doctors = db.query(Doctor).all()
    return doctors


@router.get("/{doctor_id}", response_model=DoctorInDB, summary="عرض طبيب معين")
async def get_doctor(doctor_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب طبيب بواسطة المعرف"""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد طبيب بالمعرف المحدد"
        )
    return doctor


@router.post("/", response_model=DoctorInDB, summary="إضافة طبيب جديد")
async def create_doctor(doctor: DoctorCreate, db = Depends(get_db), _ = Depends(get_current_user)):
    """إضافة طبيب جديد"""
    # التحقق من عدم تكرار رقم التراخيص
    existing_doctor = db.query(Doctor).filter(Doctor.license_number == doctor.license_number).first()
    if existing_doctor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا رقم التراخيص مستخدم بالفعل"
        )
    
    # التحقق من عدم تكرار البريد الإلكتروني
    existing_email = db.query(Doctor).filter(Doctor.email == doctor.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا البريد الإلكتروني مستخدم من قبل طبيب آخر"
        )

    # التحقق من وجود القسم
    if doctor.department_id is not None:
        from app.models import Department
        if not db.query(Department).filter(Department.id == doctor.department_id).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="القسم غير موجود"
            )
    
    db_doctor = Doctor(
        full_name=doctor.full_name,
        specialty=doctor.specialty,
        license_number=doctor.license_number,
        phone=doctor.phone,
        email=doctor.email,
        address=doctor.address,
        is_available=doctor.is_available,
        department_id=doctor.department_id,
    )
    db.add(db_doctor)
    db.commit()
    db.refresh(db_doctor)
    return db_doctor


@router.put("/{doctor_id}", response_model=DoctorInDB, summary="تحديث بيانات طبيب")
async def update_doctor(doctor_id: int, doctor: DoctorUpdate, db = Depends(get_db), _ = Depends(get_current_user)):
    """تحديث بيانات طبيب"""
    db_doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not db_doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد طبيب بالمعرف المحدد"
        )
    
    update_data = doctor.model_dump(exclude_unset=True)
    if "department_id" in update_data and update_data["department_id"] is not None:
        from app.models import Department
        if not db.query(Department).filter(Department.id == update_data["department_id"]).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="القسم غير موجود"
            )
    for field, value in update_data.items():
        setattr(db_doctor, field, value)
    
    db.commit()
    db.refresh(db_doctor)
    return db_doctor


@router.delete("/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف طبيب")
async def delete_doctor(doctor_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف طبيب (للمدير فقط)"""
    db_doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not db_doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد طبيب بالمعرف المحدد"
        )
    
    db.delete(db_doctor)
    db.commit()
    return None