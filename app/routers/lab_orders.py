from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_user_role, require_admin
from app.database import get_db
from app.models import (
    LabOrder, LabStatus, LabTest, Notification, Patient, Doctor, TestType, User,
    RadiologyRoom,
)
from app.schemas import (
    LabOrderCreate, LabOrderInDB, LabOrderUpdate,
    LabResultEntry, LabSampleCollect, LabSampleReceive, LabVerify,
)

router = APIRouter(prefix="/lab-orders", tags=["Lab & Radiology"])

_SAMPLE_STATUSES = ("none", "collected", "received", "rejected")
_PRIORITIES = ("routine", "stat")


def _doctor_can_access(db: Session, current_user: User, order: LabOrder) -> bool:
    """طبيب مرتبط بسجل طبيب: يصل فقط لطلباته — باقي الأدوار (مدير/استقبال) غير مقيّدة."""
    if get_user_role(current_user) != "doctor":
        return True
    linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
    return linked is not None and order.doctor_id == linked.id


def _who(current_user: User) -> str:
    """اسم المستخدم لسجلات السحب/الاعتماد (يُسجَّل في سجل التدقيق تلقائيًا)."""
    return (getattr(current_user, "full_name", None)
            or getattr(current_user, "username", None) or "—")


def _barcode_for(order: LabOrder) -> str:
    """باركود العيّنة: ثابت لكل طلب (Code39 يقبل الأرقام والأحرف اللاتينية الكبيرة)."""
    return order.barcode or f"BC{order.id:07d}"


def _check_schedule_conflict(
    db: Session,
    modality: Optional[str],
    room: Optional[str],
    scheduled_at: Optional[datetime],
    exclude_order_id: Optional[int] = None,
) -> Optional[str]:
    """
    التحقق من تضارب الموعد: نفس الغرفة + نفس الموعد ±30 دقيقة.
    يعيد رسالة الخطأ إن وُجد تضارب، وإلا None.
    """
    if not (modality and room and scheduled_at):
        return None
    window_start = scheduled_at - timedelta(minutes=30)
    window_end = scheduled_at + timedelta(minutes=30)
    q = db.query(LabOrder).filter(
        LabOrder.modality == modality,
        LabOrder.room == room,
        LabOrder.scheduled_at.between(window_start, window_end),
        LabOrder.status.notin_([LabStatus.CANCELLED, LabStatus.REVIEWED]),
    )
    if exclude_order_id:
        q = q.filter(LabOrder.id != exclude_order_id)
    clash = q.first()
    if clash:
        return (f"تعارض جدولة: {clash.modality} في {clash.room} "
                f"في {clash.scheduled_at.strftime('%Y-%m-%d %H:%M')} "
                f"(طلب #{clash.id} — {clash.patient.full_name})")
    return None


def _flags_for(value, ref_min, ref_max):
    """علامتا (غير طبيعي، حرجة) من مقارنة القيمة بالنطاق الطبيعي.

    خارج النطاق ⇒ غير طبيعي؛ وتُعدّ حرجة إذا انحرفت أبعد من نصف امتداد
    النطاق، أو نزلت تحت نصف الحد الأدنى، أو تجاوزت 1.5× الحد الأعلى.
    """
    abnormal = critical = False
    if value is not None and (ref_min is not None or ref_max is not None):
        lo = ref_min if ref_min is not None else value
        hi = ref_max if ref_max is not None else value
        if value < lo or value > hi:
            abnormal = True
            span = max(hi - lo, abs(hi), abs(lo), 1e-9)
            dev = (lo - value) if value < lo else (value - hi)
            beyond_low = lo > 0 and value < 0.5 * lo
            beyond_high = hi > 0 and value > 1.5 * hi
            if dev > 0.5 * span or beyond_low or beyond_high:
                critical = True
    return abnormal, critical


def _load(db: Session, current_user: User, order_id: int) -> LabOrder:
    """جلب الطلب بصلاحية عرض الطبيب — غير الموجود أو المقيَّد ⇒ 404."""
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order or not _doctor_can_access(db, current_user, order):
        raise HTTPException(status_code=404, detail="لا يوجد طلب بالمعرف المحدد")
    return order


@router.get("/", response_model=List[LabOrderInDB], summary="عرض طلبات المختبر والأشعة")
async def list_lab_orders(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    doctor_id: Optional[int] = Query(None, description="فلترة حسب الطبيب"),
    status_filter: Optional[str] = Query(None, alias="status", description="فلترة حسب الحالة"),
    test_type: Optional[str] = Query(None, description="lab / radiology"),
    priority: Optional[str] = Query(None, description="routine / stat"),
    sample_status: Optional[str] = Query(None, description="none / collected / received / rejected"),
    abnormal: Optional[bool] = Query(None, description="القيم غير الطبيعية فقط"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """جلب طلبات التحاليل — الطبيب يرى طلبات مرضاه فقط"""
    q = db.query(LabOrder)

    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            return []
        q = q.filter(LabOrder.doctor_id == linked.id)

    if patient_id is not None:
        q = q.filter(LabOrder.patient_id == patient_id)
    if doctor_id is not None:
        q = q.filter(LabOrder.doctor_id == doctor_id)
    if status_filter:
        q = q.filter(LabOrder.status == status_filter)
    if test_type:
        q = q.filter(LabOrder.test_type == test_type)
    if priority is not None:
        if priority not in _PRIORITIES:
            raise HTTPException(status_code=400, detail="priority يجب أن يكون routine أو stat")
        q = q.filter(LabOrder.priority == priority)
    if sample_status is not None:
        if sample_status not in _SAMPLE_STATUSES:
            raise HTTPException(status_code=400,
                                detail="sample_status يجب أن يكون none أو collected أو received أو rejected")
        q = q.filter(LabOrder.sample_status == sample_status)
    if abnormal is not None:
        q = q.filter(LabOrder.abnormal.is_(bool(abnormal)))

    return q.order_by(LabOrder.ordered_at.desc()).all()


@router.get("/worklist", response_model=List[LabOrderInDB], summary="قائمة عملية الأجهزة (Modality Worklist)")
async def modality_worklist(
    modality: Optional[str] = Query(None, pattern="^(XRAY|CT|MRI|ULTRASOUND)$",
                                    description="نوع الجهاز للفلترة"),
    from_date: Optional[datetime] = Query(None, description="من تاريخ (شامل)"),
    to_date: Optional[datetime] = Query(None, description="إلى تاريخ (شامل)"),
    status_filter: Optional[str] = Query(None, description="حالة الطلب"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    قائمة العملية لجهاز أشعة — تُستخدم كـ Modality Worklist (MWL) للجهاز.
    تعيد طلبات الأشعة المجدولة للجهاز المحدد في النطاق الزمني.
    """
    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            return []
        doctor_id = linked.id
    else:
        doctor_id = None

    q = db.query(LabOrder).filter(LabOrder.test_type == TestType.RADIOLOGY)
    if modality:
        q = q.filter(LabOrder.modality == modality)
    if from_date:
        q = q.filter(LabOrder.scheduled_at >= from_date)
    if to_date:
        q = q.filter(LabOrder.scheduled_at <= to_date)
    if status_filter:
        q = q.filter(LabOrder.status == status_filter)
    if doctor_id:
        q = q.filter(LabOrder.doctor_id == doctor_id)

    return q.order_by(LabOrder.scheduled_at.asc()).all()


@router.get("/{order_id}", response_model=LabOrderInDB, summary="عرض طلب معين")
async def get_lab_order(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _load(db, current_user, order_id)


@router.get("/{order_id}/pdf", summary="طباعة ورقة نتيجة الطلب PDF")
async def print_lab_order(
    order_id: int,
    lang: str = Query("ar", description="ar | en"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ورقة نتيجة المختبر/الأشعة — صلاحية العرض مطابقة لعرض الطلب (404)."""
    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")
    order = _load(db, current_user, order_id)
    from fastapi.responses import Response

    from app.pdf_utils import lab_result_pdf

    filename = f"lab_result_{order.id}{'_en' if lang == 'en' else ''}.pdf"
    return Response(
        content=lab_result_pdf(order, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{filename}"'},
    )


@router.get("/{order_id}/label", summary="طباعة ملصق باركود العيّنة PDF")
async def print_sample_label(
    order_id: int,
    copies: int = Query(1, ge=1, le=20, description="عدد الملصقات (1–20)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ملصق عيّنة الباركود (Code39) لتفادي اختلاط العينات — صلاحية العرض كعرض الطلب."""
    order = _load(db, current_user, order_id)
    if not order.barcode:
        raise HTTPException(status_code=400, detail="لم تُسحب عيّنة هذا الطلب بعد — لا يوجد باركود")
    from fastapi.responses import Response

    from app.pdf_utils import sample_labels_pdf

    return Response(
        content=sample_labels_pdf(order, copies=copies),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="sample_label_{order.id}.pdf"'},
    )


@router.post("/", response_model=LabOrderInDB, summary="طلب تحليل/أشعة جديد")
async def create_lab_order(
    order: LabOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إنشاء طلب مختبر أو أشعة لمريض — الطبيب يُنسب له تلقائيًا ولا ينشئ لغيره"""
    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="لا يوجد مريض بالمعرف المحدد")
    if order.doctor_id is not None:
        doctor = db.query(Doctor).filter(Doctor.id == order.doctor_id).first()
        if not doctor:
            raise HTTPException(status_code=404, detail="لا يوجد طبيب بالمعرف المحدد")

    data = order.model_dump()

    # ربط بدليل الفحوصات: يُورَّث السعر ونوع العينة والوحدة والنطاق الطبيعي
    if data.get("lab_test_id") is not None:
        cat = db.query(LabTest).filter(LabTest.id == data["lab_test_id"]).first()
        if cat is None:
            raise HTTPException(status_code=404, detail="لا يوجد فحص بالمعرف المحدد في الدليل")
        if not data.get("price"):
            data["price"] = cat.price or 0
        for field in ("specimen_type", "unit", "ref_min", "ref_max"):
            if data.get(field) is None:
                data[field] = getattr(cat, field)

    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            raise HTTPException(status_code=403, detail="حسابك غير مرتبط بسجل طبيب")
        if data.get("doctor_id") is not None and data["doctor_id"] != linked.id:
            raise HTTPException(status_code=403, detail="يمكنك إنشاء طلباتك فقط")
        data["doctor_id"] = linked.id

    db_order = LabOrder(**data)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order


@router.post("/{order_id}/collect", response_model=LabOrderInDB, summary="سحب العيّنة وتوليد الباركود")
async def collect_lab_sample(
    order_id: int,
    payload: LabSampleCollect,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تسجيل سحب العيّنة (دم/بول/مسحة) وتوليد باركود فريد للطباعة."""
    order = _load(db, current_user, order_id)
    if order.sample_status in ("collected", "received"):
        raise HTTPException(status_code=409, detail="سُحبت عيّنة هذا الطلب مسبقًا")

    order.specimen_type = payload.specimen_type.strip()
    order.collected_by = (payload.collected_by or "").strip() or _who(current_user)
    order.collected_at = datetime.now()
    order.sample_status = "collected"
    order.barcode = _barcode_for(order)
    if order.status == LabStatus.PENDING:
        order.status = LabStatus.IN_PROGRESS
    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/receive", response_model=LabOrderInDB, summary="استلام العيّنة أو رفضها")
async def receive_lab_sample(
    order_id: int,
    payload: LabSampleReceive,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تأكيد استلام العيّنة في المختبر (تنتقل للحالة «قيد التنفيذ») أو رفضها بذكر السبب."""
    order = _load(db, current_user, order_id)
    if order.sample_status not in ("collected", "received"):
        raise HTTPException(status_code=400, detail="لا توجد عيّنة مسحوبة لهذا الطلب")

    if not payload.accepted:
        reason = (payload.reason or "").strip() or "سبب غير محدد"
        order.sample_status = "rejected"
        order.notes = f"{(order.notes + ' — ') if order.notes else ''}رُفضت العيّنة: {reason}"
        db.commit()
        db.refresh(order)
        return order

    order.sample_status = "received"
    order.received_at = datetime.now()
    if order.status == LabStatus.PENDING:
        order.status = LabStatus.IN_PROGRESS
    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/result", response_model=LabOrderInDB, summary="إدخال النتيجة وعلامات النطاق")
async def enter_lab_result(
    order_id: int,
    payload: LabResultEntry,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إدخال قيمة الفحص ومقارنتها بالنطاق الطبيعي: تمييز تلقائي للقيم غير الطبيعية والحرجة."""
    order = _load(db, current_user, order_id)
    if order.status == LabStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="لا يمكن إدخال نتيجة لطلب ملغى")
    if order.status == LabStatus.REVIEWED:
        raise HTTPException(status_code=400, detail="النتيجة معتمدة مسبقًا — لا يمكن تعديلها")
    if order.test_type == TestType.LAB and order.sample_status != "received":
        raise HTTPException(status_code=400,
                            detail="لا تُدخل النتيجة قبل سحب العيّنة واستلامها في المختبر")

    cat = getattr(order, "test_catalog", None)
    ref_min = payload.ref_min if payload.ref_min is not None else (
        order.ref_min if order.ref_min is not None else (cat.ref_min if cat else None))
    ref_max = payload.ref_max if payload.ref_max is not None else (
        order.ref_max if order.ref_max is not None else (cat.ref_max if cat else None))
    unit = payload.unit or order.unit or (cat.unit if cat else None)

    abnormal, critical = _flags_for(payload.value, ref_min, ref_max)
    critical = critical or payload.critical

    order.result = payload.result.strip()
    order.unit = unit
    order.ref_min = ref_min
    order.ref_max = ref_max
    order.abnormal = abnormal
    order.critical = critical
    order.status = LabStatus.READY
    order.result_at = datetime.now()

    name = order.patient.full_name if order.patient else "-"
    title = "⚠️ قيمة حرجة في نتيجة تحليل" if critical else "نتيجة تحليل جاهزة"
    db.add(Notification(
        type="lab_result", title=title,
        message=f"نتيجة «{order.test_name}» للمريض {name}"
                + (" — خارج النطاق الطبيعي" if abnormal else "") + " أصبحت جاهزة",
        patient_id=order.patient_id,
    ))
    db.commit()
    db.refresh(order)

    from app.notifier import notify
    notify("lab_result", f"{title}: «{order.test_name}» للمريض {name}")
    return order


@router.post("/{order_id}/verify", response_model=LabOrderInDB, summary="اعتماد التقرير وتوقيعه إلكترونيًا")
async def verify_lab_order(
    order_id: int,
    payload: LabVerify,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """توقيع إلكتروني من الطبيب الاستشاري/المدير ⇒ تصبح النتيجة «مراجَعة» ومتاحة للطبيب والمريض."""
    if get_user_role(current_user) not in ("admin", "doctor"):
        raise HTTPException(status_code=403,
                            detail="الاعتماد متاح للمدير أو الطبيب فقط")
    order = _load(db, current_user, order_id)
    if not (order.result or "").strip() and not (order.report or "").strip():
        raise HTTPException(status_code=400, detail="لا توجد نتيجة أو تقرير لاعتماده")
    if order.status == LabStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="لا يمكن اعتماد طلب ملغى")

    stamp = f" — اعتماد: {payload.note.strip()}" if payload.note else ""
    order.notes = f"{(order.notes + stamp) if order.notes else stamp.lstrip(' — ')}" or None
    order.verified_by = _who(current_user)
    order.verified_at = datetime.now()
    order.status = LabStatus.REVIEWED
    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/deliver", response_model=LabOrderInDB, summary="تسليم النتيجة للمريض")
async def deliver_lab_order(
    order_id: int,
    payload: LabVerify,  # reuse: channel in note or extend schema
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    تسجيل تسليم النتيجة للمريض — يحدد قناة التسليم (pdf, portal, whatsapp, sms, email).
    يعيد الطلب مع حقول التسليم (delivered_at, delivered_by, delivery_channel).
    """
    order = _load(db, current_user, order_id)
    if order.status not in (LabStatus.READY, LabStatus.REVIEWED):
        raise HTTPException(status_code=400,
                            detail="لا يمكن تسليم نتيجة غير جاهزة أو غير مراجعة")
    if order.delivered_at:
        raise HTTPException(status_code=409,
                            detail="تم تسليم هذه النتيجة مسبقًا")

    channel = (payload.note or "pdf").lower()
    allowed = ("pdf", "portal", "whatsapp", "sms", "email")
    if channel not in allowed:
        channel = "pdf"

    order.delivered_at = datetime.now()
    order.delivered_by = _who(current_user)
    order.delivery_channel = channel
    db.commit()
    db.refresh(order)
    return order


@router.put("/{order_id}", response_model=LabOrderInDB, summary="تحديث طلب (نتيجة/حالة/جدولة)")
async def update_lab_order(
    order_id: int,
    update: LabOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إدخال النتيجة أو تغيير الحالة أو الأولوية/الجدولة/تقرير الأشعة — عند الجاهزية يُنشأ إشعار"""
    order = _load(db, current_user, order_id)

    data = update.model_dump(exclude_unset=True)

    # النتيجة مطلوبة لحين وصول الطلب إلى "جاهزة"
    new_status = data.get("status")
    result_text = data.get("result", order.result)
    if new_status in (LabStatus.READY, LabStatus.REVIEWED) and not (result_text or "").strip():
        raise HTTPException(status_code=400, detail="أدخل نتيجة الطلب قبل جعله جاهزًا")
    if new_status == LabStatus.REVIEWED and not (
            (order.result or "").strip() or (data.get("report") or "").strip()):
        raise HTTPException(status_code=400, detail="لا توجد نتيجة أو تقرير للاعتماد")

    became_ready = (
        new_status == LabStatus.READY and order.status != LabStatus.READY
    )

    # التحقق من تضارب الجدولة عند تحديث modality/room/scheduled_at
    if any(k in data for k in ("modality", "room", "scheduled_at")):
        new_modality = data.get("modality", order.modality)
        new_room = data.get("room", order.room)
        new_scheduled = data.get("scheduled_at", order.scheduled_at)
        conflict = _check_schedule_conflict(db, new_modality, new_room, new_scheduled, order_id)
        if conflict:
            raise HTTPException(status_code=409, detail=conflict)

    for field, value in data.items():
        setattr(order, field, value)

    # حفظ تقرير الأشعة يُوسم بمن كتبه ومتى
    if "report" in data and (data.get("report") or "").strip():
        order.reported_by = order.reported_by or _who(current_user)
        order.reported_at = order.reported_at or datetime.now()

    if became_ready:
        order.result_at = datetime.now()
        db.add(Notification(
            type="lab_result",
            title="نتيجة تحليل جاهزة",
            message=f"نتيجة طلب «{order.test_name}» للمريض {order.patient.full_name if order.patient else '-'} أصبحت جاهزة",
            patient_id=order.patient_id,
        ))

    db.commit()
    db.refresh(order)

    # إشعار فوري اختياري (تلغرام/ويبهوك) عند جاهزية النتيجة — لا يُصعّد أبدًا
    if became_ready:
        from app.notifier import notify
        notify("lab_result",
               f"نتيجة «{order.test_name}» للمريض "
               f"{order.patient.full_name if order.patient else '-'} أصبحت جاهزة")
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف طلب")
async def delete_lab_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف طلب (للمدير فقط)"""
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="لا يوجد طلب بالمعرف المحدد")
    db.delete(order)
    db.commit()
    return None
