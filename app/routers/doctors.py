from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Department, Doctor, MedicalRecord, User
from app.schemas import (
    DoctorAvailability, DoctorCreate, DoctorInDB, DoctorSummaryStats,
    DoctorUpdate, DoctorWithStats, DoctorsStats,
)
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/doctors", tags=["Doctors"])

# خريطة الترتيب المسموح — أي قيمة أخرى = 400
_SORTS = {"name": "full_name", "specialty": "specialty", "created": "id"}


def _get_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد طبيب بالمعرف المحدد",
        )
    return doctor


@router.get("/", response_model=List[DoctorInDB], summary="عرض قائمة الأطباء")
async def list_doctors(
    q: Optional[str] = Query(None, description="بحث في الاسم/التخصص/الترخيص/البريد"),
    department_id: Optional[int] = Query(None, description="فلتر حسب القسم"),
    available: Optional[bool] = Query(None, description="فلتر حسب التوافر"),
    sort: Optional[str] = Query(None, description="الترتيب: name | specialty | created"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """قائمة الأطباء مع بحث وفلاتر اختيارية"""
    qry = db.query(Doctor)
    if q and q.strip():
        like = f"%{q.strip()}%"
        qry = qry.filter(or_(
            Doctor.full_name.ilike(like),
            Doctor.specialty.ilike(like),
            Doctor.license_number.ilike(like),
            Doctor.email.ilike(like),
        ))
    if department_id is not None:
        qry = qry.filter(Doctor.department_id == department_id)
    if available is not None:
        qry = qry.filter(Doctor.is_available == available)
    if sort:
        if sort not in _SORTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sort يجب أن يكون name أو specialty أو created",
            )
        qry = qry.order_by(getattr(Doctor, _SORTS[sort]))
    return qry.all()


@router.get("/stats", response_model=DoctorsStats, summary="إحصاءات قسم الأطباء")
async def doctors_stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """عدّادات جاهزة للوحة: الإجمالي/التوافر/التخصصات/الأقسام/المواعيد"""
    total = db.query(func.count(Doctor.id)).scalar() or 0
    available = (
        db.query(func.count(Doctor.id)).filter(Doctor.is_available.is_(True)).scalar() or 0
    )
    specialties = (
        db.query(func.count(func.distinct(Doctor.specialty))).scalar() or 0
    )
    without_department = (
        db.query(func.count(Doctor.id)).filter(Doctor.department_id.is_(None)).scalar() or 0
    )
    departments = (
        db.query(
            Department.id.label("did"),
            Department.name.label("dname"),
            func.count(Doctor.id).label("cnt"),
        )
        .outerjoin(Doctor, Doctor.department_id == Department.id)
        .group_by(Department.id, Department.name)
        .having(func.count(Doctor.id) > 0)
        .order_by(Department.name)
        .all()
    )
    appointments = db.query(func.count(Appointment.id)).scalar() or 0
    return DoctorsStats(
        total=total,
        available=available,
        unavailable=total - available,
        specialties=specialties,
        without_department=without_department,
        appointments=appointments,
        departments=[
            {"id": r.did, "name": r.dname, "count": r.cnt} for r in departments
        ],
    )


@router.get("/{doctor_id}", response_model=DoctorWithStats, summary="عرض طبيب معين مع إحصاءاته")
async def get_doctor(doctor_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """طبيب واحد + عدّاد مواعيده وسجلاته ومرضاه الفريد"""
    doctor = _get_or_404(db, doctor_id)
    appts = (
        db.query(func.count(Appointment.id))
        .filter(Appointment.doctor_id == doctor_id).scalar() or 0
    )
    records = (
        db.query(func.count(MedicalRecord.id))
        .filter(MedicalRecord.doctor_id == doctor_id).scalar() or 0
    )
    pat_appt = {
        r[0] for r in db.query(Appointment.patient_id)
        .filter(Appointment.doctor_id == doctor_id).all()
    }
    pat_rec = {
        r[0] for r in db.query(MedicalRecord.patient_id)
        .filter(MedicalRecord.doctor_id == doctor_id).all()
    }
    base = DoctorInDB.model_validate(doctor)
    out = DoctorWithStats(
        **base.model_dump(),
        stats=DoctorSummaryStats(
            appointments=appts, records=records, patients=len(pat_appt | pat_rec)
        ),
    )
    return out


@router.post("/", response_model=DoctorInDB, summary="إضافة طبيب جديد")
async def create_doctor(doctor: DoctorCreate, db: Session = Depends(get_db),
                        _: User = Depends(require_admin)):
    """إضافة طبيب جديد (admin فقط)"""
    # التحقق من عدم تكرار رقم التراخيص
    existing_doctor = db.query(Doctor).filter(Doctor.license_number == doctor.license_number).first()
    if existing_doctor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا رقم التراخيص مستخدم بالفعل",
        )

    # التحقق من عدم تكرار البريد الإلكتروني
    existing_email = db.query(Doctor).filter(Doctor.email == doctor.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا البريد الإلكتروني مستخدم من قبل طبيب آخر",
        )

    # التحقق من وجود القسم
    if doctor.department_id is not None:
        if not db.query(Department).filter(Department.id == doctor.department_id).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="القسم غير موجود",
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
async def update_doctor(doctor_id: int, doctor: DoctorUpdate,
                        db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """تحديث بيانات طبيب (admin فقط) — مع منع تكرار الترخيص/البريد"""
    db_doctor = _get_or_404(db, doctor_id)

    update_data = doctor.model_dump(exclude_unset=True)

    # منع تكرار البريد/الترخيص عند التحديث (كانت تنتج 500 IntegrityError)
    if "email" in update_data:
        clash = db.query(Doctor).filter(
            Doctor.email == update_data["email"], Doctor.id != doctor_id
        ).first()
        if clash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="هذا البريد الإلكتروني مستخدم من قبل طبيب آخر",
            )
    if "license_number" in update_data:
        clash = db.query(Doctor).filter(
            Doctor.license_number == update_data["license_number"], Doctor.id != doctor_id
        ).first()
        if clash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="هذا رقم التراخيص مستخدم بالفعل",
            )

    if "department_id" in update_data and update_data["department_id"] is not None:
        if not db.query(Department).filter(
            Department.id == update_data["department_id"]
        ).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="القسم غير موجود",
            )

    for field, value in update_data.items():
        setattr(db_doctor, field, value)

    db.commit()
    db.refresh(db_doctor)
    return db_doctor


@router.put("/{doctor_id}/availability", response_model=DoctorInDB,
            summary="تغيير توافر الطبيب")
async def set_availability(doctor_id: int, body: DoctorAvailability,
                           db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """تبديل التوافر — للمدير أو للطبيب نفسه (بريده المطابق)"""
    doctor = _get_or_404(db, doctor_id)
    is_self = (current_user.email or "").lower() == (doctor.email or "").lower()
    if current_user.role != "admin" and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا تملك صلاحية تغيير توافر هذا الطبيب — للمدير أو الطبيب نفسه فقط",
        )
    doctor.is_available = body.is_available
    db.commit()
    db.refresh(doctor)
    return doctor


@router.delete("/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف طبيب")
async def delete_doctor(doctor_id: int, db: Session = Depends(get_db),
                        _: User = Depends(require_admin)):
    """حذف طبيب (admin فقط) — مرفوض 409 إن كان له سجلات طبية أو مواعيد"""
    db_doctor = _get_or_404(db, doctor_id)

    records = (
        db.query(func.count(MedicalRecord.id))
        .filter(MedicalRecord.doctor_id == doctor_id).scalar() or 0
    )
    appts = (
        db.query(func.count(Appointment.id))
        .filter(Appointment.doctor_id == doctor_id).scalar() or 0
    )
    if records or appts:
        parts = []
        if records:
            parts.append(f"{records} سجل طبي")
        if appts:
            parts.append(f"{appts} موعدًا")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "لا يمكن حذف الطبيب: لديه "
                + " و".join(parts)
                + " — عطّله بدلًا من ذلك (is_available=false) للحفاظ على السجل"
            ),
        )

    db.delete(db_doctor)
    db.commit()
    return None
