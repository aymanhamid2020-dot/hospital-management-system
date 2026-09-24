"""وصفات الدواء — إنشاء (طبيب/مدير) وصرف جماعي (أي مستخدم) وحذف (مدير).

نمط الصلاحيات مطابق لـ medical_records: الطبيب يُنسب الوصفة لنفسه عبر ربط
البريد الإلكتروني، ولا يرى وصفات غير مرضاه. الصرف كلها أو لا شيء (atomic):
تُفحص كل البنود (وجود/انتهاء/مخزون) ثم تُطبَّق في معاملة واحدة.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_user_role, require_admin
from app.database import get_db
from app.models import (
    Doctor, Dispense, Medication, Notification, Patient,
    Prescription, PrescriptionItem, StockMovement, User,
)
from app.schemas import (
    DispenseInDB, PrescriptionCreate, PrescriptionDispenseIn, PrescriptionInDB,
    PrescriptionUpdate,
)

router = APIRouter(prefix="/prescriptions", tags=["Pharmacy"])

PRESCRIPTION_STATUSES = ("PENDING", "PARTIAL", "DISPENSED", "CANCELLED")
MANUAL_STATUSES = ("PENDING", "CANCELLED")  # الحالات المسموح تعيينها يدويًا


def _linked_doctor(db: Session, user: User) -> Optional[Doctor]:
    """سجل الطبيب المرتبط بحساب المستخدم (عبر البريد الإلكتروني)."""
    return db.query(Doctor).filter(Doctor.email == user.email).first()


def _not_found():
    raise HTTPException(status_code=404, detail="لا توجد وصفة بالمعرف المحدد")


def _check_owner(db: Session, user: User, rx: Prescription,
                 detail: str = "لا تصلحية للوصول إلى هذه الوصفة"):
    """الطبيب يتعامل مع وصفات مرضاه فقط (403 عند المخالفة)."""
    if get_user_role(user) != "doctor":
        return
    linked = _linked_doctor(db, user)
    if linked is None or rx.doctor_id != linked.id:
        raise HTTPException(status_code=403, detail=detail)


@router.get("/", response_model=List[PrescriptionInDB], summary="قائمة الوصفات")
async def list_prescriptions(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    rx_status: Optional[str] = Query(None, alias="status",
                                     description="فلترة حسب الحالة"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """الطبيب يرى وصفات مرضاه فقط، وبقية الأدوار ترى كل الوصفات."""
    if rx_status is not None and rx_status not in PRESCRIPTION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status يجب أن يكون PENDING أو PARTIAL أو DISPENSED أو CANCELLED",
        )
    q = db.query(Prescription)
    if get_user_role(current_user) == "doctor":
        linked = _linked_doctor(db, current_user)
        if linked is None:
            return []
        q = q.filter(Prescription.doctor_id == linked.id)
    if patient_id is not None:
        q = q.filter(Prescription.patient_id == patient_id)
    if rx_status is not None:
        q = q.filter(Prescription.status == rx_status)
    return q.order_by(Prescription.created_at.desc()).all()


@router.get("/{rx_id}", response_model=PrescriptionInDB, summary="عرض وصفة")
async def get_prescription(
    rx_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rx = db.query(Prescription).filter(Prescription.id == rx_id).first()
    if not rx:
        _not_found()
    _check_owner(db, current_user, rx, "لا تصلحية لعرض هذه الوصفة")
    return rx


@router.get("/{rx_id}/pdf", summary="طباعة وصفة PDF")
async def print_prescription(
    rx_id: int,
    lang: str = Query("ar", description="ar | en"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ورقة الوصفة كاملة للطباعة — عربية أو إنجليزية (الصيدلية تطبعها عند
    الصرف، ويطبعها الطبيب لمرضاه). صلاحية العرض مطابقة لعرض الوصفة."""
    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")
    rx = db.query(Prescription).filter(Prescription.id == rx_id).first()
    if not rx:
        _not_found()
    _check_owner(db, current_user, rx, "لا تصلحية لطباعة هذه الوصفة")
    from app.pdf_utils import prescription_pdf
    filename = f"prescription_{rx.id}{'_en' if lang == 'en' else ''}.pdf"
    return Response(
        content=prescription_pdf(rx, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/", response_model=PrescriptionInDB, status_code=200,
             summary="إنشاء وصفة جديدة")
async def create_prescription(
    payload: PrescriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إنشاء وصفة — الطبيب يُنسبها تلقائيًا لنفسه، والمدير يحدد الطبيب."""
    role = get_user_role(current_user)
    if role not in ("doctor", "admin"):
        raise HTTPException(status_code=403,
                            detail="إنشاء الوصفات يتطلب صلاحية طبيب أو مدير")

    if not db.query(Patient).filter(Patient.id == payload.patient_id).first():
        raise HTTPException(status_code=404, detail="لا يوجد مريض بالمعرف المحدد")

    doctor_id = payload.doctor_id
    if role == "doctor":
        linked = _linked_doctor(db, current_user)
        if linked is None:
            raise HTTPException(
                status_code=403,
                detail="حسابك غير مرتبط بسجل طبيب في النظام",
            )
        doctor_id = linked.id
    elif doctor_id is not None:
        if not db.query(Doctor).filter(Doctor.id == doctor_id).first():
            raise HTTPException(status_code=404, detail="لا يوجد طبيب بالمعرف المحدد")

    if payload.record_id is not None:
        from app.models import MedicalRecord
        if not db.query(MedicalRecord).filter(
                MedicalRecord.id == payload.record_id).first():
            raise HTTPException(status_code=404, detail="لا يوجد سجل طبي بالمعرف المحدد")

    # فحص بنود الوصفة: كل دواء موجود (فشل أي بند ⇒ لا إنشاء)
    for item in payload.items:
        if not db.query(Medication).filter(Medication.id == item.medication_id).first():
            raise HTTPException(status_code=404,
                                detail=f"لا يوجد دواء بالمعرف {item.medication_id}")

    rx = Prescription(
        patient_id=payload.patient_id,
        doctor_id=doctor_id,
        record_id=payload.record_id,
        notes=payload.notes,
        status="PENDING",
        created_by=current_user.username,
    )
    db.add(rx)
    db.flush()
    for item in payload.items:
        db.add(PrescriptionItem(
            prescription_id=rx.id,
            medication_id=item.medication_id,
            quantity=item.quantity,
            dosage=item.dosage,
            frequency=item.frequency,
            duration=item.duration,
            instructions=item.instructions,
        ))
    db.commit()
    db.refresh(rx)
    return rx


@router.put("/{rx_id}", response_model=PrescriptionInDB, summary="تعديل وصفة")
async def update_prescription(
    rx_id: int,
    payload: PrescriptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تعديل الملاحظات/الحالة — الطبيب مالك الوصفة أو المدير فقط."""
    rx = db.query(Prescription).filter(Prescription.id == rx_id).first()
    if not rx:
        _not_found()

    role = get_user_role(current_user)
    if role == "doctor":
        _check_owner(db, current_user, rx, "لا تصلحية لتعديل هذه الوصفة")
    elif role != "admin":
        raise HTTPException(status_code=403,
                            detail="تعديل الوصفات يتطلب صلاحية طبيب أو مدير")

    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    if new_status is not None:
        if new_status not in MANUAL_STATUSES:
            raise HTTPException(
                status_code=400,
                detail="status اليدوي يجب أن يكون PENDING أو CANCELLED",
            )
        if new_status == "CANCELLED" and rx.status == "DISPENSED":
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إلغاء وصفة صُرفت بالكامل",
            )
        rx.status = new_status
    for field, value in data.items():
        setattr(rx, field, value)
    db.commit()
    db.refresh(rx)
    return rx


@router.delete("/{rx_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف وصفة")
async def delete_prescription(
    rx_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف وصفة (للمدير فقط) — الوصفة التي تمت صرفها تُرفض بـ 409 (تُلغى بدلًا منها)."""
    rx = db.query(Prescription).filter(Prescription.id == rx_id).first()
    if not rx:
        _not_found()
    any_dispensed = any((i.dispensed_quantity or 0) > 0 for i in rx.items)
    if any_dispensed:
        raise HTTPException(
            status_code=409,
            detail="لا يمكن حذف وصفة تمت صرفها — ألغِها بدلًا من ذلك",
        )
    db.delete(rx)
    db.commit()
    return None


@router.post("/{rx_id}/dispense", response_model=List[DispenseInDB],
             summary="صرف بنود وصفة (all-or-nothing)")
async def dispense_prescription(
    rx_id: int,
    payload: Optional[PrescriptionDispenseIn] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """صرف بنود الوصفة دفعة واحدة: كل الأبنية المعلَّقة (أو قائمة محددة).
    الفشل في أي بند (منتهٍ/ناقص/غير موجود) يمنع كل الصرف — لا تعديل نصفي."""
    rx = db.query(Prescription).filter(Prescription.id == rx_id).first()
    if not rx:
        _not_found()
    if rx.status == "CANCELLED":
        raise HTTPException(status_code=409,
                            detail="وصفة ملغاة — لا يمكن صرفها")

    all_items = db.query(PrescriptionItem).filter(
        PrescriptionItem.prescription_id == rx.id).all()
    if payload and payload.item_ids:
        wanted = set(payload.item_ids)
        known = {i.id for i in all_items}
        unknown = wanted - known
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=f"بنود غير تابعة للوصفة: {sorted(unknown)}",
            )
        selected = [i for i in all_items if i.id in wanted
                    and (i.dispensed_quantity or 0) < (i.quantity or 0)]
    else:
        selected = [i for i in all_items
                    if (i.dispensed_quantity or 0) < (i.quantity or 0)]
    if not selected:
        raise HTTPException(status_code=409,
                            detail="لا توجد أبنية معلَّقة للصرف في هذه الوصفة")

    # تجميع الكميات لكل دواء (بنود مكررة) ثم فحصها كلها قبل أي تعديل
    required: dict = {}
    for item in selected:
        qty = item.quantity - (item.dispensed_quantity or 0)
        required[item.medication_id] = required.get(item.medication_id, 0) + qty

    now = datetime.now()
    meds: dict = {}
    for med_id, qty in required.items():
        med = db.query(Medication).filter(Medication.id == med_id).first()
        if not med:
            raise HTTPException(status_code=404,
                                detail=f"لا يوجد دواء بالمعرف {med_id}")
        if med.expiry_date and med.expiry_date < now:
            raise HTTPException(
                status_code=400,
                detail=f"«{med.name}» منتهي الصلاحية "
                       f"({med.expiry_date:%Y-%m-%d}) — لا يمكن صرفه",
            )
        if qty > med.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"الكمية المطلوبة من «{med.name}» ({qty}) "
                       f"تتجاوز المتوفر ({med.quantity})",
            )
        meds[med_id] = med

    # كل الفحوص نجحت — تطبيق الصرف
    entries: List[Dispense] = []
    low_stock: List[str] = []
    crossed: set = set()
    for item in selected:
        med = meds[item.medication_id]
        qty = item.quantity - (item.dispensed_quantity or 0)
        was_above_min = med.id not in crossed and med.quantity > med.min_quantity
        med.quantity -= qty
        item.dispensed_quantity = (item.dispensed_quantity or 0) + qty
        entry = Dispense(
            medication_id=med.id,
            patient_id=rx.patient_id,
            quantity=qty,
            unit_price=med.price,
            total_price=round(qty * med.price, 2),
            dosage=item.dosage,
            frequency=item.frequency,
            duration=item.duration,
            instructions=item.instructions,
            notes=rx.notes,
            prescription_id=rx.id,
            dispensed_by=current_user.username,
        )
        db.add(entry)
        entries.append(entry)
        db.add(StockMovement(
            medication_id=med.id,
            type="out",
            change=-qty,
            quantity_after=med.quantity,
            note=f"صرف وصفة #{rx.id}",
            made_by=current_user.username,
        ))
        if was_above_min and med.quantity <= med.min_quantity and med.id not in crossed:
            crossed.add(med.id)
            low_stock.append(med.name)
            db.add(Notification(
                type="low_stock",
                title="مخزون منخفض",
                message=f"كمية «{med.name}» أصبحت {med.quantity} {med.unit} "
                        f"(حد التنبيه {med.min_quantity})",
            ))

    # تحديث حالة الوصفة: DISPENSED عند اكتمال كل الأبنية وإلا PARTIAL
    items_now = db.query(PrescriptionItem).filter(
        PrescriptionItem.prescription_id == rx.id).all()
    done = all((i.dispensed_quantity or 0) >= i.quantity for i in items_now)
    if done:
        rx.status = "DISPENSED"
        rx.dispensed_at = now
    else:
        rx.status = "PARTIAL"

    db.commit()
    for e in entries:
        db.refresh(e)

    if low_stock:
        from app.notifier import notify
        notify("low_stock", "أدوية بلغت حد التنبيه: " + "، ".join(low_stock))
    return entries
