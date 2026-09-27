"""إدارة العيادات: سجل نقاط الخدمة أمام المريض.

**قرار التصميم (منع التكرار):** العيادة *سجل* يعرّف نقطة الخدمة أمام
المريض (كود · تخصص · موقع · طبيب مسؤول · رسوم كشف · حالة). أما الخدمات
وجداول الدوام فهي بيانات تشغيلية معرّفة أصلًا في مركز الأقسام
(`DepartmentService` / `DepartmentSchedule`)، فلا تُنسخ هنا: العيادة ترتبط
بقسم عبر `department_id` وتقرأ وتكتب نفس الجداول. يبقى لكل وحدة تشغيلية
كتالوج خدمات واحد وجدول دوام واحد فقط.

قواعد السلوك:
- عيادة بلا قسم مرتبط: تُسجَّل نفسها فقط، وتُبلّغ بوضوح عند محاولة إضافة
  خدمة أو وردية (خطأ 400 برسالة إرشادية) بدل إنشاء جداول موازية.
- كود العيادة فريد على مستوى النظام ⇒ تكرار الكود 409.
- قسم واحد لا يخدم عيادتين ⇒ منع الازدواج التشغيلي عند الربط.
- وردية الدوام: اليوم + الفترة (صباحية/مسائية) فريدة داخل القسم ⇒ تكرار 409.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Appointment, Clinic, Department, DepartmentSchedule, DepartmentService, Doctor,
    User,
)
from app.schemas import (
    ClinicIn, ClinicOut, ClinicScheduleIn, ClinicScheduleOut, ClinicServiceIn,
    ClinicServiceOut, ClinicSummaryOut, ClinicUpdate,
)

router = APIRouter(prefix="/clinics", tags=["Clinics"])

CLINIC_STATUSES = ("active", "closed")
SESSIONS = ("morning", "evening")
SESSION_NAMES = {"morning": "صباحية", "evening": "مسائية"}
DAYS_AR = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]


# ===== أدوات =====
def _linked_department(db: Session, clinic: Clinic) -> Department:
    """القسم الذي تُدار عبره خدمات العيادة ودوامها، أو 400 برسالة واضحة."""
    if not clinic.department_id:
        raise HTTPException(
            400, "اربط العيادة بقسم أولًا من شاشة العيادات لتتمكن من إدارة الخدمات والدوام")
    dept = db.query(Department).filter(Department.id == clinic.department_id).first()
    if not dept:
        raise HTTPException(404, "القسم المرتبط بالعيادة غير موجود")
    return dept


def _service_out(row: DepartmentService) -> ClinicServiceOut:
    return ClinicServiceOut(
        id=row.id, department_id=row.department_id, code=row.code, name=row.name,
        price=round(float(row.price or 0), 2),
        doctor_share_pct=float(row.doctor_share_pct or 0),
        insurance_pct=float(row.insurance_pct or 0), is_active=bool(row.is_active))


def _slot_out(row: DepartmentSchedule) -> ClinicScheduleOut:
    return ClinicScheduleOut(
        id=row.id, department_id=row.department_id, day_of_week=row.day_of_week,
        day_name=DAYS_AR[row.day_of_week] if 0 <= row.day_of_week < 7 else "—",
        session=row.session, session_name=SESSION_NAMES.get(row.session, row.session),
        open_time=row.open_time, close_time=row.close_time,
        room_name=row.room_name, max_patients=int(row.max_patients or 0))


def _clinic_out(row: Clinic, db: Session) -> ClinicOut:
    """يجمع سجل العيادة مع خدمات ودوام قسمها المرتبط (بلا نسخ)."""
    services: List[ClinicServiceOut] = []
    schedule: List[ClinicScheduleOut] = []
    if row.department_id:
        services = [_service_out(s) for s in db.query(DepartmentService).filter(
            DepartmentService.department_id == row.department_id)
            .order_by(DepartmentService.id).all()]
        rows = db.query(DepartmentSchedule).filter(
            DepartmentSchedule.department_id == row.department_id).all()
        rows.sort(key=lambda x: (x.day_of_week, 0 if x.session == "morning" else 1,
                                 x.open_time))
        schedule = [_slot_out(s) for s in rows]
    return ClinicOut(
        id=row.id, code=row.code, name=row.name, specialty=row.specialty,
        department_id=row.department_id,
        department_name=row.department.name if row.department else None,
        lead_doctor_id=row.lead_doctor_id,
        lead_doctor_name=row.doctor.full_name if row.doctor else None,
        location=row.location, phone=row.phone,
        consultation_fee=round(float(row.consultation_fee or 0), 2),
        default_duration=row.default_duration, status=row.status, notes=row.notes,
        created_at=row.created_at, services=services, schedule=schedule,
        services_count=len(services), schedule_count=len(schedule),
        weekly_capacity=sum(s.max_patients for s in schedule))


@router.get("/", response_model=List[ClinicOut],
            summary="قائمة العيادات بخدمات أقسامها ودوامها")
def list_clinics(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                 specialty: Optional[str] = Query(None),
                 status_filter: Optional[str] = Query(None, alias="status"),
                 q: Optional[str] = Query(None, description="بحث بالاسم أو الرمز")):
    query = db.query(Clinic)
    if specialty:
        query = query.filter(Clinic.specialty == specialty)
    if status_filter:
        query = query.filter(Clinic.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(Clinic.name.ilike(like) | Clinic.code.ilike(like))
    return [_clinic_out(c, db) for c in query.order_by(Clinic.id).all()]


@router.post("/", response_model=ClinicOut, status_code=status.HTTP_201_CREATED,
             summary="إنشاء سجل عيادة")
def create_clinic(payload: ClinicIn, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    if db.query(Clinic).filter(Clinic.code == payload.code).first():
        raise HTTPException(409, "كود العيادة مستخدم مسبقًا")
    if payload.status not in CLINIC_STATUSES:
        raise HTTPException(400, "حالة العيادة active أو closed")
    if payload.department_id:
        if not db.query(Department).filter(
                Department.id == payload.department_id).first():
            raise HTTPException(404, "القسم غير موجود")
        taken = db.query(Clinic).filter(
            Clinic.department_id == payload.department_id).first()
        if taken:
            raise HTTPException(
                409, f"القسم مرتبط بعيادة أخرى ({taken.name}) — لا تكرار تشغيلي")
    if payload.lead_doctor_id and not db.query(Doctor).filter(
            Doctor.id == payload.lead_doctor_id).first():
        raise HTTPException(404, "الطبيب غير موجود")
    row = Clinic(**payload.model_dump(), created_at=datetime.now())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _clinic_out(row, db)


@router.get("/summary", response_model=ClinicSummaryOut,
            summary="ملخّص العيادات: السعة والدوام والرسوم")
def clinics_summary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """رقم تشغيلي واحد: كم عيادة نشطة، وكم منها بلا قسم، وكم سعة أسبوعية."""
    today = datetime.now().date()
    clinics = db.query(Clinic).all()
    dept_ids = {c.department_id for c in clinics if c.department_id}
    services = schedule_slots = weekly = 0
    if dept_ids:
        services = (db.query(func.count(DepartmentService.id))
                    .filter(DepartmentService.department_id.in_(dept_ids)).scalar() or 0)
        slots = (db.query(DepartmentSchedule)
                 .filter(DepartmentSchedule.department_id.in_(dept_ids)).all())
        schedule_slots = len(slots)
        weekly = sum(int(s.max_patients or 0) for s in slots)
    appts = (db.query(func.count(Appointment.id))
             .filter(func.date(Appointment.appointment_date) == today).scalar() or 0)
    return ClinicSummaryOut(
        clinics=len(clinics),
        active=sum(1 for c in clinics if c.status == "active"),
        closed=sum(1 for c in clinics if c.status == "closed"),
        unlinked=sum(1 for c in clinics if not c.department_id),
        services=int(services), schedule_slots=schedule_slots,
        weekly_capacity=weekly, appointments_today=int(appts),
        consultation_fees_total=round(
            sum(float(c.consultation_fee or 0) for c in clinics), 2))


@router.get("/specialties", response_model=List[str], summary="التخصصات المتاحة")
def list_specialties(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(Clinic.specialty).filter(
        Clinic.specialty.isnot(None), Clinic.specialty != "").distinct().all()
    return sorted(r[0] for r in rows if r[0])


@router.get("/{clinic_id}", response_model=ClinicOut, summary="تفاصيل عيادة")
def get_clinic(clinic_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    row = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not row:
        raise HTTPException(404, "العيادة غير موجودة")
    return _clinic_out(row, db)


@router.put("/{clinic_id}", response_model=ClinicOut, summary="تعديل بيانات عيادة")
def update_clinic(clinic_id: int, payload: ClinicUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    row = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not row:
        raise HTTPException(404, "العيادة غير موجودة")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in CLINIC_STATUSES:
        raise HTTPException(400, "حالة العيادة active أو closed")
    if data.get("department_id"):
        if not db.query(Department).filter(
                Department.id == data["department_id"]).first():
            raise HTTPException(404, "القسم غير موجود")
        taken = db.query(Clinic).filter(
            Clinic.department_id == data["department_id"],
            Clinic.id != clinic_id).first()
        if taken:
            raise HTTPException(
                409, f"القسم مرتبط بعيادة أخرى ({taken.name}) — لا تكرار تشغيلي")
    if data.get("lead_doctor_id") and not db.query(Doctor).filter(
            Doctor.id == data["lead_doctor_id"]).first():
        raise HTTPException(404, "الطبيب غير موجود")
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _clinic_out(row, db)


@router.delete("/{clinic_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف سجل عيادة (تبقى خدمات القسم ودوامه)")
def delete_clinic(clinic_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    """حذف العيادة لا يمسّ القسم المرتبط: الخدمات والدوام ملك القسم."""
    row = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not row:
        raise HTTPException(404, "العيادة غير موجودة")
    db.delete(row)
    db.commit()
    return None



# ===== خدمات العيادة (كتالوج القسم المرتبط — نفس جدول مركز الأقسام) =====
@router.get("/{clinic_id}/services", response_model=List[ClinicServiceOut],
            summary="خدمات القسم المرتبط بالعيادة")
def list_clinic_services(clinic_id: int, db: Session = Depends(get_db),
                         _: User = Depends(get_current_user)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    if not clinic.department_id:
        return []
    rows = db.query(DepartmentService).filter(
        DepartmentService.department_id == clinic.department_id).order_by(
        DepartmentService.id).all()
    return [_service_out(r) for r in rows]


@router.post("/{clinic_id}/services", response_model=ClinicServiceOut, status_code=201,
             summary="إضافة خدمة إلى كتالوج قسم العيادة")
def add_clinic_service(clinic_id: int, payload: ClinicServiceIn,
                       db: Session = Depends(get_db), user: User = Depends(require_admin)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    dept = _linked_department(db, clinic)
    total = payload.doctor_share_pct + payload.insurance_pct
    if total > 100:
        raise HTTPException(400, "مجموع حصة الطبيب والتأمين لا يتجاوز 100%")
    if payload.code and db.query(DepartmentService).filter(
            DepartmentService.department_id == dept.id,
            DepartmentService.code == payload.code).first():
        raise HTTPException(409, "كود الخدمة مستخدم في هذا القسم")
    row = DepartmentService(department_id=dept.id, code=payload.code,
                            name=payload.name.strip(), price=payload.price,
                            doctor_share_pct=payload.doctor_share_pct,
                            insurance_pct=payload.insurance_pct,
                            procedure_note=payload.procedure_note,
                            is_active=payload.is_active)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _service_out(row)


@router.put("/{clinic_id}/services/{service_id}", response_model=ClinicServiceOut,
            summary="تعديل خدمة في كتالوج قسم العيادة")
def update_clinic_service(clinic_id: int, service_id: int, payload: ClinicServiceIn,
                          db: Session = Depends(get_db), user: User = Depends(require_admin)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    dept = _linked_department(db, clinic)
    row = db.query(DepartmentService).filter(
        DepartmentService.id == service_id,
        DepartmentService.department_id == dept.id).first()
    if not row:
        raise HTTPException(404, "الخدمة غير موجودة")
    data = payload.model_dump()
    if data["doctor_share_pct"] + data["insurance_pct"] > 100:
        raise HTTPException(400, "مجموع حصة الطبيب والتأمين لا يتجاوز 100%")
    for key, value in data.items():
        setattr(row, key, value)
    row.name = row.name.strip()
    db.commit()
    db.refresh(row)
    return _service_out(row)


@router.delete("/{clinic_id}/services/{service_id}", status_code=204,
               summary="حذف خدمة من كتالوج قسم العيادة")
def delete_clinic_service(clinic_id: int, service_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_admin)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    dept = _linked_department(db, clinic)
    row = db.query(DepartmentService).filter(
        DepartmentService.id == service_id,
        DepartmentService.department_id == dept.id).first()
    if not row:
        raise HTTPException(404, "الخدمة غير موجودة")
    db.delete(row)
    db.commit()
    return None


# ===== جدول دوام العيادة (جدول القسم المرتبط — نفس جدول مركز الأقسام) =====
@router.get("/{clinic_id}/schedule", response_model=List[ClinicScheduleOut],
            summary="جدول دوام القسم المرتبط بالعيادة")
def list_clinic_schedule(clinic_id: int, db: Session = Depends(get_db),
                         _: User = Depends(get_current_user)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    if not clinic.department_id:
        return []
    rows = db.query(DepartmentSchedule).filter(
        DepartmentSchedule.department_id == clinic.department_id).all()
    rows.sort(key=lambda x: (x.day_of_week, 0 if x.session == "morning" else 1,
                             x.open_time))
    return [_slot_out(r) for r in rows]


@router.post("/{clinic_id}/schedule", response_model=ClinicScheduleOut, status_code=201,
             summary="إضافة وردية دوام لعيادة")
def add_clinic_slot(clinic_id: int, payload: ClinicScheduleIn,
                    db: Session = Depends(get_db), user: User = Depends(require_admin)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    dept = _linked_department(db, clinic)
    if payload.session not in SESSIONS:
        raise HTTPException(400, "الفترة morning أو evening")
    if payload.open_time >= payload.close_time:
        raise HTTPException(400, "وقت الفتح قبل وقت الإغلاق مطلوب")
    clash = db.query(DepartmentSchedule).filter(
        DepartmentSchedule.department_id == dept.id,
        DepartmentSchedule.day_of_week == payload.day_of_week,
        DepartmentSchedule.session == payload.session).first()
    if clash:
        raise HTTPException(409, "الفترة مسجّلة ليوم "
                                 + DAYS_AR[payload.day_of_week])
    row = DepartmentSchedule(
        department_id=dept.id, day_of_week=payload.day_of_week,
        session=payload.session, open_time=payload.open_time,
        close_time=payload.close_time, room_name=payload.room_name,
        max_patients=payload.max_patients)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _slot_out(row)


@router.delete("/{clinic_id}/schedule/{slot_id}", status_code=204,
               summary="حذف وردية من دوام العيادة")
def delete_clinic_slot(clinic_id: int, slot_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "العيادة غير موجودة")
    dept = _linked_department(db, clinic)
    row = db.query(DepartmentSchedule).filter(
        DepartmentSchedule.id == slot_id,
        DepartmentSchedule.department_id == dept.id).first()
    if not row:
        raise HTTPException(404, "الوردية غير موجودة")
    db.delete(row)
    db.commit()
    return None
