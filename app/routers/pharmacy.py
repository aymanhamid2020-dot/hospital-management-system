from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import Dispense, Medication, Notification, Patient, StockMovement, User
from app.schemas import (
    DispenseCreate, DispenseInDB,
    MedicationCreate, MedicationInDB, MedicationUpdate,
)

medications_router = APIRouter(prefix="/medications", tags=["Pharmacy"])
dispenses_router = APIRouter(prefix="/dispenses", tags=["Pharmacy"])


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
