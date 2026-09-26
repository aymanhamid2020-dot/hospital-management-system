from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import (
    Appointment, Patient, Doctor, User, AppointmentStatus, DoctorSchedule,
    DoctorBlock, DoctorLeave,
)
from app.schemas import AppointmentCreate, AppointmentUpdate, AppointmentInDB
from app.auth import get_current_user, require_admin, get_user_role

router = APIRouter(prefix="/appointments", tags=["Appointments"])

_DAYS = ["السبت", "الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"]


def _check_appointment_in_schedule(db, doctor_id: int, dt) -> str:
    """التحقق من أن التاريخ ضمن نوبات الطبيب. يُرجع فارغة إذا كان مقبولاً.
    إذا لم تُحدَّد نوبات لهذا الطبيب → لا يوجد قيد."""
    from datetime import datetime
    sched = (db.query(DoctorSchedule)
             .filter(DoctorSchedule.doctor_id == doctor_id,
                     DoctorSchedule.is_active == True)
             .all())
    if not sched:
        return ""  # لا نوبات → لا قيد
    _py_to_hms = {5: 0, 6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6}
    hms_dow = _py_to_hms.get(dt.weekday())
    if hms_dow is None:
        return "تاريخ غير صالح"
    day_rows = [s for s in sched if s.day_of_week == hms_dow]
    if not day_rows:
        return (f"الطبيب لا يعمل في يوم {_DAYS[hms_dow]} — "
                f"يُرجى حجز موعد في يوم عمل")
    at = dt.time() if isinstance(dt, datetime) else dt
    for s in day_rows:
        if at < s.end_time and at > s.start_time:
            return ""  # مقبول
    return (f"الموعد خارج نوبات العمل المحددة ليوم {_DAYS[hms_dow]}")


def _check_blocked(db, doctor_id: int, dt) -> str:
    """منع الحجز في أيام الإجازة والحظر. يُرجع رسالة أو "" إن كان مسموحًا.

    الإجازة تغطي اليوم كاملًا، والحظر قد يكون لليوم كاملًا (بلا أوقات) أو
    لجزء منه (نطاق داخل اليوم) — والمقارنة بالساعة لتجاهل الثانية.
    """
    from datetime import datetime, timedelta
    if not isinstance(dt, datetime):
        return ""
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = day + timedelta(days=1)

    on_leave = (db.query(DoctorLeave.id)
                .filter(DoctorLeave.doctor_id == doctor_id,
                        DoctorLeave.is_approved.is_(True),
                        DoctorLeave.start_date < nxt,
                        DoctorLeave.end_date >= day)
                .first())
    if on_leave:
        return "الطبيب في إجازة في هذا اليوم — اختر تاريخًا آخر"

    for b in (db.query(DoctorBlock)
              .filter(DoctorBlock.doctor_id == doctor_id,
                      DoctorBlock.block_date >= day,
                      DoctorBlock.block_date < nxt).all()):
        if b.start_time is None or b.end_time is None:
            return f"الحجز محظور في هذا اليوم ({b.reason or 'محجوز'})"
        at = dt.time()
        if at >= b.start_time and at < b.end_time:
            return f"الحجز محظور في هذه الفترة ({b.reason or 'محجوز'})"
    return ""


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
    
    # التحقق من أن الموعد ضمن نوبات الطبيب
    _sch_msg = _check_appointment_in_schedule(db, appointment.doctor_id, appointment.appointment_date)
    if _sch_msg:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_sch_msg)

    # منع الحجز في إجازات الطبيب وأيام الحظر
    _blk_msg = _check_blocked(db, appointment.doctor_id, appointment.appointment_date)
    if _blk_msg:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_blk_msg)
    
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
    
    # التحقق من أن الموعد ضمن نوبات الطبيب
    new_date = appointment.appointment_date or db_appointment.appointment_date
    _sch_msg = _check_appointment_in_schedule(db, db_appointment.doctor_id, new_date)
    if _sch_msg:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_sch_msg)

    # إعادة الجدولة إلى يوم إجازة/محظور ممنوعة أيضًا
    if new_date != db_appointment.appointment_date:
        _blk_msg = _check_blocked(db, db_appointment.doctor_id, new_date)
        if _blk_msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_blk_msg)
    
    # التحقق من توفر الطبيب (استبعاد الموعد الحالي) - فقط عند تغيير التاريخ أو الطبيب
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