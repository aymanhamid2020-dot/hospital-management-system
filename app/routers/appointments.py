from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Appointment, Patient, Doctor, User, AppointmentStatus
from app.schemas import AppointmentCreate, AppointmentUpdate, AppointmentInDB
from app.auth import get_current_user, require_admin, get_user_role

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.get("/", response_model=List[AppointmentInDB], summary="عرض قائمة المواعيد")
async def list_appointments(
    date: Optional[str] = Query(None, description="فلترة بالتاريخ (YYYY-MM-DD)"),
    doctor_id: Optional[int] = Query(None, description="فلترة حسب الطبيب"),
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    status_filter: Optional[str] = Query(None, alias="status", description="فلترة حسب الحالة"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """جلب المواعيد — الطبيب يرى مواعيده فقط"""
    from datetime import datetime, date as date_cls

    q = db.query(Appointment)

    # صلاحية الطبيب: يرى مواعيده فقط
    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            return []
        q = q.filter(Appointment.doctor_id == linked.id)

    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="صيغة التاريخ يجب أن تكون YYYY-MM-DD")
        day_start = datetime.combine(d, datetime.min.time())
        day_end = datetime.combine(d, datetime.max.time())
        q = q.filter(Appointment.appointment_date.between(day_start, day_end))
    if doctor_id is not None:
        q = q.filter(Appointment.doctor_id == doctor_id)
    if patient_id is not None:
        q = q.filter(Appointment.patient_id == patient_id)
    if status_filter:
        q = q.filter(Appointment.status == status_filter)

    return q.order_by(Appointment.appointment_date.asc()).all()


@router.get("/queue", response_model=List[AppointmentInDB], summary="طابور الوصول لليوم")
async def queue_today(
    date: Optional[str] = Query(None, description="YYYY-MM-DD — افتراضيًا اليوم"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """مواعيد وصلت فعليًا (Check-in) مرتبة برقم الطابور — موظف الاستقبال يرى اليوم كلها"""
    from datetime import datetime, date as date_cls

    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="صيغة التاريخ يجب أن تكون YYYY-MM-DD")
    else:
        d = date_cls.today()
    day_start = datetime.combine(d, datetime.min.time())
    day_end = datetime.combine(d, datetime.max.time())

    q = db.query(Appointment).filter(
        Appointment.appointment_date.between(day_start, day_end),
        Appointment.checked_in_at.isnot(None),
    )
    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            return []
        q = q.filter(Appointment.doctor_id == linked.id)
    rows = q.all()
    rows.sort(key=lambda a: a.queue_number or 0)
    return rows


@router.get("/{appointment_id}", response_model=AppointmentInDB, summary="عرض موعد معين")
@router.post("/{appointment_id}/checkin", response_model=AppointmentInDB, summary="تسجيل وصول المريض (طابور)")
async def check_in_appointment(appointment_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """تسجيل وصول المريض وإصدار رقم طابور تسلسلي لليوم"""
    from datetime import datetime, date as date_cls
    from sqlalchemy import func as _func

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="لا يوجد موعد بالمعرف المحدد")
    if appt.checked_in_at is not None:
        raise HTTPException(status_code=400, detail="تم تسجيل وصول هذا الموعد بالفعل")
    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
        raise HTTPException(status_code=400, detail="لا يمكن تسجيل وصول لموعد ملغى أو مكتمل")

    d = appt.appointment_date.date()
    day_start = datetime.combine(d, datetime.min.time())
    day_end = datetime.combine(d, datetime.max.time())
    max_no = (
        db.query(_func.max(Appointment.queue_number))
        .filter(
            Appointment.appointment_date.between(day_start, day_end),
            Appointment.queue_number.isnot(None),
        )
        .scalar() or 0
    )
    appt.queue_number = int(max_no) + 1
    appt.checked_in_at = datetime.now()
    db.commit()
    db.refresh(appt)
    return appt


async def get_appointment(appointment_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب موعد بواسطة المعرف"""
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موعد بالمعرف المحدد"
        )
    return appointment


@router.post("/", response_model=AppointmentInDB, summary="حجز موعد جديد")
async def create_appointment(
    appointment: AppointmentCreate,
    background_tasks: BackgroundTasks,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """حجز موعد جديد"""
    # التحقق من وجود المريض
    patient = db.query(Patient).filter(Patient.id == appointment.patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد مريض بالمعرف المحدد"
        )
    
    # التحقق من وجود الطبيب
    doctor = db.query(Doctor).filter(Doctor.id == appointment.doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد طبيب بالمعرف المحدد"
        )
    
    # التحقق من توفر الطبيب في التاريخ المطلوب
    existing_appointment = db.query(Appointment).filter(
        Appointment.doctor_id == appointment.doctor_id,
        Appointment.appointment_date == appointment.appointment_date
    ).first()
    
    if existing_appointment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
           detail="هذا الطبيب له موعد في هذا التاريخ بالفعل"
        )
    
    db_appointment = Appointment(
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        appointment_date=appointment.appointment_date,
        reason=appointment.reason,
        status=appointment.status,
    )
    db.add(db_appointment)
    db.commit()
    db.refresh(db_appointment)

    # إشعار داخلي + بريد تأكيد للمريض (BackgroundTasks يعمل بعد الاستجابة)
    from app.models import Notification
    from app.email_utils import send_email, appointment_created_email

    db.add(Notification(
        type="appointment",
        title="موعد جديد",
        message=f"حُجز موعد للمرضى {patient.full_name} مع {doctor.full_name} في {db_appointment.appointment_date:%Y-%m-%d %H:%M}",
        appointment_id=db_appointment.id,
        patient_id=appointment.patient_id,
    ))
    db.commit()

    if patient.email:
        subj, body = appointment_created_email(
            patient.full_name, doctor.full_name,
            f"{db_appointment.appointment_date:%Y-%m-%d %H:%M}")
        background_tasks.add_task(send_email, patient.email, subj, body)

    return db_appointment


@router.put("/{appointment_id}", response_model=AppointmentInDB, summary="تحديث موعد")
async def update_appointment(
    appointment_id: int,
    appointment: AppointmentUpdate,
    background_tasks: BackgroundTasks,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """تحديث موعد"""
    db_appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not db_appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موعد بالمعرف المحدد"
        )
    
    # التحقق من توفر الطبيب (استبعاد الموعد الحالي) - فقط عند تغيير التاريخ أو الطبيب
    new_date = appointment.appointment_date or db_appointment.appointment_date
    existing_appointment = db.query(Appointment).filter(
        Appointment.appointment_date == new_date,
        Appointment.id != appointment_id,
        Appointment.doctor_id == db_appointment.doctor_id,
    ).first()

    if existing_appointment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا الطبيب له موعد في هذا التاريخ بالفعل"
        )

    for field, value in appointment.model_dump(exclude_unset=True).items():
        setattr(db_appointment, field, value)

    db.commit()
    db.refresh(db_appointment)

    # عند التأكيد أو الإلغاء → إشعار داخلي + بريد عند التأكيد
    data = appointment.model_dump(exclude_unset=True)
    if "status" in data and data["status"] in ("confirmed", "cancelled"):
        from app.models import Notification
        from app.email_utils import send_email, appointment_created_email

        new_status = "مؤكَّد" if data["status"] == "confirmed" else "ملغى"
        pat = db.query(Patient).filter(Patient.id == db_appointment.patient_id).first()
        doc = db.query(Doctor).filter(Doctor.id == db_appointment.doctor_id).first()

        db.add(Notification(
            type="appointment",
            title=f"تحديث موعد ({new_status})",
            message=f"أصبح موعد {pat.full_name if pat else '-'} مع {doc.full_name if doc else '-'} {new_status}",
            appointment_id=db_appointment.id,
            patient_id=db_appointment.patient_id,
        ))
        db.commit()

        if pat and pat.email and data["status"] == "confirmed":
            subj, body = appointment_created_email(
                pat.full_name, doc.full_name if doc else "-",
                f"{db_appointment.appointment_date:%Y-%m-%d %H:%M}")
            background_tasks.add_task(send_email, pat.email, subj, body)

    return db_appointment


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف موعد")
async def delete_appointment(appointment_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف موعد (للمدير فقط)"""
    db_appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not db_appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موعد بالمعرف المحدد"
        )
    
    db.delete(db_appointment)
    db.commit()
    return None