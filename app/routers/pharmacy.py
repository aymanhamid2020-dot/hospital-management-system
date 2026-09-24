from datetime import datetime, timedelta
from math import ceil
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func as _func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Dispense, Medication, Notification, Patient, Prescription, PrescriptionItem,
    StockMovement, User,
)
from app.schemas import (
    BatchDispenseIn, BatchDispenseOut,
    DispenseCreate, DispenseInDB, DispenseReturnIn,
    MedicationCreate, MedicationInDB, MedicationUpdate,
    PharmacyDailyStat, PharmacyStats, PharmacyTopMed, ReorderItem,
)

medications_router = APIRouter(prefix="/medications", tags=["Pharmacy"])
dispenses_router = APIRouter(prefix="/dispenses", tags=["Pharmacy"])
pharmacy_stats_router = APIRouter(prefix="/pharmacy", tags=["Pharmacy"])


def _ensure_not_expired(med: Medication, now: datetime) -> None:
    """رفض صرف دواء منتهي الصلاحية (400) — يُستخدم في كل مسارات الصرف."""
    if med.expiry_date and med.expiry_date < now:
        raise HTTPException(
            status_code=400,
            detail=f"«{med.name}» منتهي الصلاحية "
                   f"({med.expiry_date:%Y-%m-%d}) — لا يمكن صرفه",
        )


def _low_stock_crossed(med: Medication, was_above_min: bool) -> bool:
    """هل تجاوز الرصيد حد التنبيه للمرة الأولى؟"""
    return was_above_min and med.quantity <= med.min_quantity


# ===== المخزون =====
@medications_router.get("/", response_model=List[MedicationInDB], summary="عرض قائمة الأدوية")
async def list_medications(
    search: Optional[str] = Query(None, description="بحث بالاسم أو الرمز"),
    low_stock: bool = Query(False, description="التي كميتها عند حد التنبيه فقط"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    q = db.query(Medication)
    if search:
        q = q.filter((Medication.name.contains(search)) | (Medication.code.contains(search)))
    rows = q.order_by(Medication.name.asc()).all()
    if low_stock:
        rows = [m for m in rows if m.quantity <= m.min_quantity]
    return rows


@medications_router.get("/{med_id}", response_model=MedicationInDB, summary="عرض دواء معين")
async def get_medication(med_id: int, db: Session = Depends(get_db), _ = Depends(get_current_user)):
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="لا يوجد دواء بالمعرف المحدد")
    return med


@medications_router.post("/", response_model=MedicationInDB, summary="إضافة دواء للمخزون")
async def create_medication(
    med: MedicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """إضافة دواء (للمدير فقط) — الرصيد الافتتاحي يُقيَّد كحركة in في دفتر المخزون"""
    if db.query(Medication).filter(Medication.code == med.code).first():
        raise HTTPException(status_code=400, detail="رمز الدواء موجود بالفعل")
    db_med = Medication(**med.model_dump())
    db.add(db_med)
    db.flush()  # للحصول على المعرف قبل قيد الحركة
    if db_med.quantity > 0:
        db.add(StockMovement(
            medication_id=db_med.id,
            type="in",
            change=db_med.quantity,
            quantity_after=db_med.quantity,
            note="رصيد افتتاحي عند الإضافة",
            made_by=current_user.username,
        ))
    db.commit()
    db.refresh(db_med)
    return db_med


@medications_router.put("/{med_id}", response_model=MedicationInDB, summary="تحديث دواء/توريد كمية")
async def update_medication(
    med_id: int,
    med: MedicationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """تحديث بيانات الدواء أو توريد كمية (للمدير فقط) — تغيير الكمية يُقيَّد حركة"""
    db_med = db.query(Medication).filter(Medication.id == med_id).first()
    if not db_med:
        raise HTTPException(status_code=404, detail="لا يوجد دواء بالمعرف المحدد")
    old_qty = db_med.quantity
    for field, value in med.model_dump(exclude_unset=True).items():
        setattr(db_med, field, value)
    delta = db_med.quantity - old_qty
    if delta != 0:
        db.add(StockMovement(
            medication_id=db_med.id,
            type="in" if delta > 0 else "adjust",
            change=delta,
            quantity_after=db_med.quantity,
            note="تعديل كمية عبر /medications",
            made_by=current_user.username,
        ))
    db.commit()
    db.refresh(db_med)
    return db_med


@medications_router.delete("/{med_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف دواء")
async def delete_medication(
    med_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="لا يوجد دواء بالمعرف المحدد")
    db.delete(med)
    db.commit()
    return None


# ===== الصرف =====
@dispenses_router.get("/", response_model=List[DispenseInDB], summary="سجل صرف الأدوية")
async def list_dispenses(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    medication_id: Optional[int] = Query(None, description="فلترة حسب الدواء"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    q = db.query(Dispense)
    if patient_id is not None:
        q = q.filter(Dispense.patient_id == patient_id)
    if medication_id is not None:
        q = q.filter(Dispense.medication_id == medication_id)
    return q.order_by(Dispense.created_at.desc()).all()


@dispenses_router.post("/", response_model=DispenseInDB, summary="صرف دواء لمريض")
async def dispense_medication(
    payload: DispenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """صرف كمية من الدواء للمريض (يخفض المخزون + تنبيه عند الانخفاض)"""
    med = db.query(Medication).filter(Medication.id == payload.medication_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="لا يوجد دواء بالمعرف المحدد")
    patient = db.query(Patient).filter(Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="لا يوجد مريض بالمعرف المحدد")
    _ensure_not_expired(med, datetime.now())
    if payload.quantity > med.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"الكمية المطلوبة ({payload.quantity}) تتجاوز المتوفر ({med.quantity})",
        )

    was_above_min = med.quantity > med.min_quantity
    med.quantity -= payload.quantity

    entry = Dispense(
        medication_id=med.id,
        patient_id=patient.id,
        quantity=payload.quantity,
        unit_price=med.price,
        total_price=round(payload.quantity * med.price, 2),
        notes=payload.notes,
        dosage=payload.dosage,
        frequency=payload.frequency,
        duration=payload.duration,
        instructions=payload.instructions,
        dispensed_by=current_user.username,
    )
    db.add(entry)
    db.add(StockMovement(
        medication_id=med.id,
        type="out",
        change=-payload.quantity,
        quantity_after=med.quantity,
        note=f"صرف للمريض: {patient.full_name}" + (f" — {payload.notes}" if payload.notes else ""),
        made_by=current_user.username,
    ))

    # تنبيه مخزون منخفض عند تجاوز الحد للمرة الأولى
    if was_above_min and med.quantity <= med.min_quantity:
        db.add(Notification(
            type="low_stock",
            title="مخزون منخفض",
            message=f"كمية «{med.name}» أصبحت {med.quantity} {med.unit} (حد التنبيه {med.min_quantity})",
        ))

    db.commit()
    db.refresh(entry)

    # إشعار فوري اختياري (تلغرام/ويبهوك) عند أول تجاوز للحد — لا يُصعّد أبدًا
    if was_above_min and med.quantity <= med.min_quantity:
        from app.notifier import notify
        notify("low_stock",
               f"كمية «{med.name}» أصبحت {med.quantity} {med.unit} "
               f"(حد التنبيه {med.min_quantity})")
    return entry


# ===== الصرف الجماعي (سلة) — كلها أو لا شيء =====
@dispenses_router.post("/batch", response_model=BatchDispenseOut,
                       summary="صرف سلة بنود (all-or-nothing)")
async def batch_dispense(
    payload: BatchDispenseIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """صرف عدة بنود لمرضٍ واحد دفعة واحدة: تُفحص كل البنود أولًا ثم تُطبَّق
    كلها في معاملة واحدة — أي فشل (دواء ناقص/منتهٍ/غير موجود) يمنع كل الصرف."""
    patient = db.query(Patient).filter(Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="لا يوجد مريض بالمعرف المحدد")

    # تجميع الكميات المكررة لنفس الدواء حتى تُفحص الإجمالي لا كل سطر
    required: dict = {}
    for item in payload.items:
        required[item.medication_id] = required.get(item.medication_id, 0) + item.quantity

    now = datetime.now()
    meds: dict = {}
    for med_id, qty in required.items():
        med = db.query(Medication).filter(Medication.id == med_id).first()
        if not med:
            raise HTTPException(status_code=404, detail=f"لا يوجد دواء بالمعرف {med_id}")
        _ensure_not_expired(med, now)
        if qty > med.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"الكمية المطلوبة من «{med.name}» ({qty}) "
                       f"تتجاوز المتوفر ({med.quantity})",
            )
        meds[med_id] = med

    # كل الفحوص نجحت — تطبيق البنود
    entries: List[Dispense] = []
    low_stock: List[str] = []
    crossed: set = set()
    for item in payload.items:
        med = meds[item.medication_id]
        was_above_min = med.id not in crossed and med.quantity > med.min_quantity
        med.quantity -= item.quantity
        entry = Dispense(
            medication_id=med.id,
            patient_id=patient.id,
            quantity=item.quantity,
            unit_price=med.price,
            total_price=round(item.quantity * med.price, 2),
            notes=item.notes or payload.notes,
            dosage=item.dosage,
            frequency=item.frequency,
            duration=item.duration,
            instructions=item.instructions,
            dispensed_by=current_user.username,
        )
        db.add(entry)
        entries.append(entry)
        db.add(StockMovement(
            medication_id=med.id,
            type="out",
            change=-item.quantity,
            quantity_after=med.quantity,
            note=f"صرف سلة للمريض: {patient.full_name}",
            made_by=current_user.username,
        ))
        if _low_stock_crossed(med, was_above_min) and med.id not in crossed:
            crossed.add(med.id)
            low_stock.append(med.name)
            db.add(Notification(
                type="low_stock",
                title="مخزون منخفض",
                message=f"كمية «{med.name}» أصبحت {med.quantity} {med.unit} "
                        f"(حد التنبيه {med.min_quantity})",
            ))

    db.commit()
    for e in entries:
        db.refresh(e)

    if low_stock:
        from app.notifier import notify
        notify("low_stock", "أدوية بلغت حد التنبيه: " + "، ".join(low_stock))

    return BatchDispenseOut(
        patient_id=patient.id,
        count=len(entries),
        total=round(sum(e.total_price for e in entries), 2),
        low_stock=low_stock,
        dispenses=entries,
    )


# ===== إرجاع صرف =====
def _recompute_prescription_status(db: Session, prescription_id: int) -> None:
    """إعادة احتساب حالة الوصفة بعد إرجاع/صرف (PENDING/PARTIAL/DISPENSED)."""
    rx = db.query(Prescription).filter(Prescription.id == prescription_id).first()
    if not rx or rx.status == "CANCELLED":
        return
    items = db.query(PrescriptionItem).filter(
        PrescriptionItem.prescription_id == prescription_id).all()
    if not items:
        rx.status = "PENDING"
        return
    dispensed = sum(i.dispensed_quantity or 0 for i in items)
    total = sum(i.quantity or 0 for i in items)
    if dispensed <= 0:
        rx.status = "PENDING"
        rx.dispensed_at = None
    elif dispensed >= total:
        rx.status = "DISPENSED"
    else:
        rx.status = "PARTIAL"


@dispenses_router.post("/{dispense_id}/return", response_model=DispenseInDB,
                       summary="إرجاع صرف سابق")
async def return_dispense(
    dispense_id: int,
    payload: DispenseReturnIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إرجاع صرف: يعيد الكمية للمخزون (حركة return)، يُسقط أثره من
    حسابات المبيعات، ويمنع التسديد عليه (409 عند التكرار)."""
    d = db.query(Dispense).filter(Dispense.id == dispense_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="عملية الصرف غير موجودة")
    if d.returned_at is not None:
        raise HTTPException(status_code=409, detail="عملية الصرف مُرجَعة بالفعل")

    med = db.query(Medication).filter(Medication.id == d.medication_id).first()
    if med:
        med.quantity += d.quantity
        db.add(StockMovement(
            medication_id=med.id,
            type="return",
            change=d.quantity,
            quantity_after=med.quantity,
            note=f"إرجاع صرف #{d.id}: {payload.reason}",
            made_by=current_user.username,
        ))

    # إن كان الصرف مرتبطًا بوصفة — تراجع الكمية المنصَّفة وتُعدَّل الحالة
    if d.prescription_id:
        item = (db.query(PrescriptionItem)
                .filter(PrescriptionItem.prescription_id == d.prescription_id,
                        PrescriptionItem.medication_id == d.medication_id)
                .first())
        if item:
            item.dispensed_quantity = max(0, (item.dispensed_quantity or 0) - d.quantity)
        _recompute_prescription_status(db, d.prescription_id)

    d.returned_at = datetime.now()
    d.return_reason = payload.reason
    d.returned_by = current_user.username
    db.commit()
    db.refresh(d)
    return d


# ===== إحصاءات الصيدلية =====
def _parse_day(value: Optional[str], name: str) -> Optional[datetime]:
    """تفكيك تاريخ YYYY-MM-DD (صيغة خاطئة ⇒ 400)."""
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"صيغة {name} يجب أن تكون YYYY-MM-DD")


def _period_filter(q, from_date: Optional[str], to_date: Optional[str]):
    """فلترة الفترة على الاستعلام + تسميتها (التاريخ الأخير شامل ليومه كاملًا)."""
    start = _parse_day(from_date, "from_date")
    end = _parse_day(to_date, "to_date")
    if start:
        q = q.filter(Dispense.created_at >= start)
    if end:
        q = q.filter(Dispense.created_at < end + timedelta(days=1))
    if from_date or to_date:
        label = f"{from_date or '—'} إلى {to_date or '—'}"
    else:
        label = "كل الفترات"
    return q, label


def build_pharmacy_stats(db: Session, from_date: Optional[str],
                         to_date: Optional[str]) -> PharmacyStats:
    """بناء إحصاءات الصيدلية لفترة — يُستدعى من /pharmacy/stats ومن تقارير PDF/CSV.

    التجميع اليومي في Python (لا strftime لتوافق PostgreSQL).
    عمليات الإرجاع مستثناة من كل الأرقام.
    """
    q = db.query(Dispense).filter(Dispense.returned_at.is_(None))
    q, label = _period_filter(q, from_date, to_date)
    rows = q.all()

    revenue = round(sum(float(d.total_price or 0) for d in rows), 2)
    paid = round(sum(float(d.paid_amount or 0) for d in rows), 2)
    units = sum(d.quantity or 0 for d in rows)

    # أكثر الأدوية صرفًا (أول 10)
    per_med: dict = {}
    for d in rows:
        acc = per_med.setdefault(d.medication_id, {"units": 0, "revenue": 0.0})
        acc["units"] += d.quantity or 0
        acc["revenue"] += float(d.total_price or 0)
    top: List[PharmacyTopMed] = []
    if per_med:
        med_ids = list(per_med.keys())
        med_map = {m.id: m for m in db.query(Medication).filter(
            Medication.id.in_(med_ids)).all()}
        for med_id, acc in sorted(per_med.items(),
                                   key=lambda kv: (-kv[1]["units"], kv[0]))[:10]:
            med = med_map.get(med_id)
            top.append(PharmacyTopMed(
                medication_id=med_id,
                code=med.code if med else f"#{med_id}",
                name=med.name if med else f"#{med_id}",
                units=acc["units"],
                revenue=round(acc["revenue"], 2),
            ))

    # التجميع اليومي (Python — لا strftime لتوافق PostgreSQL)
    daily_map: dict = {}
    for d in rows:
        key = f"{d.created_at:%Y-%m-%d}"
        acc = daily_map.setdefault(key, {"units": 0, "revenue": 0.0})
        acc["units"] += d.quantity or 0
        acc["revenue"] += float(d.total_price or 0)
    daily = [PharmacyDailyStat(date=k, units=v["units"],
                               revenue=round(v["revenue"], 2))
             for k, v in sorted(daily_map.items())]

    # عدّادات المخزون الحالية
    now = datetime.now()
    all_meds = db.query(Medication).all()
    inventory_value = round(sum((m.quantity or 0) * (m.price or 0) for m in all_meds), 2)
    low = out = expired = expiring = 0
    for m in all_meds:
        days = (m.expiry_date - now).days if m.expiry_date else None
        if days is not None and days < 0:
            expired += 1
            continue
        if m.quantity == 0:
            out += 1
            continue
        if days is not None and days <= 30:
            expiring += 1
            continue
        if m.quantity <= m.min_quantity:
            low += 1

    return PharmacyStats(
        period=label,
        from_date=from_date or "",
        to_date=to_date or "",
        dispense_count=len(rows),
        units=units,
        revenue=revenue,
        paid=paid,
        outstanding=round(revenue - paid, 2),
        inventory_value=inventory_value,
        low=low, out=out, expired=expired, expiring=expiring,
        top_medications=top,
        daily=daily,
    )


@pharmacy_stats_router.get("/stats", response_model=PharmacyStats,
                           summary="إحصاءات الصيدلية لفترة")
async def pharmacy_stats(
    from_date: Optional[str] = Query(None, description="من تاريخ YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ YYYY-MM-DD (شامل)"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """مبيعات واستهلاك فترة مع عدّادات المخزون الحالية (المرتجع مستثنى)."""
    return build_pharmacy_stats(db, from_date, to_date)


def build_reorder(db: Session, days: int = 30) -> List[ReorderItem]:
    """اقتراحات إعادة الطلب — مسار مشترك بين /pharmacy/reorder وتصدير CSV."""
    since = datetime.now() - timedelta(days=days)
    consumed_map: dict = {}
    rows = (db.query(Dispense.medication_id, _func.sum(Dispense.quantity))
            .filter(Dispense.created_at >= since,
                    Dispense.returned_at.is_(None))
            .group_by(Dispense.medication_id).all())
    for mid, total in rows:
        consumed_map[mid] = int(total or 0)

    now = datetime.now()
    out: List[ReorderItem] = []
    for m in db.query(Medication).order_by(Medication.name.asc()).all():
        if m.quantity > m.min_quantity and m.quantity > 0:
            continue  # الأصناف السليمة ليست بحاجة لإعادة طلب
        days_left = (m.expiry_date - now).days if m.expiry_date else None
        if days_left is not None and days_left < 0 and m.quantity == 0:
            continue  # منتهٍ ونافد تمامًا: لا شراء له — يُتلف سجله
        consumed = consumed_map.get(m.id, 0)
        avg = round(consumed / days, 4)
        cover = round((m.quantity or 0) / avg, 1) if avg > 0 else None
        suggested = max(0, int(ceil(avg * 30)) + (m.min_quantity or 0) - (m.quantity or 0))
        if m.quantity == 0 and suggested == 0:
            suggested = max(m.min_quantity, 1)
        out.append(ReorderItem(
            medication_id=m.id, code=m.code, name=m.name,
            quantity=m.quantity, min_quantity=m.min_quantity, unit=m.unit,
            price=m.price, consumed=consumed, avg_per_day=avg,
            days_cover=cover, suggested_qty=suggested,
            suggested_cost=round(suggested * (m.price or 0), 2),
        ))
    return out


@pharmacy_stats_router.get("/reorder", response_model=List[ReorderItem],
                           summary="اقتراحات إعادة الطلب")
async def reorder_suggestions(
    days: int = Query(30, ge=1, le=365, description="نافذة الاستهلاك بالأيام (1–365)"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """الأصناف المنخفضة/النافدة: معدل الاستهلاك، أيام التغطية، والكمية المقترحة
    للشراء = (متوسط يومي × 30) + حد التنبيه − الرصيد الحالي."""
    return build_reorder(db, days)
