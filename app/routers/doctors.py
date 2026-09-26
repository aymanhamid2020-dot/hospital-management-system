import json
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import (APIRouter, Depends, File, HTTPException, Query,
                     UploadFile, status)
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Appointment, Department, Doctor, DoctorBlock, DoctorCommission,
    DoctorLeave, DoctorPayout, DoctorSchedule, DoctorShift, Invoice,
    LabOrder, MedicalRecord, Prescription, PrescriptionItem, Medication,
    User,
)
from app.schemas import (
    DoctorAvailability, DoctorBlockCreate, DoctorBlockInDB,
    DoctorChart, DoctorCommissionCreate, DoctorCommissionInDB,
    DoctorCreate, DoctorInDB, DoctorLeaveCreate, DoctorLeaveInDB,
    DoctorLedger, DoctorOrderStats, DoctorPerformance,
    DoctorPerformanceRow, DoctorPermissions, DoctorPayoutCreate,
    DoctorPayoutInDB, DoctorProfileUpdate, DoctorScheduleEntry,
    DoctorScheduleUpdate, DoctorShiftCreate, DoctorShiftInDB,
    DoctorSummaryStats, DoctorUpdate, DoctorVisitStats, DoctorWithStats,
    DoctorsStats,
)
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/doctors", tags=["Doctors"])

# خريطة الترتيب المسموح — أي قيمة أخرى = 400
_SORTS = {"name": "full_name", "specialty": "specialty", "created": "id"}

# أيام الأسبوع بترقيم عربي: 0=السبت … 6=الجمعة
_DAYS = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"]

# مجلد رفع التوقيع والختم الطبي
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
_STAMP_MAX_BYTES = 2 * 1024 * 1024          # 2 ميجابايت
_STAMP_KINDS = ("signature", "stamp")
_STAMP_ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}

# تسميات أنواع الخدمات (تستهلكها الواجهة وPDF)
SERVICE_LABELS = {
    "consultation": "كشفية",
    "procedure": "إجراءات",
    "followup": "إعادة",
    "surgery": "عمليات جراحية",
}


def _load_permissions(doctor: Doctor) -> DoctorPermissions:
    """قراءة صلاحيات الطبيب من JSON — النص التالف أو الفارغ يعود للافتراضي."""
    try:
        return DoctorPermissions(**(json.loads(doctor.permissions or "{}")))
    except (ValueError, TypeError):
        return DoctorPermissions()


def _check_kind(kind: str):
    if kind not in _STAMP_KINDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="kind يجب أن يكون signature أو stamp",
        )


def _store_stamp(doctor_id: int, kind: str, upload: UploadFile) -> str:
    """حفظ صورة التوقيع أو الختم — يُرجع اسم الملف المخزَّن."""
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in _STAMP_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="صيغة غير مسموحة — الصور فقط: png, jpg, jpeg, webp",
        )
    content = upload.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(content) > _STAMP_MAX_BYTES:
        raise HTTPException(status_code=413, detail="حجم الصورة يتجاوز 2 ميجابايت")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored = f"stamp_{kind}_{doctor_id}_{uuid.uuid4().hex[:8]}{ext}"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as f:
        f.write(content)
    return stored


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


def _visit_stats(db: Session, doctor_id: int, start: datetime,
                 end: datetime) -> DoctorVisitStats:
    """زيارات الطبيب في الفترة: جدد/عائدون/طوارئ + الإلغاء ومتوسط الانتظار.

    «جديد» = لم يكن لهذا المريض أي موعد سابق مع هذا الطبيب قبل بداية الفترة،
    و«عائد» = العكس. الطوارئ = كلمة «طوارئ» في بداية سبب الزيارة.
    متوسط الانتظار = الفارق بين وقت الوصول والموعد للمواعيد التي وصلت فعلًا.
    """
    rows = (db.query(Appointment)
            .filter(Appointment.doctor_id == doctor_id,
                    Appointment.appointment_date >= start,
                    Appointment.appointment_date < end)
            .with_entities(Appointment.patient_id, Appointment.status,
                           Appointment.reason, Appointment.appointment_date,
                           Appointment.checked_in_at).all())

    total = len(rows)
    cancelled = sum(1 for r in rows
                    if getattr(r.status, "value", r.status) == "cancelled")
    emergency = sum(1 for r in rows
                    if (r.reason or "").strip().startswith("طوارئ"))

    # مريض واحد قد يحجز أكثر من موعد في الفترة ⇒ نعدّه مرّة واحدة
    patient_ids = {r.patient_id for r in rows}
    returning = sum(
        1 for pid in patient_ids
        if db.query(Appointment.id).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.patient_id == pid,
            Appointment.appointment_date < start).first()
    )

    # الانتظار: الوصول بعد موعده ⇒ فارق موجب بالدقائق
    waits = [(r.checked_in_at - r.appointment_date).total_seconds() / 60.0
             for r in rows
             if r.checked_in_at and r.checked_in_at > r.appointment_date]

    return DoctorVisitStats(
        new_patients=len(patient_ids) - returning,
        returning_patients=returning,
        emergency_visits=emergency,
        cancelled=cancelled,
        cancel_rate=round(cancelled / total, 4) if total else 0.0,
        avg_wait_minutes=round(sum(waits) / len(waits), 1) if waits else 0.0,
    )


def _order_stats(db: Session, doctor_id: int, start: datetime,
                 end: datetime, top: int = 5) -> DoctorOrderStats:
    """أكثر الأدوية والفحوصات التي طلبها الطبيب خلال الفترة."""
    rx_ids = [r[0] for r in db.query(Prescription.id).filter(
        Prescription.doctor_id == doctor_id,
        Prescription.created_at >= start,
        Prescription.created_at < end,
    ).all()]
    meds = []
    if rx_ids:
        meds = (db.query(Medication.name, func.sum(PrescriptionItem.quantity))
                .join(PrescriptionItem,
                      PrescriptionItem.medication_id == Medication.id)
                .filter(PrescriptionItem.prescription_id.in_(rx_ids))
                .group_by(Medication.name)
                .order_by(func.sum(PrescriptionItem.quantity).desc())
                .limit(top).all())

    labs = (db.query(LabOrder.test_name, func.count(LabOrder.id))
            .filter(LabOrder.doctor_id == doctor_id,
                    LabOrder.ordered_at >= start,
                    LabOrder.ordered_at < end)
            .group_by(LabOrder.test_name)
            .order_by(func.count(LabOrder.id).desc())
            .limit(top).all())

    lab_count = (db.query(func.count(LabOrder.id))
                 .filter(LabOrder.doctor_id == doctor_id,
                         LabOrder.ordered_at >= start,
                         LabOrder.ordered_at < end).scalar() or 0)

    return DoctorOrderStats(
        top_medications=[{"name": n, "quantity": int(c or 0)} for n, c in meds],
        top_lab_tests=[{"name": n, "count": int(c or 0)} for n, c in labs],
        prescriptions_count=len(rx_ids),
        lab_orders_count=int(lab_count),
    )


def _ledger_for(db: Session, doctor: Doctor, period: str, start: datetime,
                end: datetime) -> DoctorLedger:
    """كشف حساب الطبيب: إيراد فواتير مرضاه ← المستحق بالعمولة ← المتبقي.

    الإيراد = صافي فواتير مرضى الطبيب (الصافي بعد الخصم، ثم تُضاف عليه
    الضريبة) المنشأة داخل الفترة. المستحق = مجموع بنود العمولة النشطة،
    وكل بند يُحسب على أساسه: **النسبة** من الإيراد الكلي، و**القيمة الثابتة**
    لكل فاتورة (rate × عدد الفواتير) — فالبندان لا يتضاعفان. المحوَّل =
    تحويلات الفترة نفسها، والمتبقي = المستحق − المحوَّل.
    """
    patient_ids = {r[0] for r in db.query(Appointment.patient_id).filter(
        Appointment.doctor_id == doctor.id,
        Appointment.appointment_date >= start,
        Appointment.appointment_date < end,
    ).all()}

    revenue = 0.0
    invoices_count = 0
    if patient_ids:
        inv = (db.query(Invoice)
               .filter(Invoice.patient_id.in_(patient_ids),
                       Invoice.created_at >= start,
                       Invoice.created_at < end)
               .with_entities(Invoice.amount, Invoice.discount,
                              Invoice.tax_rate).all())
        invoices_count = len(inv)
        for amount, discount, tax in inv:
            net = (amount or 0) - (discount or 0)
            revenue += net + round(net * (tax or 0) / 100.0, 2)

    earned = 0.0
    by_commission: List[dict] = []
    commissions = (db.query(DoctorCommission)
                   .filter(DoctorCommission.doctor_id == doctor.id,
                           DoctorCommission.is_active.is_(True))
                   .order_by(DoctorCommission.service_type).all())
    for c in commissions:
        amount = (round(revenue * (c.rate or 0) / 100.0, 2)
                  if c.billing_type == "percent"
                  else round((c.rate or 0) * invoices_count, 2))
        earned += amount
        by_commission.append({
            "service_type": c.service_type,
            "label": SERVICE_LABELS.get(c.service_type, c.service_type),
            "billing_type": c.billing_type,
            "rate": c.rate,
            "amount": amount,
        })

    paid = db.query(func.sum(DoctorPayout.amount)).filter(
        DoctorPayout.doctor_id == doctor.id,
        DoctorPayout.period == period,
    ).scalar() or 0.0

    return DoctorLedger(
        period=period,
        revenue=round(revenue, 2),
        earned=round(earned, 2),
        paid=round(float(paid), 2),
        balance=round(earned - float(paid), 2),
        invoices_count=invoices_count,
        by_commission=by_commission,
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


@router.get("/performance/report.pdf", summary="تقرير الأداء المقارن PDF")
async def all_doctors_performance_pdf(
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (افتراضي: الشهر الحالي)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """تقرير أداء جميع الأطباء كمستند PDF عربي"""
    from fastapi.responses import Response
    from app.pdf_utils import doctor_report_compare_pdf

    month, start, end = _month_bounds(month)
    doctors = db.query(Doctor).order_by(Doctor.full_name.asc()).all()
    rows = []
    for d in doctors:
        perf = _performance_for(db, d.id, month, start, end)
        rows.append(DoctorPerformanceRow(
            **perf.model_dump(),
            full_name=d.full_name, specialty=d.specialty,
            is_available=d.is_available,
            department=d.department.name if d.department else None,
        ))
    rows.sort(key=lambda r: (-r.completion_rate, -r.total, r.full_name))
    return Response(
        content=doctor_report_compare_pdf(rows, month),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename=doctors_performance_{month}.pdf"},
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
    if doctor.user_id is not None and not db.query(User).filter(
            User.id == doctor.user_id).first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="حساب المستخدم غير موجود",
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
        sub_specialty=doctor.sub_specialty,
        academic_rank=doctor.academic_rank,
        branch=doctor.branch,
        user_id=doctor.user_id,
        consultation_minutes=doctor.consultation_minutes,
        consultation_fee=doctor.consultation_fee,
        followup_fee=doctor.followup_fee,
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
    if "user_id" in update_data and update_data["user_id"] is not None:
        if not db.query(User).filter(User.id == update_data["user_id"]).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="حساب المستخدم غير موجود",
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
    for e in entries:
        if e.end_time <= e.start_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="وقت النهاية يجب أن يكون بعد وقت البداية",
            )

    # فحص التداخل داخل اليوم نفسه (نوبتان أو أكثر)
    by_day = {}
    for e in entries:
        by_day.setdefault(e.day_of_week, []).append(e)
    for day, day_entries in by_day.items():
        ordered = sorted(day_entries, key=lambda x: x.start_time)
        for prev, nxt in zip(ordered, ordered[1:]):
            if nxt.start_time < prev.end_time:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"نوبتان متداخلتان في يوم {_DAYS[day]}",
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


# ===== شاشة ملف الطبيب (الأقسام الخمسة) =====
@router.get("/{doctor_id}/chart", response_model=DoctorChart,
            summary="ملف الطبيب الكامل (تبويبات الخمسة)")
async def doctor_chart(
    doctor_id: int,
    month: Optional[str] = Query(None, description="الشهر YYYY-MM لإحصاءات الفترة"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """طلب واحد يغذّي التبويبات الخمسة: الملف · الجداول · الصلاحيات · المالية · الأداء.

    الحركات المالية (كشف الحساب) لا تظهر إلا للمدير أو لمن فُعّلت له صلاحية
    `view_doctor_financials` — فلا يطّلع الطبيب على أرقام زملائه.
    """
    doctor = _get_or_404(db, doctor_id)
    period, start, end = _month_bounds(month)
    is_admin = current_user.role == "admin"
    perms = _load_permissions(doctor)

    out = DoctorChart.from_doctor(doctor, perms)
    out.schedules = [DoctorScheduleEntry.model_validate(s)
                     for s in db.query(DoctorSchedule)
                     .filter(DoctorSchedule.doctor_id == doctor_id)
                     .order_by(DoctorSchedule.day_of_week).all()]
    out.shifts = [DoctorShiftInDB.model_validate(s) for s in db.query(DoctorShift)
                  .filter(DoctorShift.doctor_id == doctor_id)
                  .order_by(DoctorShift.shift_date.desc()).all()]
    out.leaves = [DoctorLeaveInDB.model_validate(s) for s in db.query(DoctorLeave)
                  .filter(DoctorLeave.doctor_id == doctor_id)
                  .order_by(DoctorLeave.start_date.desc()).all()]
    out.blocks = [DoctorBlockInDB.model_validate(b) for b in db.query(DoctorBlock)
                  .filter(DoctorBlock.doctor_id == doctor_id)
                  .order_by(DoctorBlock.block_date.desc()).all()]
    out.commissions = [DoctorCommissionInDB.model_validate(c)
                       for c in db.query(DoctorCommission)
                       .filter(DoctorCommission.doctor_id == doctor_id)
                       .order_by(DoctorCommission.service_type).all()]
    out.payouts = [DoctorPayoutInDB.model_validate(p) for p in db.query(DoctorPayout)
                   .filter(DoctorPayout.doctor_id == doctor_id)
                   .order_by(DoctorPayout.paid_at.desc()).all()]

    out.visits = _visit_stats(db, doctor_id, start, end)
    out.orders = _order_stats(db, doctor_id, start, end)

    if is_admin or perms.view_doctor_financials:
        out.ledger = _ledger_for(db, doctor, period, start, end)
    else:
        out.ledger = DoctorLedger(period=period)
    return out


@router.put("/{doctor_id}/profile", response_model=DoctorChart,
            summary="حفظ الملف المهني والصلاحيات")
async def update_doctor_profile(
    doctor_id: int, body: DoctorProfileUpdate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """يحفظ الملف المهني — للمدير أو الطبيب نفسه (كما في التوافر والنوبات)."""
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "تعديل ملف هذا الطبيب")

    data = body.model_dump(exclude_unset=True, exclude={"permissions"})
    if "user_id" in data and data["user_id"] is not None:
        if not db.query(User).filter(User.id == data["user_id"]).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="حساب المستخدم غير موجود",
            )
    if "email" in data and data["email"]:
        clash = db.query(Doctor).filter(
            Doctor.email == data["email"], Doctor.id != doctor_id).first()
        if clash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="هذا البريد الإلكتروني مستخدم من قبل طبيب آخر",
            )

    for field, value in data.items():
        setattr(doctor, field, value)
    if body.permissions is not None:
        doctor.permissions = json.dumps(
            body.permissions.model_dump(), ensure_ascii=False)

    db.commit()
    db.refresh(doctor)
    return await doctor_chart(doctor_id, month=None, db=db, current_user=current_user)


# ===== مناوبات الطوارئ/التنويم/الأونكول =====
@router.get("/{doctor_id}/shifts", response_model=List[DoctorShiftInDB],
            summary="مناوبات الطبيب (طوارئ/تنويم/أونكول)")
async def list_shifts(doctor_id: int, db: Session = Depends(get_db),
                      _=Depends(get_current_user)):
    _get_or_404(db, doctor_id)
    return (db.query(DoctorShift).filter(DoctorShift.doctor_id == doctor_id)
            .order_by(DoctorShift.shift_date.desc(), DoctorShift.start_time)
            .all())


@router.post("/{doctor_id}/shifts", response_model=DoctorShiftInDB,
             status_code=status.HTTP_201_CREATED, summary="إضافة مناوبة")
async def add_shift(doctor_id: int, body: DoctorShiftCreate,
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """إضافة مناوبة — للمدير أو الطبيب نفسه، مع رفض النهاية قبل البداية."""
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "إضافة مناوبة لهذا الطبيب")
    if body.end_time <= body.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="وقت النهاية يجب أن يكون بعد وقت البداية",
        )
    row = DoctorShift(
        doctor_id=doctor_id, shift_type=body.shift_type,
        shift_date=body.shift_date, start_time=body.start_time,
        end_time=body.end_time, location=body.location, notes=body.notes,
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{doctor_id}/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف مناوبة")
async def delete_shift(doctor_id: int, shift_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "حذف مناوبة لهذا الطبيب")
    row = db.query(DoctorShift).filter(
        DoctorShift.id == shift_id, DoctorShift.doctor_id == doctor_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="المناوبة غير موجودة")
    db.delete(row)
    db.commit()
    return None


# ===== الإجازات وأيام حظر الحجز =====
@router.get("/{doctor_id}/leaves", response_model=List[DoctorLeaveInDB],
            summary="إجازات الطبيب")
async def list_leaves(doctor_id: int, db: Session = Depends(get_db),
                      _=Depends(get_current_user)):
    _get_or_404(db, doctor_id)
    return (db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id)
            .order_by(DoctorLeave.start_date.desc()).all())


@router.post("/{doctor_id}/leaves", response_model=DoctorLeaveInDB,
             status_code=status.HTTP_201_CREATED, summary="تسجيل إجازة")
async def add_leave(doctor_id: int, body: DoctorLeaveCreate,
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """تسجيل إجازة — النهاية يجب أن تكون بعد البداية (أو مساوية)."""
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "تسجيل إجازة لهذا الطبيب")
    if body.end_date < body.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="تاريخ نهاية الإجازة يجب أن يكون بعد تاريخ البداية",
        )
    row = DoctorLeave(
        doctor_id=doctor_id, start_date=body.start_date, end_date=body.end_date,
        reason=body.reason, is_approved=body.is_approved,
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{doctor_id}/leaves/{leave_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف إجازة")
async def delete_leave(doctor_id: int, leave_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "حذف إجازة لهذا الطبيب")
    row = db.query(DoctorLeave).filter(
        DoctorLeave.id == leave_id, DoctorLeave.doctor_id == doctor_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="الإجازة غير موجودة")
    db.delete(row)
    db.commit()
    return None


@router.get("/{doctor_id}/blocks", response_model=List[DoctorBlockInDB],
            summary="أيام حظر الحجز")
async def list_blocks(doctor_id: int, db: Session = Depends(get_db),
                      _=Depends(get_current_user)):
    _get_or_404(db, doctor_id)
    return (db.query(DoctorBlock).filter(DoctorBlock.doctor_id == doctor_id)
            .order_by(DoctorBlock.block_date.desc()).all())


@router.post("/{doctor_id}/blocks", response_model=DoctorBlockInDB,
             status_code=status.HTTP_201_CREATED, summary="حظر الحجز في يوم")
async def add_block(doctor_id: int, body: DoctorBlockCreate,
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """حظر الحجز في يوم (أو جزء منه) — بلا وقت = اليوم كامل."""
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "حظر الحجز لهذا الطبيب")
    if (body.start_time is None) != (body.end_time is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="حدّد وقتي البداية والنهاية معًا، أو اتركهما فارغين ليوم كامل",
        )
    if body.start_time and body.end_time and body.end_time <= body.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="وقت النهاية يجب أن يكون بعد وقت البداية",
        )
    row = DoctorBlock(
        doctor_id=doctor_id, block_date=body.block_date,
        start_time=body.start_time, end_time=body.end_time,
        reason=body.reason, created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{doctor_id}/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="رفع حظر الحجز")
async def delete_block(doctor_id: int, block_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "رفع حظر الحجز لهذا الطبيب")
    row = db.query(DoctorBlock).filter(
        DoctorBlock.id == block_id, DoctorBlock.doctor_id == doctor_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="يوم الحظر غير موجود")
    db.delete(row)
    db.commit()
    return None


# ===== العمولات وكشف الحساب =====
@router.get("/{doctor_id}/commissions", response_model=List[DoctorCommissionInDB],
            summary="نسب وقيم عمولة الطبيب")
async def list_commissions(doctor_id: int, db: Session = Depends(get_db),
                           _=Depends(get_current_user)):
    _get_or_404(db, doctor_id)
    return (db.query(DoctorCommission)
            .filter(DoctorCommission.doctor_id == doctor_id)
            .order_by(DoctorCommission.service_type).all())


@router.put("/{doctor_id}/commissions", response_model=List[DoctorCommissionInDB],
            summary="استبدال بنود عمولة الطبيب")
async def put_commissions(doctor_id: int, body: List[DoctorCommissionCreate],
                          db: Session = Depends(get_db),
                          _: User = Depends(require_admin)):
    """استبدال كل بنود العمولة — النسبة يجب أن تكون 0..100 (المدير فقط).

    استبدال كامل لا تمييز: تكرار نوع الخدمة داخل الطلب يُرفض 400 لأن
    `uq_doctor_commission_service` يفرض التفرّد أصلًا.
    """
    _get_or_404(db, doctor_id)
    seen = set()
    for c in body:
        if c.service_type in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("نوع الخدمة مكرر: "
                        + SERVICE_LABELS.get(c.service_type, c.service_type)),
            )
        seen.add(c.service_type)
        if c.billing_type == "percent" and c.rate > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="النسبة المئوية يجب أن تكون بين 0 و 100",
            )

    db.query(DoctorCommission).filter(
        DoctorCommission.doctor_id == doctor_id).delete(synchronize_session=False)
    for c in body:
        db.add(DoctorCommission(
            doctor_id=doctor_id, service_type=c.service_type,
            billing_type=c.billing_type, rate=c.rate, is_active=c.is_active))
    db.commit()
    return (db.query(DoctorCommission)
            .filter(DoctorCommission.doctor_id == doctor_id)
            .order_by(DoctorCommission.service_type).all())


@router.get("/{doctor_id}/ledger", response_model=DoctorLedger,
            summary="كشف حساب الطبيب (إيراد/مستحق/محوَّل)")
async def doctor_ledger(
    doctor_id: int,
    month: Optional[str] = Query(None, description="الشهر YYYY-MM (افتراضي: الحالي)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """كشف حساب فترة — للمدير أو من فُعّلت له صلاحية view_doctor_financials."""
    doctor = _get_or_404(db, doctor_id)
    if current_user.role != "admin" and not _load_permissions(doctor).view_doctor_financials:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا تملك صلاحية الاطلاع على كشف الحساب — للمدير فقط",
        )
    period, start, end = _month_bounds(month)
    return _ledger_for(db, doctor, period, start, end)


@router.get("/{doctor_id}/payouts", response_model=List[DoctorPayoutInDB],
            summary="تحويلات الطبيب المستحقة")
async def list_payouts(doctor_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    doctor = _get_or_404(db, doctor_id)
    if current_user.role != "admin" and not _load_permissions(doctor).view_doctor_financials:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا تملك صلاحية الاطلاع على التحويلات — للمدير فقط",
        )
    return (db.query(DoctorPayout).filter(DoctorPayout.doctor_id == doctor_id)
            .order_by(DoctorPayout.paid_at.desc()).all())


@router.post("/{doctor_id}/payouts", response_model=DoctorPayoutInDB,
             status_code=status.HTTP_201_CREATED, summary="تسجيل تحويل للطبيب")
async def add_payout(doctor_id: int, body: DoctorPayoutCreate,
                     db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """تسجيل تحويل (المدير فقط) — يُرفض إن تجاوز رصيد كشف حساب الفترة."""
    doctor = _get_or_404(db, doctor_id)
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="تسجيل التحويلات للمدير فقط",
        )
    if not (len(body.period) == 7 and body.period[4] == "-"
            and body.period[:4].isdigit() and body.period[5:7].isdigit()
            and 1 <= int(body.period[5:7]) <= 12):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period يجب أن يكون بصيغة YYYY-MM مثل 2026-09",
        )

    year, mon = int(body.period[:4]), int(body.period[5:7])
    start = datetime(year, mon, 1)
    end = datetime(year + 1, 1, 1) if mon == 12 else datetime(year, mon + 1, 1)
    ledger = _ledger_for(db, doctor, body.period, start, end)
    available = round(ledger.earned - ledger.paid, 2)
    if round(body.amount, 2) > available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"المبلغ يتجاوز الرصيد المتاح ({available:.2f}) "
                    f"في كشف حساب {body.period}"),
        )

    row = DoctorPayout(
        doctor_id=doctor_id, amount=body.amount, period=body.period,
        method=body.method, reference=body.reference, note=body.note,
        paid_at=body.paid_at, created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ===== التوقيع الإلكتروني والختم الطبي =====
# مسارات صريحة لكل نوع (لا «/{doctor_id}/{kind}») حتى لا يلتقط المتغيّر
# مسارات ثابتة مثل /shifts قبل أن تصل إلى دالّته.
async def _save_stamp(doctor_id: int, kind: str, file: UploadFile, db: Session,
                      current_user: User) -> Doctor:
    _check_kind(kind)
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "رفع ختم لهذا الطبيب")
    stored = _store_stamp(doctor_id, kind, file)
    if kind == "signature":
        doctor.signature_path = stored
    else:
        doctor.stamp_path = stored
    db.commit()
    db.refresh(doctor)
    return doctor


@router.post("/{doctor_id}/signature", response_model=DoctorInDB,
             summary="رفع التوقيع الإلكتروني")
async def upload_signature(doctor_id: int,
                           file: UploadFile = File(..., description="صورة (حد أقصى 2MB)"),
                           db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """رفع صورة التوقيع الإلكتروني — للمدير أو الطبيب نفسه.

    تُحفظ في مجلد uploads فيظهر المسار في نافذة الملف. الصيغ: png/jpg/jpeg/webp.
    """
    return await _save_stamp(doctor_id, "signature", file, db, current_user)


@router.post("/{doctor_id}/stamp", response_model=DoctorInDB,
             summary="رفع الختم الطبي")
async def upload_stamp(doctor_id: int,
                       file: UploadFile = File(..., description="صورة (حد أقصى 2MB)"),
                       db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """رفع صورة الختم الطبي — تظهر تلقائيًا على الوصفات والتقارير."""
    return await _save_stamp(doctor_id, "stamp", file, db, current_user)


@router.delete("/{doctor_id}/signature", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف التوقيع الإلكتروني")
async def delete_signature(doctor_id: int, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "حذف توقيع هذا الطبيب")
    doctor.signature_path = None
    db.commit()
    return None


@router.delete("/{doctor_id}/stamp", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف الختم الطبي")
async def delete_stamp(doctor_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    doctor = _get_or_404(db, doctor_id)
    _require_admin_or_self(current_user, doctor, "حذف ختم هذا الطبيب")
    doctor.stamp_path = None
    db.commit()
    return None


@router.get("/{doctor_id}/{kind}/image", summary="عرض صورة التوقيع أو الختم")
async def get_stamp_image(doctor_id: int, kind: str, db: Session = Depends(get_db),
                          _=Depends(get_current_user)):
    """يعيد ملف الصورة مباشرة — 404 إن لم يكن مرفوعًا أو مفقودًا من القرص."""
    _check_kind(kind)
    doctor = _get_or_404(db, doctor_id)
    stored = doctor.signature_path if kind == "signature" else doctor.stamp_path
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد توقيع مرفوع" if kind == "signature" else "لا يوجد ختم مرفوع",
        )
    path = os.path.join(UPLOAD_DIR, stored)
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ملف الصورة مفقود على القرص",
        )
    return FileResponse(path)


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
