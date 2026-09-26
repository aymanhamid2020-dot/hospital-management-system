"""مركز الأقسام —(directory & hub): الهيكل والكادر والغرف والخدمات والجداول والتقارير.

ستة أقسام تخدم شاشة «الأقسام»:
  1. دليل الأقسام والهيكل   الأقسام الفرعية + نوع القسم + الفعّالة
  2. الأطباء والكادر        الأطباء المنتسبون + الكادر المساند + رئيس القسم
  3. الغرف والأسرّة          الغرف وفئاتها + توزيع الأسرّة + حجوزاتها (بدل شاشة منفصلة)
  4. الخدمات والأسعار       كتالوج الخدمات بتسعيرها ونسبتَي الطبيب والتأمين
  5. الجداول والمواعيد      جدول تشغيل العيادة + حجز غرف العمليات/الفحص
  6. التقارير والإحصائيات   الإشغال + الإيراد/المصروف + إنتاجية الكادر
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Appointment, Bed, BedStatus, Department, DepartmentRoom, DepartmentRoomBooking,
    DepartmentSchedule, DepartmentService, DepartmentStaff, Doctor, Invoice, Staff,
    User,
)
from app.schemas import (
    DepartmentHodIn, DepartmentRoomBookingIn, DepartmentRoomBookingOut,
    DepartmentRoomCreate, DepartmentRoomOut, DepartmentScheduleIn,
    DepartmentScheduleOut, DepartmentServiceIn, DepartmentServiceOut,
    DepartmentStaffIn, DepartmentStaffOut, DepartmentUpdateExtra,
)

router = APIRouter(prefix="/department-hub", tags=["Department Hub"])

DEPT_TYPES = ("clinical", "diagnostic", "administrative", "supportive")
ROOM_CATEGORIES = ("royal", "private", "shared", "icu", "er", "operating")
DEPT_TYPE_AR = {"clinical": "طبي/عيادي", "diagnostic": "تشخيصي",
                "administrative": "إداري", "supportive": "خدمي/مساند"}
ROOM_CAT_AR = {"royal": "جناح ملكي", "private": "غرفة خاصة", "shared": "غرفة مشتركة",
               "icu": "عناية مركزة", "er": "طوارئ/صدمات", "operating": "غرف عمليات"}
DAYS_AR = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]


def _dept(db: Session, dept_id: int) -> Department:
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(404, "القسم غير موجود")
    return dept


def _check_type(value: str, allowed, label: str) -> str:
    value = (value or "").strip().lower()
    if value not in allowed:
        raise HTTPException(400, f"{label} يجب أن يكون من: {', '.join(allowed)}")
    return value


# ===== 1) دليل الأقسام والهيكل =====
@router.get("/directory", summary="دليل الأقسام: الفعّالة والفرعية والنوع")
def directory(include_inactive: bool = Query(False),
              db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """شجرة الأقسام: كل قسم مع أبوابه الفرعية وأرقامه السريعة."""
    q = db.query(Department)
    if not include_inactive:
        q = q.filter(Department.is_active.is_(True))
    depts = q.order_by(Department.name).all()
    by_parent = {}
    for d in depts:
        by_parent.setdefault(d.parent_id, []).append(d)
    visible = {d.id for d in depts}
    out = []
    for d in depts:
        if d.parent_id and d.parent_id in visible:
            continue                       # يُعرض ضمن أبوابه لا كجذر
        out.append(_node(db, d, by_parent, 0))
    return out


def _node(db: Session, dept: Department, by_parent: dict, depth: int) -> dict:
    doctors = db.query(Doctor).filter(Doctor.department_id == dept.id).count()
    beds = db.query(Bed).filter(Bed.department_id == dept.id).all()
    return {
        "id": dept.id, "name": dept.name, "floor": dept.floor,
        "description": dept.description, "dept_type": dept.dept_type,
        "dept_type_ar": DEPT_TYPE_AR.get(dept.dept_type, dept.dept_type),
        "is_active": dept.is_active, "head_doctor_id": dept.head_doctor_id,
        "monthly_operating_cost": dept.monthly_operating_cost,
        "doctors_count": doctors, "beds_count": len(beds),
        "beds_occupied": sum(1 for b in beds if b.status == BedStatus.OCCUPIED),
        "rooms_count": db.query(DepartmentRoom).filter(
            DepartmentRoom.department_id == dept.id).count(),
        "services_count": db.query(DepartmentService).filter(
            DepartmentService.department_id == dept.id).count(),
        "depth": depth,
        "children": [_node(db, child, by_parent, depth + 1)
                     for child in by_parent.get(dept.id, [])],
    }


@router.put("/{dept_id}/structure", summary="تعديل هيكل القسم (رئيس/نوع/فرعي/فعّال/تكلفة)")
def update_structure(dept_id: int, payload: DepartmentUpdateExtra,
                     db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """تعديل حقول مركز الأقسام — مرتبطة بـ admin فقط."""
    dept = _dept(db, dept_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("dept_type"):
        data["dept_type"] = _check_type(data["dept_type"], DEPT_TYPES, "نوع القسم")
    if data.get("parent_id"):
        if data["parent_id"] == dept_id:
            raise HTTPException(400, "القسم لا يكون وحدةً داخل نفسه")
        if _dept(db, data["parent_id"]).parent_id == dept_id:
            raise HTTPException(400, "لا يمكن جعل قسم ابنٍ أبوًا لقسمه")
    if data.get("head_doctor_id") and not db.query(Doctor).filter(
            Doctor.id == data["head_doctor_id"]).first():
        raise HTTPException(404, "الطبيب غير موجود")
    for field, value in data.items():
        setattr(dept, field, value)
    db.commit()
    db.refresh(dept)
    return {"id": dept.id, "parent_id": dept.parent_id, "dept_type": dept.dept_type,
            "head_doctor_id": dept.head_doctor_id, "is_active": dept.is_active,
            "monthly_operating_cost": dept.monthly_operating_cost}


# ===== 2) الأطباء والكادر الطبي =====
@router.get("/{dept_id}/team", summary="كادر القسم: الأطباء + المساندون + رئيس القسم")
def team(dept_id: int, db: Session = Depends(get_db),
         _: User = Depends(get_current_user)):
    """أطباء القسم المنتسبون + الكادر المساند الموزّع + من رأس القسم."""
    dept = _dept(db, dept_id)
    doctors = (db.query(Doctor).filter(Doctor.department_id == dept_id)
               .order_by(Doctor.full_name).all())
    support = (db.query(DepartmentStaff, Staff)
               .filter(DepartmentStaff.department_id == dept_id)
               .join(Staff, Staff.id == DepartmentStaff.staff_id).all())
    head = db.query(Doctor).filter(Doctor.id == dept.head_doctor_id).first() \
        if dept.head_doctor_id else None
    return {
        "head": {"doctor_id": dept.head_doctor_id,
                 "name": head.full_name if head else None,
                 "specialty": head.specialty if head else None,
                 "rank": head.academic_rank if head else None},
        "doctors": [{"id": d.id, "name": d.full_name, "specialty": d.specialty,
                     "rank": d.academic_rank, "available": d.is_available,
                     "consultation_fee": d.consultation_fee} for d in doctors],
        "support": [{"id": s.id, "staff_id": row.staff_id, "name": s.full_name,
                     "position": s.position, "role_in_dept": row.role_in_dept,
                     "is_head": row.is_head} for row, s in support],
        "counts": {"doctors": len(doctors), "support": len(support)},
    }


@router.put("/{dept_id}/head", summary="تعيين رئيس القسم (طبيب)")
def set_head(dept_id: int, payload: DepartmentHodIn, db: Session = Depends(get_db),
             user: User = Depends(require_admin)):
    dept = _dept(db, dept_id)
    doctor_id = payload.head_doctor_id
    if doctor_id:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise HTTPException(404, "الطبيب غير موجود")
    dept.head_doctor_id = doctor_id
    db.commit()
    return {"id": dept.id, "head_doctor_id": dept.head_doctor_id,
            "updated_by": user.username}


@router.post("/{dept_id}/support", response_model=DepartmentStaffOut, status_code=201,
             summary="توزيع موظف على القسم (ممرض/تقني/إداري)")
def add_support(dept_id: int, payload: DepartmentStaffIn,
                db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _dept(db, dept_id)
    if not db.query(Staff).filter(Staff.id == payload.staff_id).first():
        raise HTTPException(404, "الموظف غير موجود")
    if db.query(DepartmentStaff).filter(
            DepartmentStaff.department_id == dept_id,
            DepartmentStaff.staff_id == payload.staff_id).first():
        raise HTTPException(409, "الموظف موزّع على هذا القسم مسبقًا")
    row = DepartmentStaff(department_id=dept_id, staff_id=payload.staff_id,
                          role_in_dept=payload.role_in_dept, is_head=payload.is_head)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _support_out(db, row)


@router.delete("/{dept_id}/support/{row_id}", status_code=204,
               summary="إلغاء توزيع موظف من القسم")
def remove_support(dept_id: int, row_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    row = db.query(DepartmentStaff).filter(
        DepartmentStaff.id == row_id,
        DepartmentStaff.department_id == dept_id).first()
    if not row:
        raise HTTPException(404, "التوزيع غير موجود")
    db.delete(row)
    db.commit()
    return None


def _support_out(db: Session, row: DepartmentStaff) -> DepartmentStaffOut:
    person = db.query(Staff).filter(Staff.id == row.staff_id).first()
    return DepartmentStaffOut(
        id=row.id, department_id=row.department_id, staff_id=row.staff_id,
        staff_name=person.full_name if person else None,
        position=person.position if person else None,
        role_in_dept=row.role_in_dept, is_head=row.is_head)


# ===== 3) الغرف والأسرّة =====
@router.get("/{dept_id}/rooms", response_model=List[DepartmentRoomOut],
            summary="غرف القسم بفئاتها وأسرّتها وحجوزاتها")
def list_rooms(dept_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    _dept(db, dept_id)
    now = datetime.utcnow()
    out = []
    for room in (db.query(DepartmentRoom)
                 .filter(DepartmentRoom.department_id == dept_id)
                 .order_by(DepartmentRoom.category, DepartmentRoom.name).all()):
        beds = db.query(Bed).filter(Bed.room_id == room.id).all()
        upcoming = (db.query(DepartmentRoomBooking)
                    .filter(DepartmentRoomBooking.room_id == room.id,
                            DepartmentRoomBooking.starts_at >= now).count())
        out.append(DepartmentRoomOut(
            id=room.id, department_id=room.department_id, name=room.name,
            room_number=room.room_number, category=room.category,
            capacity=room.capacity, is_active=room.is_active,
            beds_count=len(beds),
            beds_occupied=sum(1 for b in beds if b.status == BedStatus.OCCUPIED),
            upcoming_bookings=upcoming))
    return out


@router.post("/{dept_id}/rooms", response_model=DepartmentRoomOut, status_code=201,
             summary="إضافة غرفة/جناح للقسم")
def create_room(dept_id: int, payload: DepartmentRoomCreate,
                db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _dept(db, dept_id)
    room = DepartmentRoom(
        department_id=dept_id, name=payload.name.strip(),
        room_number=payload.room_number,
        category=_check_type(payload.category, ROOM_CATEGORIES, "فئة الغرفة"),
        capacity=payload.capacity)
    db.add(room)
    db.commit()
    db.refresh(room)
    return DepartmentRoomOut(**_room_fields(room), beds_count=0, beds_occupied=0,
                             upcoming_bookings=0)


def _room_fields(room: DepartmentRoom) -> dict:
    return {"id": room.id, "department_id": room.department_id, "name": room.name,
            "room_number": room.room_number, "category": room.category,
            "capacity": room.capacity, "is_active": room.is_active}


@router.delete("/{dept_id}/rooms/{room_id}", status_code=204,
               summary="حذف غرفة (تُفصل أسرّتها ولا تُحذف)")
def delete_room(dept_id: int, room_id: int, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    room = db.query(DepartmentRoom).filter(
        DepartmentRoom.id == room_id, DepartmentRoom.department_id == dept_id).first()
    if not room:
        raise HTTPException(404, "الغرفة غير موجودة")
    for bed in db.query(Bed).filter(Bed.room_id == room.id).all():
        bed.room_id = None
    db.delete(room)
    db.commit()
    return None


@router.post("/{dept_id}/rooms/{room_id}/bookings",
             response_model=DepartmentRoomBookingOut, status_code=201,
             summary="حجز غرفة (يرفض التداخل مع حجز قائم)")
def book_room(dept_id: int, room_id: int, payload: DepartmentRoomBookingIn,
              db: Session = Depends(get_db), user: User = Depends(require_admin)):
    room = db.query(DepartmentRoom).filter(
        DepartmentRoom.id == room_id, DepartmentRoom.department_id == dept_id).first()
    if not room:
        raise HTTPException(404, "الغرفة غير موجودة")
    if not room.is_active:
        raise HTTPException(400, "الغرفة معطّلة")
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(400, "وقت النهاية يجب أن يكون بعد البداية")
    clash = (db.query(DepartmentRoomBooking)
             .filter(DepartmentRoomBooking.room_id == room_id,
                     DepartmentRoomBooking.starts_at < payload.ends_at,
                     DepartmentRoomBooking.ends_at > payload.starts_at).first())
    if clash:
        raise HTTPException(409, "الغرفة محجوزة في هذا الوقت")
    row = DepartmentRoomBooking(
        room_id=room_id, starts_at=payload.starts_at, ends_at=payload.ends_at,
        purpose=payload.purpose, patient_id=payload.patient_id,
        created_by=user.username)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _booking_out(db, row)


def _booking_out(db: Session, row: DepartmentRoomBooking) -> DepartmentRoomBookingOut:
    room = db.query(DepartmentRoom).filter(
        DepartmentRoom.id == row.room_id).first()
    return DepartmentRoomBookingOut(
        id=row.id, room_id=row.room_id, room_name=room.name if room else None,
        starts_at=row.starts_at, ends_at=row.ends_at, purpose=row.purpose,
        patient_id=row.patient_id, created_by=row.created_by)


@router.get("/{dept_id}/bookings", response_model=List[DepartmentRoomBookingOut],
            summary="حجوزات غرف القسم")
def list_bookings(dept_id: int, from_now: bool = Query(True),
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _dept(db, dept_id)
    q = (db.query(DepartmentRoomBooking, DepartmentRoom)
         .join(DepartmentRoom, DepartmentRoom.id == DepartmentRoomBooking.room_id)
         .filter(DepartmentRoom.department_id == dept_id))
    if from_now:
        q = q.filter(DepartmentRoomBooking.starts_at >= datetime.utcnow())
    return [_booking_out(db, row) for row, _ in q.order_by(
        DepartmentRoomBooking.starts_at).all()]


@router.put("/{dept_id}/beds/{bed_id}/room", summary="توزيع سرير على غرفة")
def assign_bed(dept_id: int, bed_id: int, room_id: Optional[int] = Query(None),
               db: Session = Depends(get_db), _: User = Depends(require_admin)):
    bed = db.query(Bed).filter(Bed.id == bed_id,
                               Bed.department_id == dept_id).first()
    if not bed:
        raise HTTPException(404, "السرير غير موجود في هذا القسم")
    if room_id:
        room = db.query(DepartmentRoom).filter(
            DepartmentRoom.id == room_id,
            DepartmentRoom.department_id == dept_id).first()
        if not room:
            raise HTTPException(404, "الغرفة غير موجودة في هذا القسم")
        used = db.query(Bed).filter(Bed.room_id == room_id,
                                    Bed.id != bed_id).count()
        if used >= room.capacity:
            raise HTTPException(400, f"الغرفة مكتملة السعة ({room.capacity})")
    bed.room_id = room_id
    db.commit()
    return {"bed_id": bed.id, "room_id": bed.room_id}


# ===== 4) الخدمات والأسعار =====
@router.get("/{dept_id}/services", response_model=List[DepartmentServiceOut],
            summary="كتالوج خدمات القسم بتسعيرها ونسبها")
def list_services(dept_id: int, include_inactive: bool = Query(False),
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _dept(db, dept_id)
    q = db.query(DepartmentService).filter(
        DepartmentService.department_id == dept_id)
    if not include_inactive:
        q = q.filter(DepartmentService.is_active.is_(True))
    return [_service_out(s) for s in q.order_by(DepartmentService.name).all()]


def _service_out(s: DepartmentService) -> DepartmentServiceOut:
    doctor = round(s.price * (s.doctor_share_pct or 0) / 100.0, 2)
    insurance = round(s.price * (s.insurance_pct or 0) / 100.0, 2)
    return DepartmentServiceOut(
        id=s.id, department_id=s.department_id, code=s.code, name=s.name,
        price=s.price, doctor_share_pct=s.doctor_share_pct,
        insurance_pct=s.insurance_pct, procedure_note=s.procedure_note,
        is_active=s.is_active, doctor_amount=doctor, insurance_amount=insurance,
        patient_amount=round(s.price - insurance, 2))


@router.post("/{dept_id}/services", response_model=DepartmentServiceOut, status_code=201,
             summary="إضافة خدمة/إجراء بسعره")
def create_service(dept_id: int, payload: DepartmentServiceIn,
                   db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _dept(db, dept_id)
    if payload.doctor_share_pct + payload.insurance_pct > 100:
        raise HTTPException(400, "مجموع نسبة الطبيب والتأمين لا يتجاوز 100%")
    row = DepartmentService(
        department_id=dept_id, name=payload.name.strip(), code=payload.code,
        price=payload.price, doctor_share_pct=payload.doctor_share_pct,
        insurance_pct=payload.insurance_pct, procedure_note=payload.procedure_note)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _service_out(row)


@router.put("/{dept_id}/services/{service_id}", response_model=DepartmentServiceOut,
            summary="تعديل خدمة في الكتالوج")
def update_service(dept_id: int, service_id: int, payload: DepartmentServiceIn,
                   db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = db.query(DepartmentService).filter(
        DepartmentService.id == service_id,
        DepartmentService.department_id == dept_id).first()
    if not row:
        raise HTTPException(404, "الخدمة غير موجودة")
    if payload.doctor_share_pct + payload.insurance_pct > 100:
        raise HTTPException(400, "مجموع نسبة الطبيب والتأمين لا يتجاوز 100%")
    row.name, row.code = payload.name.strip(), payload.code
    row.price, row.doctor_share_pct = payload.price, payload.doctor_share_pct
    row.insurance_pct = payload.insurance_pct
    row.procedure_note = payload.procedure_note
    db.commit()
    db.refresh(row)
    return _service_out(row)


@router.delete("/{dept_id}/services/{service_id}", status_code=204,
               summary="حذف خدمة من كتالوج القسم")
def delete_service(dept_id: int, service_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    row = db.query(DepartmentService).filter(
        DepartmentService.id == service_id,
        DepartmentService.department_id == dept_id).first()
    if not row:
        raise HTTPException(404, "الخدمة غير موجودة")
    db.delete(row)
    db.commit()
    return None


# ===== 5) الجداول والمواعيد =====
@router.get("/{dept_id}/schedule", response_model=List[DepartmentScheduleOut],
            summary="جدول تشغيل عيادات القسم")
def list_schedule(dept_id: int, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    _dept(db, dept_id)
    rows = (db.query(DepartmentSchedule)
            .filter(DepartmentSchedule.department_id == dept_id).all())
    rows.sort(key=lambda r: (r.day_of_week,
                             0 if r.session == "morning" else 1, r.open_time))
    return [DepartmentScheduleOut(
        id=r.id, department_id=r.department_id, day_of_week=r.day_of_week,
        session=r.session, open_time=r.open_time, close_time=r.close_time,
        room_name=r.room_name) for r in rows]


@router.post("/{dept_id}/schedule", response_model=DepartmentScheduleOut, status_code=201,
             summary="إضافة وردية للعيادة (يوم + فترة)")
def create_schedule(dept_id: int, payload: DepartmentScheduleIn,
                    db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _dept(db, dept_id)
    session = _check_type(payload.session, ("morning", "evening"), "الفترة")
    if payload.open_time >= payload.close_time:
        raise HTTPException(400, "وقت الفتح قبل وقت الإغلاق مطلوب")
    clash = (db.query(DepartmentSchedule)
             .filter(DepartmentSchedule.department_id == dept_id,
                     DepartmentSchedule.day_of_week == payload.day_of_week,
                     DepartmentSchedule.session == session).first())
    if clash:
        raise HTTPException(409, "الفترة مسجّلة ليوم " + DAYS_AR[payload.day_of_week])
    row = DepartmentSchedule(
        department_id=dept_id, day_of_week=payload.day_of_week, session=session,
        open_time=payload.open_time, close_time=payload.close_time,
        room_name=payload.room_name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return DepartmentScheduleOut(
        id=row.id, department_id=row.department_id, day_of_week=row.day_of_week,
        session=row.session, open_time=row.open_time, close_time=row.close_time,
        room_name=row.room_name)


@router.delete("/{dept_id}/schedule/{row_id}", status_code=204,
               summary="حذف وردية من جدول القسم")
def delete_schedule(dept_id: int, row_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_admin)):
    row = db.query(DepartmentSchedule).filter(
        DepartmentSchedule.id == row_id,
        DepartmentSchedule.department_id == dept_id).first()
    if not row:
        raise HTTPException(404, "الوردية غير موجودة")
    db.delete(row)
    db.commit()
    return None


# ===== 3ب) أسرّة القسم (ضمن تبويب الغرف بدل الشاشة المنفصلة) =====
@router.get("/{dept_id}/beds", summary="أسرّة القسم مع غرفها وحالتها")
def department_beds(dept_id: int, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """أسرّة القسم مع اسم الغرفة — لعرضها داخل تبويب الغرف بدل شاشة مستقلة."""
    _dept(db, dept_id)
    rows = (db.query(Bed)
            .filter(Bed.department_id == dept_id)
            .order_by(Bed.bed_number).all())
    rooms = {r.id: r for r in db.query(DepartmentRoom).filter(
        DepartmentRoom.department_id == dept_id).all()}
    return [{"id": b.id, "bed_number": b.bed_number, "status": b.status.value,
             "patient_id": b.patient_id, "room_id": b.room_id,
             "room_name": rooms[b.room_id].name if b.room_id in rooms else None}
            for b in rows]


# ===== 6) التقارير وإحصائيات القسم =====
def _analytics(db: Session, dept_id: int, since: datetime) -> dict:
    """مؤشرات قسم واحد: الإشغال + الإيراد/المصروف + إنتاجية الكادر."""
    dept = _dept(db, dept_id)
    beds = db.query(Bed).filter(Bed.department_id == dept_id).all()
    occupied = sum(1 for b in beds if b.status == BedStatus.OCCUPIED)
    maintenance = sum(1 for b in beds if b.status == BedStatus.MAINTENANCE)
    total_beds = len(beds)

    doctor_ids = [d.id for d in db.query(Doctor).filter(
        Doctor.department_id == dept_id).all()]
    appts = (db.query(Appointment)
             .filter(Appointment.doctor_id.in_(doctor_ids),
                     Appointment.appointment_date >= since).all()) \
        if doctor_ids else []
    inv_rows = (db.query(Invoice, Appointment)
                .join(Appointment, Appointment.id == Invoice.appointment_id)
                .filter(Appointment.doctor_id.in_(doctor_ids),
                        Invoice.created_at >= since).all()) if doctor_ids else []

    revenue = 0.0
    paid = 0.0
    for inv, _ in inv_rows:
        revenue += inv.total
        paid += float(inv.paid_amount or 0)
    months = max((datetime.utcnow() - since).days / 30.0, 1.0)
    cost = round(float(dept.monthly_operating_cost or 0) * months, 2)

    per_doctor = []
    for did in doctor_ids:
        doc = db.query(Doctor).filter(Doctor.id == did).first()
        n = sum(1 for a in appts if a.doctor_id == did)
        patients = len({a.patient_id for a in appts if a.doctor_id == did})
        per_doctor.append({"doctor_id": did, "name": doc.full_name if doc else None,
                           "appointments": n, "patients": patients,
                           "revenue": round(sum(
                               inv.total for inv, appt in inv_rows
                               if appt.doctor_id == did), 2)})
    per_doctor.sort(key=lambda x: -x["appointments"])
    patients_seen = len({a.patient_id for a in appts})

    return {
        "department_id": dept_id, "name": dept.name,
        "occupancy": {
            "beds_total": total_beds, "beds_occupied": occupied,
            "beds_maintenance": maintenance,
            "beds_available": total_beds - occupied - maintenance,
            "rate": round(occupied * 100.0 / total_beds, 1) if total_beds else 0.0,
        },
        "financials": {
            "revenue": round(revenue, 2), "collected": round(paid, 2),
            "cost": cost, "net": round(revenue - cost, 2),
            "insurance_share": round(sum(
                float(inv.total or 0) for inv, _ in inv_rows
                if (inv.payment_method or "") == "insurance"), 2),
        },
        "productivity": {
            "appointments": len(appts), "patients": patients_seen,
            "revenue_per_patient": round(revenue / patients_seen, 2)
            if patients_seen else 0.0,
            "doctors": len(doctor_ids),
            "per_doctor": per_doctor,
        },
    }


@router.get("/analytics", summary="مؤشرات كل الأقسام (مقارنة)")
def analytics_all(days: int = Query(30, ge=1, le=365),
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """مقارنة مؤشرات جميع الأقسام في نافذة زمنية واحدة."""
    since = datetime.utcnow() - timedelta(days=days)
    return [_analytics(db, d.id, since) for d in db.query(Department)
            .order_by(Department.name).all()]


@router.get("/{dept_id}/analytics", summary="مؤشرات قسم واحد")
def analytics_dept(dept_id: int, days: int = Query(30, ge=1, le=365),
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _analytics(db, dept_id, datetime.utcnow() - timedelta(days=days))




