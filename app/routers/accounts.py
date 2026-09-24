"""حسابات المبيعات — سجل المبيعات، الملخص، وتسجيل الدفع."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func as _func

from app.database import get_db
from app.models import Dispense, Patient, User
from app.auth import get_current_user
from app.schemas import Debtor, DispenseInDB, RevenuePoint, SalePayment, SaleSummary

router = APIRouter(prefix="/accounts", tags=["Accounts & Sales"])


def _apply_period(q, period: Optional[str], from_date: Optional[str], to_date: Optional[str]):
    """توحيد فلترة الفترة بين/و داخل الشهر — يعيد (الاستعلام، تسمية الفترة)."""
    if from_date or to_date:
        if from_date:
            q = q.filter(Dispense.created_at >= from_date)
        if to_date:
            q = q.filter(Dispense.created_at <= to_date)
        return q, f"{from_date or '—'} إلى {to_date or '—'}"
    if period:
        try:
            dt = datetime.strptime(period, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="صيغة الفترة يجب أن تكون YYYY-MM")
        nxt = datetime(dt.year + (1 if dt.month == 12 else 0),
                       1 if dt.month == 12 else dt.month + 1, 1)
        return q.filter(Dispense.created_at >= dt, Dispense.created_at < nxt), period
    return q, "كل الفترات"


@router.get("/sales", response_model=List[DispenseInDB], summary="سجل المبيعات")
async def list_sales(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    staff: Optional[str] = Query(None, description="فلترة باسم صرف المستخدم"),
    payment_method: Optional[str] = Query(None, description="طريقة الدفع"),
    _status: Optional[str] = Query(None, alias="status", description="حالة الدفع UNPAID/PARTIAL/PAID"),
    from_date: Optional[str] = Query(None, description="من تاريخ (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    q = db.query(Dispense).order_by(Dispense.created_at.desc())
    if patient_id is not None:
        q = q.filter(Dispense.patient_id == patient_id)
    if staff:
        q = q.filter(Dispense.dispensed_by.like(f"%{staff}%"))
    if payment_method:
        q = q.filter(Dispense.payment_method == payment_method)
    if _status:
        q = q.filter(Dispense.status == _status)
    if from_date:
        q = q.filter(Dispense.created_at >= from_date)
    if to_date:
        q = q.filter(Dispense.created_at <= to_date)
    return q.all()


@router.get("/summary", response_model=SaleSummary, summary="ملخص المبيعات")
async def sales_summary(
    period: Optional[str] = Query(None, description="الشهر YYYY-MM (اختياري)"),
    from_date: Optional[str] = Query(None, description="من تاريخ"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    q = db.query(Dispense)
    q, label = _apply_period(q, period, from_date, to_date)

    agg = q.with_entities(
        _func.sum(Dispense.total_price),
        _func.sum(Dispense.paid_amount),
        _func.count(Dispense.id),
    ).one()
    total_sales = float(agg[0] or 0)
    total_paid = float(agg[1] or 0)
    count = agg[2] or 0
    pm_rows = q.with_entities(
        Dispense.payment_method, _func.sum(Dispense.total_price)
    ).group_by(Dispense.payment_method).all()
    by_payment_method = {m: float(v or 0) for m, v in pm_rows}
    return SaleSummary(
        period=label, total_sales=total_sales, total_paid=total_paid,
        total_outstanding=round(total_sales - total_paid, 2),
        count=count, by_payment_method=by_payment_method,
    )


@router.get("/revenue", response_model=List[RevenuePoint], summary="منحنى الإيراد")
async def revenue_curve(
    period: Optional[str] = Query(None, description="الشهر YYYY-MM"),
    from_date: Optional[str] = Query(None, description="من تاريخ"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ"),
    group: str = Query("day", description="التجميع: day أو month"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """سلسلة إيراد مجمّعة يوميًا أو شهريًا (لرسم بياني)"""
    if group not in ("day", "month"):
        raise HTTPException(status_code=400, detail="group يجب أن يكون day أو month")
    q = db.query(Dispense)
    q, _label = _apply_period(q, period, from_date, to_date)

    if group == "day":
        bucket = _func.strftime("%Y-%m-%d", Dispense.created_at)
    else:
        bucket = _func.strftime("%Y-%m", Dispense.created_at)

    rows = (
        q.with_entities(
            bucket.label("bucket"),
            _func.sum(Dispense.total_price),
            _func.sum(Dispense.paid_amount),
            _func.count(Dispense.id),
        )
        .group_by(bucket)
        .order_by(bucket.asc())
        .all()
    )
    return [
        RevenuePoint(date=str(b), sales=float(s or 0),
                     collected=float(c or 0), count=int(n or 0))
        for b, s, c, n in rows
    ]


@router.get("/debtors", response_model=List[Debtor], summary="المدينون")
async def debtors(
    period: Optional[str] = Query(None, description="الشهر YYYY-MM"),
    from_date: Optional[str] = Query(None, description="من تاريخ"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ"),
    min_outstanding: float = Query(0, ge=0, description="أدنى مبلغ متبقٍ"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """المرضى الذين باقي عليهم مبلغ (مرتّبون تنازليًا حسب المتبقي)"""
    q = db.query(Dispense).filter(Dispense.status != "PAID")
    q, _label = _apply_period(q, period, from_date, to_date)

    rows = (
        q.with_entities(
            Dispense.patient_id,
            _func.count(Dispense.id),
            _func.sum(Dispense.total_price),
            _func.sum(Dispense.paid_amount),
        )
        .group_by(Dispense.patient_id)
        .all()
    )
    out = []
    for pid, n, total, paid in rows:
        outstanding = round(float(total or 0) - float(paid or 0), 2)
        if outstanding < min_outstanding:
            continue
        patient = db.query(Patient).filter(Patient.id == pid).first()
        out.append(Debtor(
            patient_id=pid,
            full_name=patient.full_name if patient else f"#{pid}",
            operations=int(n or 0),
            total=float(total or 0),
            paid=float(paid or 0),
            outstanding=outstanding,
        ))
    out.sort(key=lambda d: d.outstanding, reverse=True)
    return out


@router.get("/sales/{id}", response_model=DispenseInDB, summary="تفاصيل عملية بيع")
async def sale_detail(id: int, db: Session = Depends(get_db), _ = Depends(get_current_user)):
    d = db.query(Dispense).filter(Dispense.id == id).first()
    if not d:
        raise HTTPException(status_code=404, detail="عملية البيع غير موجودة")
    return d


@router.put("/sales/{id}/payment", response_model=DispenseInDB, summary="تسجيل دفعة")
async def record_payment(
    id: int,
    payload: SalePayment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تسجيل مبلغ مدفوع وتحديث الحالة (PAID إذا وصل للإجمالي، PARTIAL خلاف ذلك)"""
    d = db.query(Dispense).filter(Dispense.id == id).first()
    if not d:
        raise HTTPException(status_code=404, detail="عملية البيع غير موجودة")
    if payload.paid_amount <= 0:
        raise HTTPException(status_code=400, detail="المبلغ يجب أن يكون أكبر من صفر")
    if payload.paid_amount > d.total_price:
        raise HTTPException(status_code=400, detail="المدفوع يتجاوز مبلغ العملية")
    # صلاحية أدق: لا يُسمح بإعادة تسديد عملية مسدّدة بالكامل (409)
    if d.status == "PAID":
        raise HTTPException(
            status_code=409,
            detail="العملية مسدّدة بالكامل — لا يمكن تسجيل دفعة جديدة عليها",
        )
    d.paid_amount = round(payload.paid_amount, 2)
    d.payment_method = payload.payment_method
    d.paid_at = datetime.now()
    d.status = "PAID" if d.paid_amount >= d.total_price else "PARTIAL"
    db.commit()
    db.refresh(d)
    return d


@router.get("/sales/{id}/receipt", summary="إيصال دفعة (HTML للطباعة)")
async def sale_receipt(
    id: int,
    lang: str = Query("ar", description="لغة الإيصال: ar أو en"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """إيصال طباعة لعملية بيع واحدة — ar|en (لغة خاطئة ⇒ 400)"""
    from fastapi.responses import HTMLResponse

    from app.receipt_template import sale_receipt_html

    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")
    d = db.query(Dispense).filter(Dispense.id == id).first()
    if not d:
        raise HTTPException(status_code=404, detail="عملية البيع غير موجودة")
    return HTMLResponse(sale_receipt_html(d, lang=lang))


@router.get("/statement/{patient_id}", summary="كشف حساب مريض (JSON)")
async def patient_statement(
    patient_id: int,
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """ملخص كشف الحساب: مبيعات الصيدلية + الفواتير + الأرصدة"""
    from app.models import Invoice

    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="المريض غير موجود")

    sales = (db.query(Dispense).filter(Dispense.patient_id == patient_id)
             .order_by(Dispense.created_at.desc()).all())
    invoices = (db.query(Invoice).filter(Invoice.patient_id == patient_id)
                .order_by(Invoice.created_at.desc()).all())

    sales_total = round(sum(float(s.total_price or 0) for s in sales), 2)
    sales_paid = round(sum(float(s.paid_amount or 0) for s in sales), 2)
    inv_total = round(sum(i.total for i in invoices), 2)
    inv_paid = round(sum(float(i.paid_amount or 0) for i in invoices), 2)
    dues = round(sales_total + inv_total, 2)
    outstanding = round((sales_total - sales_paid) + (inv_total - inv_paid), 2)
    return {
        "patient": {"id": p.id, "full_name": p.full_name, "phone": p.phone or ""},
        "sales": [DispenseInDB.model_validate(s).model_dump(mode="json") for s in sales],
        "invoices": [{"id": i.id,
                      "created_at": i.created_at,
                      "description": i.description,
                      "total": i.total,
                      "paid_amount": float(i.paid_amount or 0),
                      "payment_method": i.payment_method,
                      "status": i.status.value if hasattr(i.status, "value") else str(i.status)}
                     for i in invoices],
        "totals": {"sales_total": sales_total, "sales_paid": sales_paid,
                   "inv_total": inv_total, "inv_paid": inv_paid,
                   "dues": dues, "outstanding": outstanding},
    }


@router.get("/statement/{patient_id}/print", summary="كشف حساب مريض (HTML للطباعة)")
async def patient_statement_print(
    patient_id: int,
    lang: str = Query("ar", description="لغة الكشف: ar أو en"),
    db: Session = Depends(get_db),
    _ = Depends(get_current_user),
):
    """كشف حساب قابل للطباعة — ar|en (لغة خاطئة ⇒ 400)"""
    from fastapi.responses import HTMLResponse

    from app.models import Invoice
    from app.receipt_template import patient_statement_html

    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="المريض غير موجود")

    sales = (db.query(Dispense).filter(Dispense.patient_id == patient_id)
             .order_by(Dispense.created_at.desc()).all())
    invoices = (db.query(Invoice).filter(Invoice.patient_id == patient_id)
                .order_by(Invoice.created_at.desc()).all())
    sales_total = round(sum(float(s.total_price or 0) for s in sales), 2)
    sales_paid = round(sum(float(s.paid_amount or 0) for s in sales), 2)
    inv_total = round(sum(i.total for i in invoices), 2)
    inv_paid = round(sum(float(i.paid_amount or 0) for i in invoices), 2)
    totals = {
        "sales_total": sales_total, "sales_paid": sales_paid,
        "inv_total": inv_total, "inv_paid": inv_paid,
        "dues": round(sales_total + inv_total, 2),
        "outstanding": round((sales_total - sales_paid) + (inv_total - inv_paid), 2),
    }
    return HTMLResponse(patient_statement_html(p, sales, invoices, totals, lang=lang))
