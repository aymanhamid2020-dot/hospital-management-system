from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from fastapi import Query
from datetime import datetime, date

from app.database import get_db
from app.models import (
    Patient, Doctor, Appointment, Staff, Invoice, Department, Bed,
    MedicalRecord, AppointmentStatus, InvoiceStatus, BedStatus, User,
)
from app.schemas import DashboardStats
from app.auth import get_current_user, get_user_role

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats, summary="إحصائيات لوحة التحكم")
async def get_stats(db = Depends(get_db), _ = Depends(get_current_user)):
    """إحصائيات شاملة للنظام"""
    total_patients = db.query(func.count(Patient.id)).scalar() or 0
    total_doctors = db.query(func.count(Doctor.id)).scalar() or 0
    total_appointments = db.query(func.count(Appointment.id)).scalar() or 0
    total_staff = db.query(func.count(Staff.id)).scalar() or 0
    total_departments = db.query(func.count(Department.id)).scalar() or 0

    # المواعيد اليوم
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    appointments_today = (
        db.query(func.count(Appointment.id))
        .filter(Appointment.appointment_date.between(today_start, today_end))
        .scalar() or 0
    )

    # المواعيد المعلّقة
    pending_appointments = (
        db.query(func.count(Appointment.id))
        .filter(Appointment.status == AppointmentStatus.PENDING)
        .scalar() or 0
    )

    # توزيع المواعيد حسب الحالة
    status_rows = (
        db.query(Appointment.status, func.count(Appointment.id))
        .group_by(Appointment.status)
        .all()
    )
    appointments_by_status = {
        (s.value if hasattr(s, "value") else str(s)): c for s, c in status_rows
    }

    # الأسرّة
    beds_total = db.query(func.count(Bed.id)).scalar() or 0
    beds_available = (
        db.query(func.count(Bed.id)).filter(Bed.status == BedStatus.AVAILABLE).scalar() or 0
    )
    beds_occupied = (
        db.query(func.count(Bed.id)).filter(Bed.status == BedStatus.OCCUPIED).scalar() or 0
    )

    # الإيرادات (إجمالي شامل الخصم/الضريبة − المدفوع فعليًا)
    total_expr = (
        (Invoice.amount - func.coalesce(Invoice.discount, 0.0))
        * (1.0 + func.coalesce(Invoice.tax_rate, 0.0) / 100.0)
    )
    revenue_total = db.query(func.coalesce(func.sum(total_expr), 0.0)).scalar() or 0.0
    revenue_paid = (
        db.query(func.coalesce(func.sum(Invoice.paid_amount), 0.0)).scalar() or 0.0
    )
    revenue_unpaid = max(0.0, float(revenue_total) - float(revenue_paid))

    return DashboardStats(
        total_patients=total_patients,
        total_doctors=total_doctors,
        total_appointments=total_appointments,
        appointments_today=appointments_today,
        pending_appointments=pending_appointments,
        total_staff=total_staff,
        total_departments=total_departments,
        beds_available=beds_available,
        beds_occupied=beds_occupied,
        beds_total=beds_total,
        revenue_total=float(revenue_total),
        revenue_paid=float(revenue_paid),
        revenue_unpaid=float(revenue_unpaid),
        appointments_by_status=appointments_by_status,
    )


def _doctor_stats(db: Session, doctor: Doctor) -> DashboardStats:
    """إحصائيات محصورة بمرضى/مواعيد الطبيب + أسرّة قسمه (لتقريره الخاص)."""
    from sqlalchemy import or_

    appt_rows = (
        db.query(Appointment.appointment_date, Appointment.status)
        .filter(Appointment.doctor_id == doctor.id)
        .all()
    )
    my_patient_ids = {
        r[0] for r in db.query(Appointment.patient_id)
        .filter(Appointment.doctor_id == doctor.id)
    } | {
        r[0] for r in db.query(MedicalRecord.patient_id)
        .filter(MedicalRecord.doctor_id == doctor.id)
    }

    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    appointments_today = sum(1 for d, _ in appt_rows if today_start <= d <= today_end)
    pending = sum(1 for _, s in appt_rows if s == AppointmentStatus.PENDING)

    by_status = {}
    for _, s in appt_rows:
        key = s.value if hasattr(s, "value") else str(s)
        by_status[key] = by_status.get(key, 0) + 1

    appt_ids = [r[0] for r in db.query(Appointment.id)
                .filter(Appointment.doctor_id == doctor.id)]
    rec_ids = [r[0] for r in db.query(MedicalRecord.id)
               .filter(MedicalRecord.doctor_id == doctor.id)]

    invs = []
    if appt_ids or rec_ids:
        invs = (
            db.query(Invoice)
            .filter(or_(
                Invoice.appointment_id.in_(appt_ids),
                Invoice.record_id.in_(rec_ids),
            ))
            .all()
        )
    revenue_total = float(sum(i.total for i in invs))
    revenue_paid = float(sum((i.paid_amount or 0) for i in invs))
    revenue_unpaid = max(0.0, revenue_total - revenue_paid)

    # أسرّة قسم الطبيب (أو الكل إن لم يكن مرتبطًا بقسم)
    bed_q = db.query(func.count(Bed.id))
    if doctor.department_id:
        bed_q = bed_q.filter(Bed.department_id == doctor.department_id)
        total_departments = (
            db.query(func.count(Department.id))
            .filter(Department.id == doctor.department_id).scalar() or 0
        )
    else:
        total_departments = db.query(func.count(Department.id)).scalar() or 0

    return DashboardStats(
        total_patients=len(my_patient_ids),
        total_doctors=db.query(func.count(Doctor.id)).scalar() or 0,
        total_appointments=len(appt_rows),
        appointments_today=appointments_today,
        pending_appointments=pending,
        total_staff=db.query(func.count(Staff.id)).scalar() or 0,
        total_departments=total_departments,
        beds_available=bed_q.filter(Bed.status == BedStatus.AVAILABLE).scalar() or 0,
        beds_occupied=bed_q.filter(Bed.status == BedStatus.OCCUPIED).scalar() or 0,
        beds_total=bed_q.scalar() or 0,
        revenue_total=revenue_total,
        revenue_paid=revenue_paid,
        revenue_unpaid=revenue_unpaid,
        appointments_by_status=by_status,
    )


@router.get("/report/pdf", summary="تقرير إحصائي PDF")
async def download_stats_report(
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (اختياري — افتراضي: الفترة الحالية"),
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تقرير PDF — للمدير (كل المستشفى) وللطبيب (مرضاه ومواعيده وأقسامه فقط) — ar|en"""
    from fastapi.responses import Response
    from app.pdf_utils import stats_report_pdf
    from datetime import datetime as _dt

    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")

    # التحقق من صيغة الشهر
    if month:
        try:
            _dt.strptime(month, "%Y-%m")
            month_label = f"شهر {month}" if lang == "ar" else f"Month {month}"
        except ValueError:
            raise HTTPException(status_code=400, detail="صيغة الشهر يجب أن تكون YYYY-MM")
    else:
        month_label = "الوضع الراهن" if lang == "ar" else "Current state"

    role = get_user_role(current_user)
    if role == "admin":
        stats = await get_stats(db=db, _=None)
        label = month_label
    elif role == "doctor":
        doctor = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if doctor is None:
            raise HTTPException(status_code=403, detail="حسابك غير مرتبط بسجل طبيب")
        stats = _doctor_stats(db, doctor)
        label = (f"تقرير الطبيب {doctor.full_name} — {month_label}" if lang == "ar"
                 else f"Dr. {doctor.full_name} report — {month_label}")
    else:
        raise HTTPException(status_code=403, detail="التقرير متاح للمدير والطبيب فقط")

    pdf_bytes = stats_report_pdf(stats.model_dump(), label, lang=lang)
    fname = f"report_{month or 'current'}{'_en' if lang == 'en' else ''}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
