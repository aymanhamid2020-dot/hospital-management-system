"""مسارات الوحدات التشغيلية والخدمات المكملة:
1. العلاج الطبيعي (Physiotherapy)
2. التغذية السريرية (Nutrition)
3. الطوارئ (Emergency)
4. الرعاية الصحية المنزلية (Home Health)
5. برامج العافية (Wellness)
6. النظافة الفندقية والتدبير المنزلي (Housekeeping)
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.clinical_schemas import (
    EmergencyCaseCreate, EmergencyCaseOut, EmergencyCaseUpdate,
    EmergencyCheckoutIn, EmergencyInvoiceBrief, EmergencyLabOrderBrief,
    EmergencyLineBrief, EmergencyOrderIn, EmergencySummaryOut, EmergencyTreatmentIn,
    HomeHealthCaseCreate, HomeHealthCaseOut, HomeHealthCaseUpdate,
    HousekeepingTaskCreate, HousekeepingTaskOut, HousekeepingTaskUpdate,
    NutritionCaseCreate, NutritionCaseOut, NutritionCaseUpdate,
    PhysiotherapyCaseCreate, PhysiotherapyCaseOut, PhysiotherapyCaseUpdate,
    StatusUpdate, WellnessProgramCreate, WellnessProgramOut, WellnessProgramUpdate,
)
from app.database import get_db
from app.models import (
    Doctor, EmergencyCase, HomeHealthCase, HousekeepingTask, Invoice, InvoiceLine,
    InvoiceStatus, LabOrder, LabTest, LabStatus, MedicalRecord, Medication,
    Notification, NutritionCase, Patient, Prescription, PrescriptionItem,
    PhysiotherapyCase, TestType, User, WellnessProgram,
)

router = APIRouter(prefix="/service-units", tags=["الوحدات التشغيلية المكملة"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_patient(db: Session, patient_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="المريض غير موجود")
    return patient


def _get_doctor(db: Session, doctor_id: Optional[int]) -> Optional[Doctor]:
    if doctor_id is None:
        return None
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="الطبيب غير موجود")
    return doctor


# =====================================================================
# 1. العلاج الطبيعي (Physiotherapy)
# =====================================================================

@router.get("/physiotherapy", response_model=List[PhysiotherapyCaseOut])
def list_physiotherapy_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    therapist_id: Optional[int] = Query(None, gt=0),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PhysiotherapyCase)
    if patient_id:
        query = query.filter(PhysiotherapyCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(PhysiotherapyCase.status == status_filter)
    if therapist_id:
        query = query.filter(PhysiotherapyCase.therapist_id == therapist_id)
    return query.order_by(PhysiotherapyCase.id.desc()).limit(limit).all()


@router.post("/physiotherapy", response_model=PhysiotherapyCaseOut, status_code=status.HTTP_201_CREATED)
def create_physiotherapy_case(
    payload: PhysiotherapyCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    _get_doctor(db, payload.therapist_id)

    item = PhysiotherapyCase(
        **payload.model_dump(),
        status="assessed",
        created_by=current_user.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/physiotherapy/{case_id}", response_model=PhysiotherapyCaseOut)
def get_physiotherapy_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(PhysiotherapyCase).filter(PhysiotherapyCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة العلاج الطبيعي غير موجودة")
    return item


@router.put("/physiotherapy/{case_id}", response_model=PhysiotherapyCaseOut)
def update_physiotherapy_case(
    case_id: int,
    payload: PhysiotherapyCaseUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(PhysiotherapyCase).filter(PhysiotherapyCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة العلاج الطبيعي غير موجودة")
    if item.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail="لا يمكن تعديل حالة مكتملة أو ملغاة")

    update_data = payload.model_dump(exclude_unset=True)
    if "therapist_id" in update_data:
        _get_doctor(db, update_data["therapist_id"])

    for key, value in update_data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/physiotherapy/{case_id}/status", response_model=PhysiotherapyCaseOut)
def change_physiotherapy_status(
    case_id: int,
    payload: StatusUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(PhysiotherapyCase).filter(PhysiotherapyCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة العلاج الطبيعي غير موجودة")

    allowed = {"assessed", "in_treatment", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(status_code=422, detail=f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")

    if item.status in ("completed", "cancelled") and payload.status != item.status:
        raise HTTPException(status_code=409, detail="لا يمكن تغيير حالة منتهية")

    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "cancelled" and item.cancelled_at is None:
        item.cancelled_at = _utc_now()

    db.commit()
    db.refresh(item)
    return item



# =====================================================================
# 2. التغذية السريرية (Nutrition)
# =====================================================================

@router.get("/nutrition", response_model=List[NutritionCaseOut])
def list_nutrition_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(NutritionCase)
    if patient_id:
        query = query.filter(NutritionCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(NutritionCase.status == status_filter)
    return query.order_by(NutritionCase.id.desc()).limit(limit).all()


@router.post("/nutrition", response_model=NutritionCaseOut, status_code=status.HTTP_201_CREATED)
def create_nutrition_case(
    payload: NutritionCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = NutritionCase(
        **payload.model_dump(),
        status="assessed",
        created_by=current_user.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/nutrition/{case_id}", response_model=NutritionCaseOut)
def get_nutrition_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(NutritionCase).filter(NutritionCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة التغذية غير موجودة")
    return item


@router.put("/nutrition/{case_id}", response_model=NutritionCaseOut)
def update_nutrition_case(
    case_id: int,
    payload: NutritionCaseUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(NutritionCase).filter(NutritionCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة التغذية غير موجودة")
    if item.status in ("completed", "suspended"):
        raise HTTPException(status_code=409, detail="لا يمكن تعديل حالة مغلقة أو معلقة")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/nutrition/{case_id}/status", response_model=NutritionCaseOut)
def change_nutrition_status(
    case_id: int,
    payload: StatusUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(NutritionCase).filter(NutritionCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة التغذية غير موجودة")

    allowed = {"assessed", "active", "completed", "suspended"}
    if payload.status not in allowed:
        raise HTTPException(status_code=422, detail=f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")

    if item.status in ("completed", "suspended") and payload.status != item.status:
        raise HTTPException(status_code=409, detail="لا يمكن تغيير حالة منتهية أو معلقة")

    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "suspended" and item.suspended_at is None:
        item.suspended_at = _utc_now()

    db.commit()
    db.refresh(item)
    return item



# =====================================================================
# 3. الطوارئ (Emergency)
# =====================================================================

@router.get("/emergency", response_model=List[EmergencyCaseOut])
def list_emergency_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    triage_level: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(EmergencyCase)
    if patient_id is not None:
        query = query.filter(EmergencyCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(EmergencyCase.status == status_filter)
    if triage_level:
        query = query.filter(EmergencyCase.triage_level == triage_level)
    rows = query.order_by(EmergencyCase.arrival_at.desc()).limit(limit).all()
    # اسم المريض يُجلب دفعة واحدة — لا استعلام لكل حالة في القائمة
    pids = {r.patient_id for r in rows}
    names = (dict(db.query(Patient.id, Patient.full_name)
                  .filter(Patient.id.in_(pids)).all()) if pids else {})
    out = []
    for r in rows:
        item = EmergencyCaseOut.model_validate(r)
        item.patient_name = names.get(r.patient_id)
        out.append(item)
    return out


@router.post("/emergency", response_model=EmergencyCaseOut, status_code=status.HTTP_201_CREATED)
def create_emergency_case(
    payload: EmergencyCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = EmergencyCase(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/emergency/{case_id}", response_model=EmergencyCaseOut)
def get_emergency_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    return item


@router.put("/emergency/{case_id}", response_model=EmergencyCaseOut)
def update_emergency_case(
    case_id: int,
    payload: EmergencyCaseUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    if item.status in {"discharged", "closed"}:
        raise HTTPException(409, "لا يمكن تعديل حالة طوارئ منتهية")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/emergency/{case_id}/status", response_model=EmergencyCaseOut)
def change_emergency_status(
    case_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    allowed = {"arrived", "triaged", "under_treatment", "discharged", "closed"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"discharged", "closed"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة طوارئ منتهية")
    item.status = payload.status
    if payload.status in {"discharged", "closed"} and item.closed_at is None:
        item.closed_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item


# ======================================================================
# سير عمل الطوارئ: فتح ملف ← طلب فحوصات ← تحصيل ← نتائج ← علاج ← صيدلية
# ======================================================================

def _er_case(db: Session, case_id: int) -> EmergencyCase:
    """حالة الطوارئ أو 404."""
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    return item


def _er_open(case: EmergencyCase) -> None:
    """لا متابعة في حالة منتهية (خرجت أو أُغلقت)."""
    if case.status in {"discharged", "closed"}:
        raise HTTPException(409, "حالة طوارئ منتهية — لا يمكن المتابعة فيها")


def _case_invoice_ids(db: Session, case: EmergencyCase) -> List[int]:
    """كل فواتير التي تحمل بنودًا لهذه الحالة أو لطلبات مختبرها.

    قد تستفي الحالة فاتورتين (تحصيلٌ ثم فحوصات طُلبت بعده)، فلا يكفي
    النظر إلى الأحدث وحده: بوابة الدفع يجب أن ترى كلًا منهما.
    """
    order_ids = [r[0] for r in db.query(LabOrder.id)
                 .filter(LabOrder.emergency_case_id == case.id).all()]
    conds = [and_(InvoiceLine.ref_type == "emergency_case",
                  InvoiceLine.ref_id == case.id)]
    if order_ids:
        conds.append(and_(InvoiceLine.ref_type == "lab_order",
                          InvoiceLine.ref_id.in_(order_ids)))
    rows = db.query(InvoiceLine.invoice_id).filter(or_(*conds)).distinct().all()
    return [r[0] for r in rows]


def _case_settled(db: Session, case: EmergencyCase) -> bool:
    """هل حُصِّلت كل بنود الحالة؟ لا فاتورة بعد ⇒ لم يُفتح تحصيل أصلًا."""
    ids = _case_invoice_ids(db, case)
    if not ids:
        return False
    invoices = db.query(Invoice).filter(Invoice.id.in_(ids)).all()
    return bool(invoices) and all(
        (i.paid_amount or 0) >= (i.total or 0) - 0.01 for i in invoices)


def _billed_order_ids(db: Session, order_ids) -> set:
    """طلبات مختبر سبق فوترتها على أي فاتورة — لا تحصيل مزدوج."""
    ids = [i for i in order_ids if i is not None]
    if not ids:
        return set()
    rows = db.query(InvoiceLine.ref_id).filter(
        InvoiceLine.ref_type == "lab_order",
        InvoiceLine.ref_id.in_(ids)).distinct().all()
    return {r[0] for r in rows}


def _notify_once(db: Session, ntype: str, title: str, message: str,
                 patient_id: int) -> None:
    """إشعار إن لم يبقَ سابق غير مقروء بالعنوان نفسه — لا تكرار مع كل محاولة."""
    exists = db.query(Notification).filter(
        Notification.title == title,
        Notification.is_read.is_(False),
    ).first()
    if exists:
        return
    db.add(Notification(type=ntype, title=title, message=message,
                        patient_id=patient_id))


def _doctor_for(db: Session, user: User) -> Optional[int]:
    """يربط المستخدم بسجلّه المهني إن كان طبيبًا (ربطًا بالبريد كالنظام كلّه)."""
    linked = db.query(Doctor).filter(Doctor.email == user.email).first()
    return linked.id if linked else None


def _emergency_summary(db: Session, case: EmergencyCase) -> EmergencySummaryOut:
    """لوحة الحالة: ما فُوترة، ما دُفع، وما نفّذه المختبر."""
    patient = db.query(Patient).filter(Patient.id == case.patient_id).first()
    orders = (db.query(LabOrder)
              .filter(LabOrder.emergency_case_id == case.id)
              .order_by(LabOrder.ordered_at).all())
    billed = _billed_order_ids(db, [o.id for o in orders])

    inv_ids = _case_invoice_ids(db, case)
    invoices = (db.query(Invoice).filter(Invoice.id.in_(inv_ids))
                .order_by(Invoice.id).all()) if inv_ids else []
    lines = [x for inv in invoices for x in inv.lines]

    billed_total = round(sum(i.total or 0 for i in invoices), 2)
    paid = round(sum(i.paid_amount or 0 for i in invoices), 2)
    due = round(max(0.0, billed_total - paid), 2)
    if not invoices:
        pay_state = "unbilled"
    elif due <= 0.01:
        pay_state = "paid"
    elif paid > 0:
        pay_state = "partial"
    else:
        pay_state = "unpaid"

    return EmergencySummaryOut(
        case=case,
        patient_name=(patient.full_name if patient else ""),
        invoice_id=invoices[-1].id if invoices else None,
        invoices=[EmergencyInvoiceBrief(
            id=i.id, total=float(i.total or 0), paid_amount=float(i.paid_amount or 0),
            status=(i.status.value if hasattr(i.status, "value") else str(i.status)),
            due=round(max(0.0, (i.total or 0) - (i.paid_amount or 0)), 2))
            for i in invoices],
        lines=[EmergencyLineBrief(id=x.id, kind=x.kind,
                                  description=x.description,
                                  amount=float(x.amount or 0)) for x in lines],
        billed_total=billed_total, paid_amount=paid, due=due,
        payment_status=pay_state,
        lab_orders=[EmergencyLabOrderBrief(
            id=o.id, test_name=o.test_name,
            test_type=(o.test_type.value if hasattr(o.test_type, "value") else str(o.test_type)),
            status=(o.status.value if hasattr(o.status, "value") else str(o.status)),
            price=float(o.price or 0), priority=o.priority or "routine",
            result=o.result, billed=o.id in billed,
            executed=bool(o.result) or (o.sample_status not in (None, "none")),
        ) for o in orders],
        tests_ready=sum(
            1 for o in orders
            if o.status in (LabStatus.READY, LabStatus.REVIEWED)),
        has_record=case.record_id is not None,
        has_prescription=case.prescription_id is not None,
    )


@router.get("/emergency/{case_id}/summary", response_model=EmergencySummaryOut,
            summary="لوحة حالة الطوارئ: الفوترة والمختبر والعلاج")
def emergency_summary(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """كل ما يخصّ الحالة في شاشة واحدة لصاحب النوبة."""
    return _emergency_summary(db, _er_case(db, case_id))


@router.post("/emergency/{case_id}/orders", response_model=EmergencySummaryOut,
             summary="طلب فحوصات المختبر/الأشعة من نوبة الطوارئ")
def order_emergency_tests(
    case_id: int,
    payload: EmergencyOrderIn,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    """الطبيب يختار من الدليل المصنَّف (دم/بول/براز… أو أنواع الأشعة).

    الطلبات تُنشأ معلّقة التحصيل: تظهر للمختبر فورًا ومعها شارة
    «بانتظار التحصيل»، ولا يبدأ تنفيذها إلا بعد دفع الكشفية معها.
    """
    case = _er_case(db, case_id)
    _er_open(case)
    if case.doctor_id is None:
        case.doctor_id = _doctor_for(db, current_user)

    for line in payload.lines:
        price, name, test_type = 0.0, line.test_name, TestType.LAB
        lab_test_id = specimen = unit = modality = None
        ref_min = ref_max = None

        if line.lab_test_id:
            cat = (db.query(LabTest)
                   .filter(LabTest.id == line.lab_test_id,
                           LabTest.active.is_(True)).first())
            if not cat:
                raise HTTPException(404, "الفحص غير موجود في الدليل أو معطّل")
            name = name or cat.name
            price = float(cat.price or 0)
            test_type = cat.category
            lab_test_id = cat.id
            specimen, unit = cat.specimen_type, cat.unit
            ref_min, ref_max = cat.ref_min, cat.ref_max
            # مجموعة الأشعة (xray/ct/mri/ultrasound) تُнакоَن لتصنيف الجهاز
            if (test_type is TestType.RADIOLOGY and cat.specimen_group):
                modality = cat.specimen_group.upper()
        if not name:
            raise HTTPException(400, "اسم الفحص إلزامي")

        db.add(LabOrder(
            patient_id=case.patient_id, doctor_id=case.doctor_id,
            test_type=test_type, test_name=name, status=LabStatus.PENDING,
            price=price, priority=line.priority, notes=line.notes,
            lab_test_id=lab_test_id, specimen_type=specimen,
            unit=unit, ref_min=ref_min, ref_max=ref_max, modality=modality,
            emergency_case_id=case.id,
        ))

    db.commit()
    db.refresh(case)
    return _emergency_summary(db, case)


@router.post("/emergency/{case_id}/checkout", response_model=EmergencySummaryOut,
             summary="فتح فاتورة تحصيل: الكشفية + فحوصات الحالة")
def emergency_checkout(
    case_id: int,
    payload: EmergencyCheckoutIn,
    current_user: User = Depends(
        require_role("admin", "doctor", "cashier", "receptionist")),
    db: Session = Depends(get_db),
):
    """يجمع صاحب التحصيل الكشفية وما لم يُفوتر من الفحوصات في فاتورة واحدة.

    السطور تُعلَّق بمصادرها (emergency_case / lab_order) فلا تُحصَّل مرّة
    أخرى إن أُعيد فتح الحالة، ويفتح بعدها إشعارٌ لصاحب التحصيل.
    """
    case = _er_case(db, case_id)
    _er_open(case)
    fee = case.consult_fee if payload.consult_fee is None else float(payload.consult_fee)

    pending = []
    visit_billed = (db.query(InvoiceLine.id)
                    .filter(InvoiceLine.ref_type == "emergency_case",
                            InvoiceLine.ref_id == case.id,
                            InvoiceLine.kind == "visit").first())
    if fee > 0 and not visit_billed:
        pending.append(("visit", f"كشفية طوارئ #{case.id}", fee,
                        "emergency_case", case.id))

    orders = db.query(LabOrder).filter(LabOrder.emergency_case_id == case.id).all()
    already = _billed_order_ids(db, [o.id for o in orders])
    for o in orders:
        if o.id in already:
            continue
        pending.append((
            "radiology" if o.test_type is TestType.RADIOLOGY else "lab",
            o.test_name, float(o.price or 0), "lab_order", o.id))

    if not pending:
        raise HTTPException(409, "لا توجد بنود جديدة لفوترةها — كل ما طلب سبق فوترته")

    inv = Invoice(
        patient_id=case.patient_id, amount=0, discount=0, tax_rate=0,
        paid_amount=0, status=InvoiceStatus.UNPAID,
        description=(payload.note or "").strip() or f"طوارئ #{case.id} — كشفية وفحوصات",
    )
    total = 0.0
    for kind, desc, amount, ref_type, ref_id in pending:
        amount = round(amount, 2)
        inv.lines.append(InvoiceLine(
            kind=kind, description=desc, quantity=1,
            unit_price=amount, amount=amount,
            ref_type=ref_type, ref_id=ref_id,
        ))
        total += amount
    inv.amount = round(total, 2)
    if inv.amount <= 0:
        raise HTTPException(400, "لا يمكن فتح فاتورة بمبلغ صفر")

    db.add(inv)
    db.flush()
    case.invoice_id = inv.id
    case.consult_fee = fee
    db.commit()
    db.refresh(inv)

    # قيد الإيراد لحظة الفتح — يلتزم وحده فلا يسقط التحصيل إن تعثّر
    from app.routers.accounting import auto_post_invoice
    auto_post_invoice(db, inv, current_user.username)

    _notify_once(
        db, "payment_pending", f"تحصيل طوارئ #{case.id}",
        f"فاتورة #{inv.id} بمبلغ {inv.total:.2f} ر.س بانتظار التحصيل — "
        f"{case.complaint[:80]}",
        case.patient_id)
    db.commit()
    db.refresh(case)
    return _emergency_summary(db, case)


@router.post("/emergency/{case_id}/treatment", response_model=EmergencySummaryOut,
             summary="تسجيل علاج الطوارئ وإرسال الوصفة للصيدلية")
def record_emergency_treatment(
    case_id: int,
    payload: EmergencyTreatmentIn,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    """طبيب الطوارئ يسجّل التشخيص والعلاج بعد رؤية نتائج المختبر.

    يُنشئ سجلًا طبيًّا للمريض، ويوصف إن وُجدت أدوية فتظهر فورًا لصاحب
    الصيدلية على حالة PENDING ليتم التحصيل عندها.
    """
    case = _er_case(db, case_id)
    _er_open(case)
    if case.record_id:
        raise HTTPException(409, "سُجّل علاج لهذه الحالة بالفعل")

    doctor_id = case.doctor_id or _doctor_for(db, current_user)
    rx_names = []
    for item in payload.prescription:
        med = db.query(Medication).filter(Medication.id == item.medication_id).first()
        if not med:
            raise HTTPException(
                404, f"الدواء بالمعرف {item.medication_id} غير موجود")
        rx_names.append(med.name)

    record = MedicalRecord(
        patient_id=case.patient_id, doctor_id=doctor_id,
        diagnosis=payload.diagnosis,
        chief_complaint=payload.chief_complaint or case.complaint,
        prescription="، ".join(rx_names) or None,
        notes=payload.notes,
    )
    db.add(record)
    db.flush()

    rx = None
    if payload.prescription:
        rx = Prescription(
            patient_id=case.patient_id, doctor_id=doctor_id, record_id=record.id,
            status="PENDING", notes=f"طوارئ #{case.id} — {payload.diagnosis}",
            created_by=current_user.username,
        )
        db.add(rx)
        db.flush()
        for item in payload.prescription:
            rx.items.append(PrescriptionItem(
                medication_id=item.medication_id, quantity=item.quantity,
                dosage=item.dosage, frequency=item.frequency,
                duration=item.duration, instructions=item.instructions))
        db.flush()

    case.record_id = record.id
    case.prescription_id = rx.id if rx else None
    case.diagnosis = payload.diagnosis
    case.treatment = payload.treatment
    if case.status in ("arrived", "triaged"):
        case.status = "under_treatment"
    if payload.discharge:
        case.status = "discharged"
        case.closed_at = _utc_now()
        case.disposition = case.disposition or "خرج بعد العلاج"
    db.commit()

    if rx is not None:
        _notify_once(
            db, "prescription", f"وصفة طوارئ #{case.id}",
            f"وصفة جديدة بحالة PENDING — {payload.diagnosis}",
            case.patient_id)
        db.commit()
    db.refresh(case)
    return _emergency_summary(db, case)


# =====================================================================
# 4. الرعاية الصحية المنزلية (Home Health)
# =====================================================================

@router.get("/home-health", response_model=List[HomeHealthCaseOut])
def list_home_health_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(HomeHealthCase)
    if patient_id is not None:
        query = query.filter(HomeHealthCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(HomeHealthCase.status == status_filter)
    return query.order_by(HomeHealthCase.id.desc()).limit(limit).all()


@router.post("/home-health", response_model=HomeHealthCaseOut, status_code=status.HTTP_201_CREATED)
def create_home_health_case(
    payload: HomeHealthCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = HomeHealthCase(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/home-health/{case_id}", response_model=HomeHealthCaseOut)
def get_home_health_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(HomeHealthCase).filter(HomeHealthCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الرعاية المنزلية غير موجودة")
    return item


@router.put("/home-health/{case_id}", response_model=HomeHealthCaseOut)
def update_home_health_case(
    case_id: int,
    payload: HomeHealthCaseUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(HomeHealthCase).filter(HomeHealthCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الرعاية المنزلية غير موجودة")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تعديل حالة رعاية منزلية منتهية")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/home-health/{case_id}/status", response_model=HomeHealthCaseOut)
def change_home_health_status(
    case_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(HomeHealthCase).filter(HomeHealthCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الرعاية المنزلية غير موجودة")
    allowed = {"referred", "scheduled", "active", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"completed", "cancelled"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة رعاية منزلية منتهية")
    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "cancelled" and item.cancelled_at is None:
        item.cancelled_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item


# =====================================================================
# 5. برامج العافية ونمط الحياة (Wellness)
# =====================================================================

@router.get("/wellness", response_model=List[WellnessProgramOut])
def list_wellness_programs(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(WellnessProgram)
    if patient_id is not None:
        query = query.filter(WellnessProgram.patient_id == patient_id)
    if status_filter:
        query = query.filter(WellnessProgram.status == status_filter)
    return query.order_by(WellnessProgram.id.desc()).limit(limit).all()


@router.post("/wellness", response_model=WellnessProgramOut, status_code=status.HTTP_201_CREATED)
def create_wellness_program(
    payload: WellnessProgramCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = WellnessProgram(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/wellness/{program_id}", response_model=WellnessProgramOut)
def get_wellness_program(
    program_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(WellnessProgram).filter(WellnessProgram.id == program_id).first()
    if not item:
        raise HTTPException(404, "برنامج العافية غير موجود")
    return item


@router.put("/wellness/{program_id}", response_model=WellnessProgramOut)
def update_wellness_program(
    program_id: int,
    payload: WellnessProgramUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(WellnessProgram).filter(WellnessProgram.id == program_id).first()
    if not item:
        raise HTTPException(404, "برنامج العافية غير موجود")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تعديل برنامج عافية منتهٍ")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/wellness/{program_id}/status", response_model=WellnessProgramOut)
def change_wellness_status(
    program_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(WellnessProgram).filter(WellnessProgram.id == program_id).first()
    if not item:
        raise HTTPException(404, "برنامج العافية غير موجود")
    allowed = {"planned", "active", "paused", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"completed", "cancelled"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة برنامج عافية منتهٍ")
    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item



# =====================================================================
# 6. النظافة والتدبير المنزلي (Housekeeping)
# =====================================================================

@router.get("/housekeeping", response_model=List[HousekeepingTaskOut])
def list_housekeeping_tasks(
    room_number: Optional[str] = Query(None, min_length=1, max_length=50),
    status_filter: Optional[str] = Query(None, alias="status"),
    assigned_to: Optional[str] = Query(None, max_length=100),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(HousekeepingTask)
    if room_number:
        query = query.filter(HousekeepingTask.room_number == room_number)
    if status_filter:
        query = query.filter(HousekeepingTask.status == status_filter)
    if assigned_to:
        query = query.filter(HousekeepingTask.assigned_to == assigned_to)
    return query.order_by(HousekeepingTask.id.desc()).limit(limit).all()


@router.post("/housekeeping", response_model=HousekeepingTaskOut, status_code=status.HTTP_201_CREATED)
def create_housekeeping_task(
    payload: HousekeepingTaskCreate,
    current_user: User = Depends(require_role("admin", "doctor", "موظف استقبال")),
    db: Session = Depends(get_db),
):
    item = HousekeepingTask(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/housekeeping/{task_id}", response_model=HousekeepingTaskOut)
def get_housekeeping_task(
    task_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(HousekeepingTask).filter(HousekeepingTask.id == task_id).first()
    if not item:
        raise HTTPException(404, "مهمة النظافة غير موجودة")
    return item


@router.put("/housekeeping/{task_id}", response_model=HousekeepingTaskOut)
def update_housekeeping_task(
    task_id: int,
    payload: HousekeepingTaskUpdate,
    _: User = Depends(require_role("admin", "doctor", "موظف استقبال")),
    db: Session = Depends(get_db),
):
    item = db.query(HousekeepingTask).filter(HousekeepingTask.id == task_id).first()
    if not item:
        raise HTTPException(404, "مهمة النظافة غير موجودة")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تعديل مهمة نظافة منتهية")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/housekeeping/{task_id}/status", response_model=HousekeepingTaskOut)
def change_housekeeping_status(
    task_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor", "موظف استقبال")),
    db: Session = Depends(get_db),
):
    item = db.query(HousekeepingTask).filter(HousekeepingTask.id == task_id).first()
    if not item:
        raise HTTPException(404, "مهمة النظافة غير موجودة")
    allowed = {"pending", "in_progress", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"completed", "cancelled"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة مهمة نظافة منتهية")
    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "cancelled" and item.cancelled_at is None:
        item.cancelled_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item

