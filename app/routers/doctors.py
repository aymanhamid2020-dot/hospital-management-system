from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Appointment, Department, Doctor, DoctorSchedule, MedicalRecord, User,
)
from app.schemas import (
    DoctorAvailability, DoctorCreate, DoctorInDB, DoctorPerformance,
    DoctorPerformanceRow, DoctorScheduleEntry, DoctorScheduleUpdate,
    DoctorSummaryStats, DoctorUpdate, DoctorWithStats, DoctorsStats,
)
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/doctors", tags=["Doctors"])

# خريطة الترتيب المسموح — أي قيمة أخرى = 400
_SORTS = {"name": "full_name", "specialty": "specialty", "created": "id"}

# أيام الأسبوع بترقيم عربي: 0=السبت … 6=الجمعة
_DAYS = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"]


def _get_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد طبيب بالمعرف المحدد",
        )
    return doctor


def _month_bounds(month: Optional[str]):
    """يتحقق من month (YYYY-MM) ويعيده مع حدَّي الشهر: [البداية، البداية التالية)."""
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    if not (len(month) == 7 and month[4] == "-"
            and month[:4].isdigit() and month[5:7].isdigit()
            and 1 <= int(month[5:7]) <= 12):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="month يجب أن يكون بصيغة YYYY-MM مثل 2026-09",
        )
    year, mon = int(month[:4]), int(month[5:7])
    start = datetime(year, mon, 1)
    end = datetime(year + 1, 1, 1) if mon == 12 else datetime(year, mon + 1, 1)
    return month, start, end


def _require_admin_or_self(current_user: User, doctor: Doctor, what: str):
    """صلاحية تعديل طبيب: المدير أو الطبيب نفسه (مطابقة منطق التوافر)."""
    is_self = (current_user.email or "").lower() == (doctor.email or "").lower()
    if current_user.role != "admin" and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"لا تملك صلاحية {what} — للمدير أو الطبيب نفسه فقط",
        )


def _performance_for(db: Session, doctor_id: int, month: str,
                     start: datetime, end: datetime) -> "DoctorPerformance":
    """أرقام شهر طبيب واحدة — تُستخدم في التقرير الفردي والمقارنة والتصدير."""
    rows = (db.query(Appointment.status, func.count(Appointment.id))
            .filter(Appointment.doctor_id == doctor_id,
                    Appointment.appointment_date >= start,
                    Appointment.appointment_date < end)
            .group_by(Appointment.status).all())
    by_status = {getattr(st, "value", str(st)): cnt for st, cnt in rows}
    total = sum(by_status.values())
    completed = by_status.get("completed", 0)
    patients = (db.query(func.count(func.distinct(Appointment.patient_id)))
                .filter(Appointment.doctor_id == doctor_id,
                        Appointment.appointment_date >= start,
                        Appointment.appointment_date < end)
                .scalar() or 0)
    records = (db.query(func.count(MedicalRecord.id))
               .filter(MedicalRecord.doctor_id == doctor_id,
                       MedicalRecord.created_at >= start,
                       MedicalRecord.created_at < end)
               .scalar() or 0)
    return DoctorPerformance(
        month=month, doctor_id=doctor_id, total=total, completed=completed,
        cancelled=by_status.get("cancelled", 0),
        pending=by_status.get("pending", 0),
        confirmed=by_status.get("confirmed", 0),
        completion_rate=round(completed / total, 4) if total else 0.0,
        patients=patients, records=records,
    )


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


@router.get("/performance", response_model=List[DoctorPerformanceRow],
            summary="تقرير مقارن لأداء جميع الأطباء لشهر")
async def all_doctors_performance(
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (افتراضي: الشهر الحالي)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """كل الأطباء مع أرقام شهرهم — مرتَّبين حسب نسبة الإتمام ثم حجم العمل"""
    month, start, end = _month_bounds(month)
    doctors = db.query(Doctor).order_by(Doctor.full_name.asc()).all()
    rows: List[DoctorPerformanceRow] = []
    for d in doctors:
        perf = _performance_for(db, d.id, month, start, end)
        rows.append(DoctorPerformanceRow(
            **perf.model_dump(),
            full_name=d.full_name,
            specialty=d.specialty,
            is_available=d.is_available,
            department=d.department.name if d.department else None,
        ))
    rows.sort(key=lambda r: (-r.completion_rate, -r.total, r.full_name))
    return rows


@router.get("/performance/export.csv", summary="تصدير التقرير المقارن إلى CSV")
async def export_all_performance_csv(
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (افتراضي: الشهر الحالي)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """التقرير المقارن لجميع الأطباء إلى CSV (UTF-8 + BOM)"""
    import csv as _csv
    import io as _io
    from fastapi.responses import Response

    month, start, end = _month_bounds(month)
    doctors = db.query(Doctor).order_by(Doctor.full_name.asc()).all()
    paired = [(d, _performance_for(db, d.id, month, start, end)) for d in doctors]
    paired.sort(key=lambda t: (-t[1].completion_rate, -t[1].total, t[0].full_name))

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["#", "الطبيب", "التخصص", "القسم", "الشهر", "الإجمالي", "مكتملة",
                "ملغاة", "معلّقة", "مؤكّدة", "نسبة الإتمام %", "مرضى", "سجلات"])
    for i, (d, perf) in enumerate(paired, 1):
        w.writerow([i, d.full_name, d.specialty,
                    d.department.name if d.department else "",
                    month, perf.total, perf.completed, perf.cancelled,
                    perf.pending, perf.confirmed,
                    f"{perf.completion_rate * 100:.1f}", perf.patients, perf.records])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=doctors_performance_{month}.csv"},
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
    _require_admin_or_self(current_user, doctor, "تغيير توافر هذا الطبيب")
    doctor.is_available = body.is_available
    db.commit()
    db.refresh(doctor)
    return doctor


@router.get("/{doctor_id}/performance", response_model=DoctorPerformance,
            summary="تقرير أداء الطبيب الشهري")
async def doctor_performance(doctor_id: int,
                             month: Optional[str] = Query(
                                 None,
                                 description="الشهر بصيغة YYYY-MM — افتراضي الشهر الحالي"),
                             db: Session = Depends(get_db),
                             _: User = Depends(get_current_user)):
    """أداء الطبيب في شهر: مواعيد حسب الحالة + نسبة الإتمام + مرضاه + سجلاته."""
    _get_or_404(db, doctor_id)
    month, start, end = _month_bounds(month)
    return _performance_for(db, doctor_id, month, start, end)


@router.get("/{doctor_id}/performance/export.csv",
            summary="تصدير تقرير الطبيب الشهري إلى CSV")
async def export_doctor_performance_csv(
    doctor_id: int,
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (افتراضي: الشهر الحالي)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """تقرير طبيب واحد إلى CSV (UTF-8 + BOM)"""
    import csv as _csv
    import io as _io
    from fastapi.responses import Response

    doctor = _get_or_404(db, doctor_id)
    month, start, end = _month_bounds(month)
    perf = _performance_for(db, doctor_id, month, start, end)

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["الطبيب", "التخصص", "القسم", "الشهر", "الإجمالي", "مكتملة",
                "ملغاة", "معلّقة", "مؤكّدة", "نسبة الإتمام %", "مرضى", "سجلات"])
    w.writerow([doctor.full_name, doctor.specialty,
                doctor.department.name if doctor.department else "",
                month, perf.total, perf.completed, perf.cancelled,
                perf.pending, perf.confirmed,
                f"{perf.completion_rate * 100:.1f}", perf.patients, perf.records])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=doctor_{doctor_id}_performance_{month}.csv"},
    )


@router.get("/{doctor_id}/performance/report.pdf", summary="تقرير الطبيب الشهري PDF")
async def doctor_performance_pdf(
    doctor_id: int,
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (افتراضي: الشهر الحالي)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """تقرير أداء الطبيب الشهري كمستند PDF عربي"""
    from fastapi.responses import Response
    from app.pdf_utils import doctor_report_pdf

    doctor = _get_or_404(db, doctor_id)
    month, start, end = _month_bounds(month)
    perf = _performance_for(db, doctor_id, month, start, end)
    return Response(
        content=doctor_report_pdf(perf, doctor, month),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename=doctor_{doctor_id}_report_{month}.pdf"},
    )


@router.get("/{doctor_id}/license.pdf", summary="بطاقة ترخيص الطبيب PDF")
async def doctor_license_card(
    doctor_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """بطاقة ترخيص ممارسة المهن الطبية — مستند إلكتروني للطباعة"""
    from fastapi.responses import Response
    from app.pdf_utils import doctor_license_pdf

    doctor = _get_or_404(db, doctor_id)
    return Response(
        content=doctor_license_pdf(doctor),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename=license_doctor_{doctor_id}.pdf"},
    )


@router.get("/{doctor_id}/schedule", response_model=List[DoctorScheduleEntry],
            summary="نوبات عمل الطبيب الأسبوعية")
async def get_doctor_schedule(doctor_id: int, db: Session = Depends(get_db),
                              _=Depends(get_current_user)):
    """نوبات الأسبوع (0=السبت … 6=الجمعة) — فارغة قبل أول حفظ"""
    _get_or_404(db, doctor_id)
    return (db.query(DoctorSchedule)
            .filter(DoctorSchedule.doctor_id == doctor_id)
            .order_by(DoctorSchedule.day_of_week)
            .all())


@router.put("/{doctor_id}/schedule", response_model=List[DoctorScheduleEntry],
            summary="استبدال نوبات أسبوع الطبيب")
async def put_doctor_schedule(doctor_id: int, body: DoctorScheduleUpdate,
                              db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """حفظ الأسبوع كاملًا — للمدير أو الطبيب نفسه، مع رفض التكرار والتداخل"""
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "تعديل نوبات هذا الطبيب")

    entries = body.entries
    seen = set()
    for e in entries:
        if e.day_of_week in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"يوم مكرر في الجدول: {_DAYS[e.day_of_week]}",
            )
        seen.add(e.day_of_week)
        if e.end_time <= e.start_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="وقت النهاية يجب أن يكون بعد وقت البداية",
            )

    db.query(DoctorSchedule).filter(
        DoctorSchedule.doctor_id == doctor_id).delete(synchronize_session=False)
    for e in entries:
        db.add(DoctorSchedule(doctor_id=doctor_id, day_of_week=e.day_of_week,
                              start_time=e.start_time, end_time=e.end_time,
                              location=e.location, is_active=e.is_active))
    db.commit()
    return (db.query(DoctorSchedule)
            .filter(DoctorSchedule.doctor_id == doctor_id)
            .order_by(DoctorSchedule.day_of_week)
            .all())


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
