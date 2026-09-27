"""دورة الإيراد: التسعير · العروض والباقات · الودائع · إغلاق الصندوق ·
الموافقات المسبقة · حزم المطالبات · إشعارات الدائن · تقارير المبيعات.

كل ما يكمّل دورة الفاتورة: من التسعير والعرض السعر، إلى التحصيل وإغلاق
الصندوق، إلى مطالبة التأمين وتسوية رفضها، وصولًا لتقرير مبيعات مفصّل.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Admission, CashierShift, ClaimBatch, ClaimBatchItem, ClaimStatus, CreditNote,
    DiscountRule,
    Dispense, InsuranceClaim, Invoice, InvoiceStatus,
    PackageItem, Patient, PatientDeposit, PriorAuthorization, PriceList, PriceListItem,
    Quotation, QuotationItem, ServicePackage, StockDoc, StockDocLine, User,
)
from app.routers.accounting import _ensure_chart, _money, _new_entry
from app.routers.stock_ops import _next_doc_no, _warehouse
from app.schemas import (
    ClaimBatchBuildIn, ClaimBatchItemOut, ClaimBatchOut, ClaimBatchSubmitIn,
    CreditNoteIn, CreditNoteOut, DepositApplyIn, DepositIn, DepositOut,
    DiscountRuleIn, DiscountRuleOut, PackageItemOut, PriorAuthDecisionIn, PriorAuthIn,
    PriorAuthOut, PriceCheckOut, PriceListIn, PriceListItemOut, PriceListOut,
    QuotationIn, QuotationLineIn, QuotationLineOut, QuotationOut, QuotationStatusIn,
    SalesReportOut,
    SalesReportRow, ServicePackageIn, ServicePackageOut, ShiftCloseIn, ShiftOpenIn,
    ShiftOut,
)

router = APIRouter(prefix="/revenue", tags=["Revenue Cycle"])

QUOTE_STATUSES = ("sent", "accepted", "rejected", "expired")
PRIOR_STATUSES = ("approved", "partially_approved", "denied")


# ===== أدوات =====
def _seq_no(db: Session, model, column, prefix: str) -> str:
    """رقم متسلسل لا يتعارض: QUO-00001 / DEP-00001 / CN-00001."""
    n = 1
    while db.query(model).filter(column == f"{prefix}-{n:05d}").first():
        n += 1
    return f"{prefix}-{n:05d}"


def _patient(db: Session, pid: int) -> Patient:
    p = db.query(Patient).filter(Patient.id == pid).first()
    if not p:
        raise HTTPException(404, "المريض غير موجود")
    return p


def _active_discount_rule(db: Session, scope: str) -> Optional[DiscountRule]:
    return (db.query(DiscountRule)
            .filter(DiscountRule.is_active.is_(True),
                    or_(DiscountRule.scope == scope, DiscountRule.scope == "all"))
            .order_by(DiscountRule.max_percent.desc()).first())


# ================================================================
# 5) التسعير والخصومات
# ================================================================
@router.get("/price-lists", response_model=List[PriceListOut],
            summary="قوائم الأسعار مع بنودها")
def list_price_lists(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    out = []
    for pl in db.query(PriceList).order_by(PriceList.id).all():
        out.append(PriceListOut(
            id=pl.id, code=pl.code, name=pl.name, insurer=pl.insurer,
            patient_category=pl.patient_category, is_default=pl.is_default,
            is_active=pl.is_active, notes=pl.notes, created_at=pl.created_at,
            items_count=len(pl.items),
            items=[PriceListItemOut(id=x.id, service_code=x.service_code,
                                    service_name=x.service_name,
                                    unit_price=x.unit_price, is_active=x.is_active)
                   for x in pl.items if x.is_active]))
    return out


@router.post("/price-lists", response_model=PriceListOut, status_code=201,
             summary="إنشاء قائمة أسعار ببنودها")
def create_price_list(payload: PriceListIn, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    if db.query(PriceList).filter(PriceList.code == payload.code).first():
        raise HTTPException(409, "كود قائمة الأسعار مستخدم مسبقًا")
    if payload.is_default:
        for other in db.query(PriceList).filter(PriceList.is_default.is_(True)).all():
            other.is_default = False
    pl = PriceList(**{k: v for k, v in payload.model_dump().items() if k != "lines"},
                   created_at=datetime.now())
    db.add(pl)
    db.flush()
    for ln in payload.lines:
        db.add(PriceListItem(price_list_id=pl.id, service_code=ln.service_code,
                             service_name=ln.service_name, unit_price=ln.unit_price,
                             is_active=ln.is_active))
    db.commit()
    db.refresh(pl)
    return PriceListOut(
        id=pl.id, code=pl.code, name=pl.name, insurer=pl.insurer,
        patient_category=pl.patient_category, is_default=pl.is_default,
        is_active=pl.is_active, notes=pl.notes, created_at=pl.created_at,
        items_count=len(payload.lines),
        items=[PriceListItemOut(id=0, service_code=x.service_code,
                                service_name=x.service_name,
                                unit_price=x.unit_price, is_active=x.is_active)
               for x in payload.lines])


@router.get("/price-lists/resolve", summary="سعر خدمة من أنسب قائمة (تأمين/فئة/افتراضية)")
def resolve_price(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                  service_code: str = Query(..., min_length=1),
                  insurer: Optional[str] = Query(None),
                  patient_category: Optional[str] = Query(None)):
    """ترتيب الأولوية: قائمة التأمين ← فئة المريض ← الافتراضية."""
    q = db.query(PriceListItem).join(PriceList).filter(
        PriceListItem.service_code == service_code,
        PriceListItem.is_active.is_(True), PriceList.is_active.is_(True))
    rows = q.all()
    pick = None
    for want in ("insurer", "category", "default"):
        for it in rows:
            pl = it.price_list
            if want == "insurer" and insurer and pl.insurer == insurer:
                pick = it
            elif want == "category" and patient_category and \
                    pl.patient_category == patient_category:
                pick = pick or it
            elif want == "default" and pl.is_default:
                pick = pick or it
        if pick:
            break
    if not pick and rows:
        pick = rows[0]
    if not pick:
        raise HTTPException(404, f"لا يوجد سعر للخدمة {service_code}")
    return {"service_code": pick.service_code, "service_name": pick.service_name,
            "unit_price": _money(pick.unit_price),
            "price_list": pick.price_list.name, "price_list_id": pick.price_list_id}


@router.get("/discount-rules", response_model=List[DiscountRuleOut], summary="سياسات الخصم")
def list_discount_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(DiscountRule).order_by(DiscountRule.id).all()


@router.post("/discount-rules", response_model=DiscountRuleOut, status_code=201,
             summary="إضافة سياسة خصم")
def create_discount_rule(payload: DiscountRuleIn, db: Session = Depends(get_db),
                         user: User = Depends(require_admin)):
    row = DiscountRule(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/discount-rules/check", response_model=PriceCheckOut,
            summary="فحص نسبة خصم مقابل السياسة السارية")
def check_discount(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                   percent: float = Query(..., ge=0, le=100),
                   scope: str = Query("all")):
    """الواجهة تستدعيها أثناء الكتابة لتنبيه الموظف قبل الحفظ."""
    rule = _active_discount_rule(db, scope)
    if not rule:
        return PriceCheckOut(allowed=True, max_percent=100, requested_percent=percent,
                             requires_approval=False)
    return PriceCheckOut(allowed=percent <= rule.max_percent,
                         max_percent=rule.max_percent, requested_percent=percent,
                         requires_approval=rule.requires_approval, rule_name=rule.name)


# ================================================================
# 4) الباقات وعروض الأسعار
# ================================================================
def _package_out(pkg: ServicePackage) -> ServicePackageOut:
    lines = [PackageItemOut(id=x.id, service_code=x.service_code, service_name=x.service_name,
                            quantity=x.quantity, unit_price=x.unit_price,
                            line_total=_money(x.quantity * x.unit_price)) for x in pkg.items]
    list_total = _money(sum(x.line_total for x in lines))
    return ServicePackageOut(id=pkg.id, code=pkg.code, name=pkg.name,
                             description=pkg.description,
                             package_price=_money(pkg.package_price),
                             list_total=list_total,
                             saving=_money(max(0, list_total - pkg.package_price)),
                             is_active=pkg.is_active, created_at=pkg.created_at,
                             lines=lines)


@router.get("/packages", response_model=List[ServicePackageOut], summary="باقات الخدمات")
def list_packages(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_package_out(p) for p in
            db.query(ServicePackage).order_by(ServicePackage.id).all()]


@router.post("/packages", response_model=ServicePackageOut, status_code=201,
             summary="إنشاء باقة خدمات ببنودها")
def create_package(payload: ServicePackageIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    if db.query(ServicePackage).filter(ServicePackage.code == payload.code).first():
        raise HTTPException(409, "كود الباقة مستخدم مسبقًا")
    pkg = ServicePackage(code=payload.code, name=payload.name,
                         description=payload.description,
                         package_price=payload.package_price,
                         is_active=payload.is_active)
    db.add(pkg)
    db.flush()
    total = 0.0
    for ln in payload.lines:
        db.add(PackageItem(package_id=pkg.id, service_code=ln.service_code,
                           service_name=ln.service_name, quantity=ln.quantity,
                           unit_price=ln.unit_price))
        total += ln.quantity * ln.unit_price
    pkg.list_total = _money(total)
    db.commit()
    db.refresh(pkg)
    return _package_out(pkg)


@router.get("/quotations", response_model=List[QuotationOut], summary="عروض الأسعار")
def list_quotations(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                    status: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200)):
    q = db.query(Quotation)
    if status:
        q = q.filter(Quotation.status == status)
    rows = q.order_by(Quotation.id.desc()).limit(limit).all()
    names = {p.id: p.full_name for p in db.query(Patient).filter(
        Patient.id.in_({x.patient_id for x in rows})).all()} if rows else {}
    return [_quote_out(db, x, names.get(x.patient_id)) for x in rows]


def _quote_out(db: Session, q: Quotation, patient_name: Optional[str] = None) -> QuotationOut:
    return QuotationOut(
        id=q.id, quote_no=q.quote_no, patient_id=q.patient_id,
        patient_name=patient_name, package_id=q.package_id, title=q.title,
        status=q.status, subtotal=_money(q.subtotal), discount=_money(q.discount),
        tax_rate=q.tax_rate, total=_money(q.total), valid_until=q.valid_until,
        notes=q.notes, invoice_id=q.invoice_id, created_by=q.created_by,
        created_at=q.created_at,
        lines=[QuotationLineOut(id=x.id, service_code=x.service_code,
                                description=x.description, quantity=x.quantity,
                                unit_price=x.unit_price, line_total=x.line_total)
               for x in q.lines])


@router.post("/quotations", response_model=QuotationOut, status_code=201,
             summary="إنشاء عرض سعر (يدويًا أو من باقة)")
def create_quotation(payload: QuotationIn, db: Session = Depends(get_db),
                     user: User = Depends(require_admin)):
    patient = _patient(db, payload.patient_id)
    lines = list(payload.lines)
    package_price = None
    pkg = None
    if payload.package_id:
        pkg = db.query(ServicePackage).filter(
            ServicePackage.id == payload.package_id, ServicePackage.is_active.is_(True)).first()
        if not pkg:
            raise HTTPException(404, "الباقة غير موجودة أو معطّلة")
        if not lines:   # الباقة وحدها هي العرض
            lines = [QuotationLineIn(service_code=x.service_code,
                                     description=x.service_name, quantity=x.quantity,
                                     unit_price=x.unit_price) for x in pkg.items]
            package_price = _money(pkg.package_price)
        elif package_price is None:
            package_price = _money(pkg.package_price)
    if not lines:
        raise HTTPException(400, "أضف بندًا واحدًا على الأقل أو اختر باقة")
    subtotal = _money(sum(x.quantity * x.unit_price for x in lines))
    if package_price is not None and package_price < subtotal:
        # بنود مخصومة بسعر الباقة ⇒ فرق الباقة خصم تلقائي
        payload.discount = _money(payload.discount + (subtotal - package_price))
    if payload.discount > subtotal + .01:
        raise HTTPException(400, "الخصم يتجاوز إجمالي البنود")
    total = _money(subtotal - payload.discount +
                   (subtotal - payload.discount) * payload.tax_rate / 100.0)
    q = Quotation(quote_no=_seq_no(db, Quotation, Quotation.quote_no, "QUO"),
                  patient_id=patient.id, package_id=payload.package_id,
                  title=payload.title, status="draft", subtotal=subtotal,
                  discount=_money(payload.discount), tax_rate=payload.tax_rate,
                  total=total, valid_until=datetime.now() + timedelta(days=payload.valid_days),
                  notes=payload.notes, created_by=user.username, created_at=datetime.now())
    db.add(q)
    db.flush()
    for ln in lines:
        db.add(QuotationItem(quotation_id=q.id, service_code=ln.service_code,
                             description=ln.description, quantity=ln.quantity,
                             unit_price=_money(ln.unit_price),
                             line_total=_money(ln.quantity * ln.unit_price)))
    db.commit()
    db.refresh(q)
    return _quote_out(db, q, patient.full_name)


@router.put("/quotations/{quote_id}/status", response_model=QuotationOut,
            summary="تغيير حالة عرض السعر (أُرسل/قُبل/رُفض/انتهى)")
def set_quotation_status(quote_id: int, payload: QuotationStatusIn,
                         db: Session = Depends(get_db), user: User = Depends(require_admin)):
    q = db.query(Quotation).filter(Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(404, "عرض السعر غير موجود")
    st = payload.status.strip().lower()
    if st not in QUOTE_STATUSES:
        raise HTTPException(400, "الحالة يجب أن تكون sent أو accepted أو rejected أو expired")
    if q.status == "converted":
        raise HTTPException(400, "لا يمكن تغيير حالة عرض محوَّل إلى فاتورة")
    q.status = st
    db.commit()
    db.refresh(q)
    return _quote_out(db, q)


@router.post("/quotations/{quote_id}/convert", response_model=QuotationOut,
             summary="تحويل عرض السعر المقبول إلى فاتورة")
def convert_quotation(quote_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    q = db.query(Quotation).filter(Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(404, "عرض السعر غير موجود")
    if q.invoice_id:
        raise HTTPException(409, "هذا العرض حُوّل مسبقًا إلى فاتورة")
    if q.status not in ("accepted", "draft"):
        raise HTTPException(400, "لا يُحوَّل العرض إلا بعد قبوله")
    if q.valid_until and q.valid_until < datetime.now():
        raise HTTPException(400, "انتهت صلاحية العرض")
    inv = Invoice(patient_id=q.patient_id, amount=q.subtotal, discount=q.discount,
                  tax_rate=q.tax_rate, paid_amount=0, status=InvoiceStatus.UNPAID,
                  description=f"فاتورة من عرض السعر {q.quote_no} — {q.title}")
    db.add(inv)
    db.flush()
    q.invoice_id, q.status = inv.id, "converted"
    db.commit()
    db.refresh(q)
    return _quote_out(db, q)

# ================================================================
# 2) السندات والتحصيل: الدفعات المقدمة وإغلاق الصندوق
# ================================================================
def _deposit_out(db: Session, d: PatientDeposit, name: Optional[str] = None) -> DepositOut:
    return DepositOut(
        id=d.id, patient_id=d.patient_id, patient_name=name, invoice_id=d.invoice_id,
        admission_id=d.admission_id, amount=_money(d.amount),
        applied_amount=_money(d.applied_amount),
        balance=_money(max(0.0, d.amount - d.applied_amount)),
        status=d.status, method=d.method, reference=d.reference, received_at=d.received_at,
        notes=d.notes, created_by=d.created_by, created_at=d.created_at)


@router.get("/deposits", response_model=List[DepositOut], summary="الدفعات المقدمة/الودائع")
def list_deposits(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                  patient_id: Optional[int] = Query(None, gt=0),
                  status: Optional[str] = Query(None)):
    q = db.query(PatientDeposit)
    if patient_id:
        q = q.filter(PatientDeposit.patient_id == patient_id)
    if status:
        q = q.filter(PatientDeposit.status == status)
    rows = q.order_by(PatientDeposit.id.desc()).limit(200).all()
    names = {p.id: p.full_name for p in db.query(Patient).filter(
        Patient.id.in_({x.patient_id for x in rows})).all()} if rows else {}
    return [_deposit_out(db, d, names.get(d.patient_id)) for d in rows]


@router.post("/deposits", response_model=DepositOut, status_code=201,
             summary="تسجيل دفعة مقدمة/وديعة لمريض")
def create_deposit(payload: DepositIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    _ensure_chart(db)
    patient = _patient(db, payload.patient_id)
    if payload.invoice_id and not db.query(Invoice).filter(
            Invoice.id == payload.invoice_id).first():
        raise HTTPException(404, "الفاتورة غير موجودة")
    dep = PatientDeposit(
        patient_id=patient.id, invoice_id=payload.invoice_id,
        admission_id=payload.admission_id, amount=_money(payload.amount),
        applied_amount=0, status="active", method=payload.method,
        reference=payload.reference, received_at=datetime.now(), notes=payload.notes,
        created_by=user.username, created_at=datetime.now())
    db.add(dep)
    db.flush()
    # قيد قبض: نقدية/بنك مقابل ذمم مريض
    cash_code = "1000" if payload.method.lower() in ("cash", "نقدي") else "1010"
    entry = _new_entry(db, datetime.now(), f"دفعة مقدمة — {patient.full_name}",
                       "patient_deposit", dep.id,
                       [{"code": cash_code, "debit": _money(payload.amount),
                         "description": "دفعة مقدمة"},
                        {"code": "1100", "credit": _money(payload.amount),
                         "description": f"رصيد مريض {patient.full_name}"}],
                       user.username)
    entry.reference_id = dep.id
    db.commit()
    db.refresh(dep)
    return _deposit_out(db, dep, patient.full_name)


@router.post("/deposits/{deposit_id}/apply", response_model=DepositOut,
             summary="خصم دفعة مقدمة على فاتورة (تحصيل)")
def apply_deposit(deposit_id: int, payload: DepositApplyIn,
                  db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """يخصم من رصيد الوديعة، ويسدّد فاتورة المريض، ويسجّل الدفعة في الدفتر."""
    _ensure_chart(db)
    dep = db.query(PatientDeposit).filter(PatientDeposit.id == deposit_id).first()
    if not dep:
        raise HTTPException(404, "الدفعة غير موجودة")
    if dep.status != "active":
        raise HTTPException(400, "هذه الدفعة مستنفدة أو مرتجعة")
    inv = db.query(Invoice).filter(Invoice.id == payload.invoice_id).first()
    if not inv:
        raise HTTPException(404, "الفاتورة غير موجودة")
    if inv.patient_id != dep.patient_id:
        raise HTTPException(400, "الفاتورة لمريض آخر")
    balance = _money(dep.amount - dep.applied_amount)
    outstanding = _money(inv.total - inv.paid_amount)
    if outstanding <= 0:
        raise HTTPException(400, "الفاتورة مسدّدة بالكامل")
    amount = _money(payload.amount) if payload.amount else balance
    amount = min(amount, balance, outstanding)
    if amount <= 0:
        raise HTTPException(400, "لا يوجد رصيد للخصم")
    dep.applied_amount = _money(dep.applied_amount + amount)
    if dep.applied_amount >= _money(dep.amount) - .01:
        dep.status = "applied"
    inv.paid_amount = _money(inv.paid_amount + amount)
    inv.paid_at = datetime.now()
    inv.payment_method = inv.payment_method or dep.method
    inv.status = (InvoiceStatus.PAID if inv.paid_amount >= _money(inv.total) - .01
                  else InvoiceStatus.PARTIAL)
    dep.invoice_id = dep.invoice_id or inv.id
    db.flush()
    entry = _new_entry(db, datetime.now(), f"سداد فاتورة #{inv.id} من دفعة مقدمة",
                       "patient_invoice_payment", inv.id,
                       [{"code": "1100", "debit": amount, "description": "سداد ذمم"},
                        {"code": "1000", "credit": amount,
                         "description": "إقفال دفعة مقدمة"}], user.username)
    entry.reference_id = inv.id
    db.commit()
    db.refresh(dep)
    return _deposit_out(db, dep)


@router.get("/shifts", response_model=List[ShiftOut], summary="ورديات الكاشير")
def list_shifts(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                username: Optional[str] = Query(None), limit: int = Query(30, ge=1, le=200)):
    q = db.query(CashierShift)
    if username:
        q = q.filter(CashierShift.username == username)
    rows = q.order_by(CashierShift.id.desc()).limit(limit).all()
    return [ShiftOut(**{c.name: getattr(r, c.name) for c in CashierShift.__table__.columns}
                     | {"created_at": r.opened_at}) for r in rows]


@router.get("/shifts/current", response_model=ShiftOut, summary="الوردية المفتوحة الحالية للمستخدم")
def current_shift(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = (db.query(CashierShift)
           .filter(CashierShift.username == user.username, CashierShift.status == "open")
           .order_by(CashierShift.id.desc()).first())
    if not row:
        raise HTTPException(404, "لا توجد وردية مفتوحة — افتح وردية أولًا")
    return ShiftOut(**{c.name: getattr(row, c.name) for c in CashierShift.__table__.columns}
                    | {"created_at": row.opened_at})


@router.post("/shifts/open", response_model=ShiftOut, status_code=201,
             summary="فتح وردية كاشير برصيد افتتاحي")
def open_shift(payload: ShiftOpenIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    if db.query(CashierShift).filter(CashierShift.username == user.username,
                                     CashierShift.status == "open").first():
        raise HTTPException(409, "لديك وردية مفتوحة بالفعل — أغلقها أولًا")
    row = CashierShift(username=user.username, opened_at=datetime.now(),
                       opening_cash=_money(payload.opening_cash), status="open",
                       sales_count=0, collected_total=0, notes=payload.notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return ShiftOut(**{c.name: getattr(row, c.name) for c in CashierShift.__table__.columns}
                    | {"created_at": row.opened_at})


@router.post("/shifts/close", response_model=ShiftOut,
             summary="إغلاق الوردية بمطابقة الصندوق مع المبيعات المسجّلة")
def close_shift(payload: ShiftCloseIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """يقارن النقد المعدّ فعليًا بما سجّله النظام في نقد وردية الكاشير."""
    row = (db.query(CashierShift)
           .filter(CashierShift.username == user.username, CashierShift.status == "open")
           .order_by(CashierShift.id.desc()).first())
    if not row:
        raise HTTPException(404, "لا توجد وردية مفتوحة")
    # نقد محصّل خلال الوردية (فواتير + صرف أدوية) + الودائع النقدية
    since = row.opened_at
    inv_cash = (db.query(func.coalesce(func.sum(Invoice.paid_amount), 0))
                .filter(Invoice.created_at >= since, Invoice.payment_method == "cash").scalar() or 0)
    med_cash = (db.query(func.coalesce(func.sum(Dispense.paid_amount), 0))
                .filter(Dispense.created_at >= since, Dispense.payment_method == "cash",
                        Dispense.returned_at.is_(None)).scalar() or 0)
    dep_cash = (db.query(func.coalesce(func.sum(PatientDeposit.amount), 0))
                .filter(PatientDeposit.received_at >= since,
                        PatientDeposit.method == "cash").scalar() or 0)
    count = (db.query(func.count(Invoice.id))
             .filter(Invoice.created_at >= since).scalar() or 0) + \
            (db.query(func.count(Dispense.id))
             .filter(Dispense.created_at >= since, Dispense.returned_at.is_(None)).scalar() or 0)
    expected = _money(row.opening_cash + inv_cash + med_cash + dep_cash)
    counted = _money(payload.counted_cash)
    diff = _money(counted - expected)
    row.expected_cash, row.counted_cash, row.difference = expected, counted, diff
    row.sales_count = int(count)
    row.collected_total = _money(inv_cash + med_cash)
    row.closed_at = datetime.now()
    row.closed_by = user.username
    row.status = "balanced" if abs(diff) < .01 else "unbalanced"
    row.notes = payload.notes or row.notes
    db.commit()
    db.refresh(row)
    return ShiftOut(**{c.name: getattr(row, c.name) for c in CashierShift.__table__.columns}
                    | {"created_at": row.opened_at})


# ================================================================
# 3) التأمين: الموافقات المسبقة وحزم المطالبات وتسوية الرفوضات
# ================================================================
def _auth_out(db: Session, a: PriorAuthorization, name: Optional[str] = None) -> PriorAuthOut:
    return PriorAuthOut(**{c.name: getattr(a, c.name) for c in PriorAuthorization.__table__.columns}
                        | {"patient_name": name})


@router.get("/prior-authorizations", response_model=List[PriorAuthOut],
            summary="الموافقات المسبقة")
def list_prior_auths(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                     status: Optional[str] = Query(None),
                     insurer: Optional[str] = Query(None),
                     limit: int = Query(100, ge=1, le=300)):
    q = db.query(PriorAuthorization)
    if status:
        q = q.filter(PriorAuthorization.status == status)
    if insurer:
        q = q.filter(PriorAuthorization.insurer == insurer)
    rows = q.order_by(PriorAuthorization.id.desc()).limit(limit).all()
    names = {p.id: p.full_name for p in db.query(Patient).filter(
        Patient.id.in_({x.patient_id for x in rows})).all()} if rows else {}
    return [_auth_out(db, a, names.get(a.patient_id)) for a in rows]


@router.post("/prior-authorizations", response_model=PriorAuthOut, status_code=201,
             summary="تسجيل طلب موافقة مسبقة (مع أكواد ICD-10/CPT)")
def create_prior_auth(payload: PriorAuthIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    patient = _patient(db, payload.patient_id)
    num = (payload.auth_number or "").strip() or _seq_no(db, PriorAuthorization,
                                                        PriorAuthorization.auth_number, "PA")
    if db.query(PriorAuthorization).filter(PriorAuthorization.auth_number == num).first():
        raise HTTPException(409, "رقم الموافقة مستخدم مسبقًا")
    row = PriorAuthorization(
        auth_number=num, patient_id=patient.id,
        insurer=payload.insurer or patient.insurer,
        service_description=payload.service_description,
        icd10_code=payload.icd10_code, cpt_code=payload.cpt_code,
        requested_amount=_money(payload.requested_amount), status="pending",
        requested_at=datetime.now(),
        valid_until=datetime.now() + timedelta(days=payload.valid_days),
        decision_notes=payload.notes, created_by=user.username)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _auth_out(db, row, patient.full_name)


@router.post("/prior-authorizations/{auth_id}/decision", response_model=PriorAuthOut,
             summary="قرار شركة التأمين على الموافقة المسبقة")
def decide_prior_auth(auth_id: int, payload: PriorAuthDecisionIn,
                      db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = db.query(PriorAuthorization).filter(PriorAuthorization.id == auth_id).first()
    if not row:
        raise HTTPException(404, "الموافقة غير موجودة")
    st = payload.status.strip().lower()
    if st not in PRIOR_STATUSES:
        raise HTTPException(400, "القرار يجب أن يكون approved أو partially_approved أو denied")
    if st != "denied" and payload.approved_amount is not None and \
            payload.approved_amount > row.requested_amount + .01:
        raise HTTPException(400, "المبلغ المعتمد يتجاوز المطلوب")
    row.status = st
    row.approved_amount = 0.0 if st == "denied" else (
        _money(payload.approved_amount) if payload.approved_amount is not None else None)
    row.decision_notes = payload.decision_notes
    row.decided_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _auth_out(db, row)


@router.get("/claim-batches", response_model=List[ClaimBatchOut], summary="حزم المطالبات")
def list_claim_batches(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                       insurer: Optional[str] = Query(None)):
    q = db.query(ClaimBatch)
    if insurer:
        q = q.filter(ClaimBatch.insurer == insurer)
    return [_batch_out(x) for x in q.order_by(ClaimBatch.id.desc()).all()]


def _batch_out(b: ClaimBatch) -> ClaimBatchOut:
    """حزمة واحدة ببنودها — تفصل عن القائمة حتى تُعاد مباشرة بعد الإنشاء."""
    lines = []
    for x in b.items:
        claim = x.claim
        lines.append(ClaimBatchItemOut(
            id=x.id, claim_id=x.claim_id,
            claim_number=claim.claim_number if claim else None,
            patient_name=claim.patient.full_name if claim and claim.patient else None,
            amount=_money(x.amount), approved_amount=x.approved_amount,
            claim_status=claim.status.value if claim and claim.status else None))
    return ClaimBatchOut(
        id=b.id, batch_no=b.batch_no, insurer=b.insurer, period_from=b.period_from,
        period_to=b.period_to, status=b.status, total_claims=b.total_claims,
        total_amount=_money(b.total_amount), approved_amount=_money(b.approved_amount),
        submitted_at=b.submitted_at, notes=b.notes, created_by=b.created_by,
        created_at=b.created_at, lines=lines)


@router.post("/claim-batches", response_model=ClaimBatchOut, status_code=201,
             summary="بناء حزمة مطالبات من مطالبات شركة تأمين في فترة")
def build_claim_batch(payload: ClaimBatchBuildIn, db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    """يجمع المطالبات المُرسَلة (SUBMITTED) لتلك الشركة في الفترة ويجموع مبالغها."""
    if payload.period_to < payload.period_from:
        raise HTTPException(400, "نهاية الفترة قبل بدايتها")
    claims = (db.query(InsuranceClaim)
              .filter(InsuranceClaim.insurer == payload.insurer,
                      InsuranceClaim.submitted_at >= payload.period_from,
                      InsuranceClaim.submitted_at <= payload.period_to)
              .order_by(InsuranceClaim.id).all())
    claims = [c for c in claims if c.status in (ClaimStatus.SUBMITTED, ClaimStatus.APPROVED)]
    if not claims:
        raise HTTPException(400, "لا توجد مطالبات مُرسَلة لهذه الشركة في الفترة")
    already = {x.claim_id for x in db.query(ClaimBatchItem).all()}
    fresh = [c for c in claims if c.id not in already]
    if not fresh:
        raise HTTPException(409, "كل مطالبات هذه الفترة مرتبطة بحزم سابقة")
    batch = ClaimBatch(
        batch_no=_seq_no(db, ClaimBatch, ClaimBatch.batch_no, "CLM"),
        insurer=payload.insurer, period_from=payload.period_from,
        period_to=payload.period_to, status="draft", total_claims=len(fresh),
        total_amount=0, approved_amount=0, notes=payload.notes,
        created_by=user.username)
    db.add(batch)
    db.flush()
    total = approved = 0.0
    for c in fresh:
        amount = _money(c.amount)
        db.add(ClaimBatchItem(batch_id=batch.id, claim_id=c.id, amount=amount,
                              approved_amount=c.approved_amount))
        total += amount
        approved += _money(c.approved_amount or 0)
    batch.total_amount, batch.approved_amount = _money(total), _money(approved)
    db.commit()
    db.refresh(batch)
    return _batch_out(batch)


@router.post("/claim-batches/{batch_id}/submit", response_model=ClaimBatchOut,
             summary="إرسال حزمة المطالبات لشركة التأمين")
def submit_claim_batch(batch_id: int, payload: ClaimBatchSubmitIn,
                       db: Session = Depends(get_db), user: User = Depends(require_admin)):
    batch = db.query(ClaimBatch).filter(ClaimBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(404, "الحزمة غير موجودة")
    if batch.status != "draft":
        raise HTTPException(400, "الحزمة مُرسَلة أو مُسوّاة مسبقًا")
    batch.status, batch.submitted_at = "submitted", datetime.now()
    batch.notes = payload.notes or batch.notes
    db.commit()
    db.refresh(batch)
    return _batch_out(batch)


@router.get("/denials", response_model=List[dict],
            summary="المطالبات والموافقات المرفوضة قابلة لإعادة الإرسال")
def list_denials(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """تجمع المرفوض من المطالبات والموافقات المسبقة في قائمة واحدة لتسويتها."""
    out = []
    for c in db.query(InsuranceClaim).filter(InsuranceClaim.status == ClaimStatus.REJECTED).all():
        out.append({"kind": "claim", "id": c.id, "reference": c.claim_number,
                    "insurer": c.insurer, "amount": _money(c.amount),
                    "reason": c.rejection_reason, "patient_id": c.patient_id,
                    "date": c.decided_at or c.submitted_at})
    for a in db.query(PriorAuthorization).filter(
            PriorAuthorization.status == "denied").all():
        out.append({"kind": "prior_auth", "id": a.id, "reference": a.auth_number,
                    "insurer": a.insurer, "amount": _money(a.requested_amount),
                    "reason": a.decision_notes, "patient_id": a.patient_id,
                    "date": a.decided_at})
    return sorted(out, key=lambda x: (x["date"] or datetime.min), reverse=True)


@router.post("/denials/claims/{claim_id}/transfer", response_model=dict,
             summary="تحميل المطالبة المرفوضة على حساب المريض")
def transfer_denied_claim(claim_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_admin)):
    """ينقل قيمة المرفوض إلى ذمم المريض: فاتورة ذممة + قيد بسداد من شركة التأمين."""
    _ensure_chart(db)
    claim = db.query(InsuranceClaim).filter(InsuranceClaim.id == claim_id).first()
    if not claim:
        raise HTTPException(404, "المطالبة غير موجودة")
    if claim.status != ClaimStatus.REJECTED:
        raise HTTPException(400, "المطالبة غير مرفوضة")
    if not claim.invoice_id:
        raise HTTPException(400, "المطالبة بلا فاتورة مرتبطة")
    inv = db.query(Invoice).filter(Invoice.id == claim.invoice_id).first()
    if not inv:
        raise HTTPException(404, "الفاتورة غير موجودة")
    outstanding = _money(inv.total - inv.paid_amount)
    if outstanding > .01:
        # المبلغ المرفوض يبقى على المريض: نغيّر الحالة فقط بلا حركة إضافية
        claim.decision_notes = ((claim.decision_notes or "") +
                                " — حُمِّلت على حساب المريض").strip()
    else:
        inv.paid_amount = _money(inv.total)
        inv.status = InvoiceStatus.PAID
        inv.paid_at = datetime.now()
        entry = _new_entry(db, datetime.now(), f"تحميل مطالبة مرفوضة #{claim.id} على المريض",
                           "patient_invoice_payment", inv.id,
                           [{"code": "1100", "debit": _money(inv.total),
                             "description": "ذمم على مريض (مطالبة مرفوضة)"},
                            {"code": "1110", "credit": _money(inv.total),
                             "description": "إيراد مُخصم من شركة التأمين"}], user.username)
        entry.reference_id = inv.id
    db.commit()
    return {"claim_id": claim.id, "invoice_id": inv.id, "status": inv.status.value,
            "outstanding": _money(inv.total - inv.paid_amount)}


# ================================================================
# 1) إشعارات الدائن والاسترداد
# ================================================================
def _note_out(db: Session, n: CreditNote, name: Optional[str] = None) -> CreditNoteOut:
    return CreditNoteOut(**{c.name: getattr(n, c.name) for c in CreditNote.__table__.columns}
                         | {"patient_name": name})


@router.get("/credit-notes", response_model=List[CreditNoteOut], summary="إشعارات الدائن")
def list_credit_notes(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                      limit: int = Query(100, ge=1, le=300)):
    rows = db.query(CreditNote).order_by(CreditNote.id.desc()).limit(limit).all()
    names = {p.id: p.full_name for p in db.query(Patient).filter(
        Patient.id.in_({x.patient_id for x in rows})).all()} if rows else {}
    return [_note_out(db, n, names.get(n.patient_id)) for n in rows]


@router.post("/credit-notes", response_model=CreditNoteOut, status_code=201,
             summary="إصدار إشعار دائن/استرداد مالي (محدود بما مدفوع)")
def create_credit_note(payload: CreditNoteIn, db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    """لا يُستردّ إلا ما دُفع فعلًا، ويُخصم من رصيد الفاتورة/الصرف قبل الصرف."""
    _ensure_chart(db)
    patient = _patient(db, payload.patient_id)
    amount = _money(payload.amount)
    if payload.invoice_id:
        inv = db.query(Invoice).filter(Invoice.id == payload.invoice_id).first()
        if not inv:
            raise HTTPException(404, "الفاتورة غير موجودة")
        if inv.patient_id != patient.id:
            raise HTTPException(400, "الفاتورة لمريض آخر")
        if amount > _money(inv.paid_amount) + .01:
            raise HTTPException(400, f"المبلغ المسترد ({amount}) يتجاوز المدفوع "
                                     f"({_money(inv.paid_amount)})")
        inv.paid_amount = _money(max(0.0, inv.paid_amount - amount))
        inv.paid_at = None if inv.paid_amount <= 0 else inv.paid_at
        inv.status = (InvoiceStatus.UNPAID if inv.paid_amount <= .01
                      else InvoiceStatus.PARTIAL)
    elif payload.dispense_id:
        dsp = db.query(Dispense).filter(Dispense.id == payload.dispense_id).first()
        if not dsp:
            raise HTTPException(404, "عملية البيع غير موجودة")
        if dsp.patient_id != patient.id:
            raise HTTPException(400, "عملية البيع لمريض آخر")
        if dsp.returned_at:
            raise HTTPException(400, "هذه العملية مرتجعة مسبقًا")
        if amount > _money(dsp.paid_amount) + .01:
            raise HTTPException(400, f"المبلغ المسترد ({amount}) يتجاوز المدفوع "
                                     f"({_money(dsp.paid_amount)})")
        dsp.paid_amount = _money(max(0.0, dsp.paid_amount - amount))
        dsp.status = "UNPAID" if dsp.paid_amount <= .01 else "PARTIAL"
    else:
        raise HTTPException(400, "حدّد الفاتورة أو عملية البيع المراد استردادها")
    note = CreditNote(
        note_no=_seq_no(db, CreditNote, CreditNote.note_no, "CN"),
        patient_id=patient.id, invoice_id=payload.invoice_id,
        dispense_id=payload.dispense_id, amount=amount, method=payload.method,
        reason=payload.reason, status="refunded" if payload.refund_now else "issued",
        refunded_at=datetime.now() if payload.refund_now else None,
        created_by=user.username, created_at=datetime.now())
    db.add(note)
    db.flush()
    if payload.refund_now:
        # الاسترداد: نقد/بنك من contra ذمم → ردّ قيمة محصّلة
        cash_code = "1000" if payload.method.lower() in ("cash", "نقدي") else "1010"
        _new_entry(db, datetime.now(), f"إشعار دائن {note.note_no} — {patient.full_name}",
                   "credit_note", note.id,
                   [{"code": "1100", "debit": amount, "description": "ردّ مبلغ محصّل"},
                    {"code": cash_code, "credit": amount, "description": "صرف استرداد"}],
                   user.username).reference_id = note.id
    db.commit()
    db.refresh(note)
    return _note_out(db, note, patient.full_name)


# ================================================================
# 6) تقارير المبيعات والإيرادات
# ================================================================
@router.get("/reports/sales", response_model=SalesReportOut,
            summary="تقرير مبيعات مفصّل: طريقة الدفع والطبيب والحالة والتأمين")
def sales_report(db: Session = Depends(get_db), _: User = Depends(get_current_user),
                 from_date: Optional[datetime] = Query(None),
                 to_date: Optional[datetime] = Query(None),
                 doctor_id: Optional[int] = Query(None, gt=0)):
    """يجمع فواتير الخدمات وصرف الصيدلية في تقرير واحد قابل للتصفية."""
    f0 = from_date
    t0 = to_date

    def _inv_query():
        q = db.query(Invoice)
        if f0:
            q = q.filter(Invoice.created_at >= f0)
        if t0:
            q = q.filter(Invoice.created_at <= t0)
        return q

    def _med_query():
        q = db.query(Dispense).filter(Dispense.returned_at.is_(None))
        if f0:
            q = q.filter(Dispense.created_at >= f0)
        if t0:
            q = q.filter(Dispense.created_at <= t0)
        return q

    inv_total = _money(sum(_money(i.amount - (i.discount or 0) + i.tax)
                           for i in _inv_query().all()))
    med_total = _money(sum(_money(d.total_price) for d in _med_query().all()))

    by_payment: dict = {}
    for i in _inv_query().all():
        key = (i.payment_method or "unspecified")
        row = by_payment.setdefault(key, {"count": 0, "total": 0.0, "paid": 0.0})
        total = _money(i.total)
        row["count"] += 1
        row["total"] += total
        row["paid"] += _money(i.paid_amount)
    for d in _med_query().all():
        key = (d.payment_method or "unspecified")
        row = by_payment.setdefault(key, {"count": 0, "total": 0.0, "paid": 0.0})
        row["count"] += 1
        row["total"] += _money(d.total_price)
        row["paid"] += _money(d.paid_amount)
    labels = {"cash": "نقدًا", "card": "بطاقة", "bank": "بنك",
              "insurance": "تأمين", "unspecified": "غير محدد"}
    payment_rows = [SalesReportRow(key=k, label=labels.get(k, k), count=v["count"],
                                   total=_money(v["total"]), paid=_money(v["paid"]),
                                   outstanding=_money(v["total"] - v["paid"]))
                    for k, v in sorted(by_payment.items(),
                                       key=lambda x: -x[1]["total"])]

    status_map = {InvoiceStatus.UNPAID: "غير مدفوعة", InvoiceStatus.PAID: "مدفوعة",
                  InvoiceStatus.PARTIAL: "جزئية"}
    by_status: dict = {}
    for i in _inv_query().all():
        key = i.status.value if i.status else "unpaid"
        row = by_status.setdefault(key, {"count": 0, "total": 0.0, "paid": 0.0})
        row["count"] += 1
        row["total"] += _money(i.total)
        row["paid"] += _money(i.paid_amount)
    for d in _med_query().all():
        key = (d.status or "UNPAID").lower()
        row = by_status.setdefault(key, {"count": 0, "total": 0.0, "paid": 0.0})
        row["count"] += 1
        row["total"] += _money(d.total_price)
        row["paid"] += _money(d.paid_amount)
    status_rows = [SalesReportRow(key=k, label=status_map.get(k, k), count=v["count"],
                                  total=_money(v["total"]), paid=_money(v["paid"]),
                                  outstanding=_money(v["total"] - v["paid"]))
                   for k, v in sorted(by_status.items(), key=lambda x: -x[1]["total"])]

    by_insurer: dict = {}
    for i in _inv_query().filter(Invoice.insurer.isnot(None)).all():
        row = by_insurer.setdefault(i.insurer, {"count": 0, "total": 0.0, "paid": 0.0})
        row["count"] += 1
        row["total"] += _money(i.total)
        row["paid"] += _money(i.paid_amount)
    insurer_rows = [SalesReportRow(key=k, label=k, count=v["count"], total=_money(v["total"]),
                                   paid=_money(v["paid"]),
                                   outstanding=_money(v["total"] - v["paid"]))
                    for k, v in sorted(by_insurer.items(), key=lambda x: -x[1]["total"])]

    # إيرادات الأطباء: الفاتورة المرتبطة بموعد ⇒ الطبيب المسؤول عنها
    by_doctor: dict = {}
    appt_invoices = [i for i in _inv_query().all() if i.appointment_id]
    if appt_invoices:
        from app.models import Appointment, Doctor
        doc_of = {a.id: a.doctor_id for a in db.query(Appointment).filter(
            Appointment.id.in_({i.appointment_id for i in appt_invoices})).all()}
        for inv in appt_invoices:
            docid = doc_of.get(inv.appointment_id)
            if not docid or (doctor_id and docid != doctor_id):
                continue
            row = by_doctor.setdefault(str(docid), {"count": 0, "total": 0.0, "paid": 0.0})
            row["count"] += 1
            row["total"] += _money(inv.total)
            row["paid"] += _money(inv.paid_amount)
    from app.models import Doctor
    doc_names = {d.id: d.full_name for d in db.query(Doctor).all()}
    doctor_rows = [SalesReportRow(key=k, label=doc_names.get(int(k), f"طبيب {k}"),
                                  count=v["count"], total=_money(v["total"]),
                                  paid=_money(v["paid"]),
                                  outstanding=_money(v["total"] - v["paid"]))
                   for k, v in sorted(by_doctor.items(), key=lambda x: -x[1]["total"])]

    return SalesReportOut(
        period_from=f0, period_to=t0, invoices_total=inv_total,
        pharmacy_total=med_total, grand_total=_money(inv_total + med_total),
        by_payment=payment_rows, by_doctor=doctor_rows, by_status=status_rows,
        by_insurer=insurer_rows)
