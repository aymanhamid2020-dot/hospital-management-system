from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import Payroll, PayrollStatus, Staff, User
from app.schemas import PayrollCreate, PayrollInDB, PayrollUpdate

router = APIRouter(
    prefix="/payroll",
    tags=["Payroll"],
    dependencies=[Depends(require_admin)],  # الرواتب للمدير فقط
)


def _net(base: float, bonus: float, deduction: float) -> float:
    return round(float(base) + float(bonus) - float(deduction), 2)


@router.get("/", response_model=List[PayrollInDB], summary="عرض كشف الرواتب")
async def list_payroll(
    staff_id: Optional[int] = Query(None, description="فلترة حسب الموظف"),
    period: Optional[str] = Query(None, description="الشهر YYYY-MM"),
    status_filter: Optional[str] = Query(None, alias="status", description="unpaid / paid"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(Payroll)
    if staff_id is not None:
        q = q.filter(Payroll.staff_id == staff_id)
    if period:
        q = q.filter(Payroll.period == period)
    if status_filter:
        q = q.filter(Payroll.status == status_filter)
    return q.order_by(Payroll.period.desc(), Payroll.id.desc()).all()


@router.post("/", response_model=PayrollInDB, summary="إنشاء قيد راتب")
async def create_payroll(
    entry: PayrollCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """إنشاء قيد راتب شهري — الصافي = أساسي + بدلات − استقطاعات"""
    staff = db.query(Staff).filter(Staff.id == entry.staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="لا يوجد موظف بالمعرف المحدد")
    dup = (
        db.query(Payroll)
        .filter(Payroll.staff_id == entry.staff_id, Payroll.period == entry.period)
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="يوجد قيد راتب لهذا الموظف في نفس الفترة")

    # إن لم يُدخل أساسي ⇒ يُستخدم راتب الموظف المسجّل
    base = entry.base_salary or (staff.salary or 0)
    db_entry = Payroll(
        staff_id=entry.staff_id,
        period=entry.period,
        base_salary=base,
        bonus=entry.bonus,
        deduction=entry.deduction,
        net=_net(base, entry.bonus, entry.deduction),
        notes=entry.notes,
    )
    if db_entry.net < 0:
        raise HTTPException(status_code=400, detail="الصافي لا يمكن أن يكون سالبًا")
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    # إثبات استحقاق تلقائي: مصروف الرواتب مقابل مستحقات الموظفين — الفشل
    # لا يُسقط إنشاء القيد؛ يبقى الترحيل اليدوي من شاشة المحاسبة بديلًا.
    from app.routers.accounting import auto_post_payroll
    auto_post_payroll(db, db_entry, user.username, kind="accrual")
    db.refresh(db_entry)
    return db_entry


@router.put("/{entry_id}", response_model=PayrollInDB, summary="تحديث قيد راتب")
async def update_payroll(
    entry_id: int,
    update: PayrollUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    entry = db.query(Payroll).filter(Payroll.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="لا يوجد قيد بالمعرف المحدد")

    data = update.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(entry, field, value)
    entry.net = _net(entry.base_salary, entry.bonus, entry.deduction)
    if entry.net < 0:
        raise HTTPException(status_code=400, detail="الصافي لا يمكن أن يكون سالبًا")
    db.commit()
    db.refresh(entry)
    # إن كان الاستحقاق قد أُثبِّت قبل التعديل ⇒ قيد تعديل يوازن الفرق،
    # فلا تبقى الذمة بالمبلغ القديم وينحرف الصرف لاحقًا عنها.
    from app.routers.accounting import auto_post_payroll_adjustment
    auto_post_payroll_adjustment(db, entry, user.username)
    db.refresh(entry)
    return entry


@router.post("/{entry_id}/pay", response_model=PayrollInDB, summary="صرف راتب")
async def pay_payroll(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    entry = db.query(Payroll).filter(Payroll.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="لا يوجد قيد بالمعرف المحدد")
    if entry.status == PayrollStatus.PAID:
        raise HTTPException(status_code=400, detail="الراتب مُصرف بالفعل")
    entry.status = PayrollStatus.PAID
    entry.paid_at = datetime.now()
    db.commit()
    db.refresh(entry)
    # قيد الصرف لحظة الصرف: إقفال المستحق مقابل النقدية (يُثبِّت
    # الاستحقاق أولًا إن كان الراتب أُنشئ قبل هذا المسار)
    from app.routers.accounting import auto_post_payroll
    auto_post_payroll(db, entry, user.username, kind="disbursement")
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف قيد راتب")
async def delete_payroll(
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    entry = db.query(Payroll).filter(Payroll.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="لا يوجد قيد بالمعرف المحدد")
    db.delete(entry)
    db.commit()
    return None
