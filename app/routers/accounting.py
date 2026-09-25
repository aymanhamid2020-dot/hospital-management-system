"""المحاسبة المؤسسية: دليل حسابات، قيود مزدوجة، ذمم، وميزان مراجعة."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Account, Invoice, InvoiceLedgerPayment, InvoiceStatus, JournalEntry,
    JournalLine, Vendor, VendorBill, VendorPayment,
)
from app.schemas import (
    AgingBucket, InvoiceLedgerPaymentCreate, JournalEntryCreate, JournalEntryOut,
    JournalLineOut, LedgerAccountCreate, LedgerAccountOut, LedgerSummary,
    VendorBillCreate, VendorBillOut, VendorCreate, VendorOut, VendorPaymentCreate,
)

router = APIRouter(prefix="/accounts/ledger", tags=["General Ledger"])
DEFAULT_ACCOUNTS = (
    ("1000", "الصندوق النقدي", "asset", None),
    ("1010", "البنك", "asset", "1000"),
    ("1100", "ذمم المرضى", "asset", "1000"),
    ("1110", "ذمم شركات التأمين", "asset", "1000"),
    ("1200", "المخزون", "asset", "1000"),
    ("2000", "ذمم الموردين", "liability", None),
    ("3000", "حقوق الملكية", "equity", None),
    ("4000", "إيرادات الخدمات", "revenue", None),
    ("5000", "المصروفات التشغيلية", "expense", None),
    ("5100", "المستلزمات الطبية", "expense", "5000"),
    ("2100", "مستحقات رواتب الموظفين", "liability", None),
    ("2110", "سلف الموظفين", "liability", None),
    ("2120", "مستحقات نهاية الخدمة", "liability", None),
)


def _money(value) -> float:
    return round(float(value or 0), 2)


def _ensure_chart(db: Session) -> None:
    missing = [Account(code=c, name=n, account_type=t, parent_code=p)
               for c, n, t, p in DEFAULT_ACCOUNTS
               if not db.query(Account).filter(Account.code == c).first()]
    if missing:
        db.add_all(missing)
        db.flush()


def _account(db: Session, code: str) -> Account:
    row = db.query(Account).filter(Account.code == code).first()
    if not row or not row.is_active:
        raise HTTPException(400, f"الحساب المحاسبي غير موجود أو غير نشط: {code}")
    return row


def _new_entry(db: Session, date: datetime, description: str,
               ref_type: str, ref_id: int, lines: List[dict], username: str) -> JournalEntry:
    total_debit = sum(_money(x.get("debit")) for x in lines)
    total_credit = sum(_money(x.get("credit")) for x in lines)
    if len(lines) < 2 or total_debit <= 0 or total_credit <= 0 or abs(total_debit-total_credit) > .01:
        raise HTTPException(400, "القيد يحتاج سطرين على الأقل ويجب أن يكون متوازنًا")
    if any(_money(x.get("debit")) and _money(x.get("credit")) for x in lines):
        raise HTTPException(400, "السطر لا يكون مدينًا ودائنًا معًا")
    row = JournalEntry(
        entry_no=f"JE-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        entry_date=date, description=description, reference_type=ref_type,
        reference_id=ref_id, is_posted=True, created_by=username,
    )
    db.add(row)
    db.flush()
    for line in lines:
        account = _account(db, line["code"])
        db.add(JournalLine(
            entry_id=row.id, account_id=account.id,
            debit=_money(line.get("debit")), credit=_money(line.get("credit")),
            description=line.get("description"),
        ))
    db.flush()
    return row


def _entry_out(row: JournalEntry) -> JournalEntryOut:
    return JournalEntryOut(
        id=row.id, entry_no=row.entry_no, entry_date=row.entry_date,
        description=row.description, reference_type=row.reference_type,
        reference_id=row.reference_id, is_posted=row.is_posted,
        created_by=row.created_by, created_at=row.created_at,
        lines=[JournalLineOut(
            id=x.id, account_id=x.account_id, account_code=x.account.code,
            account_name=x.account.name, debit=_money(x.debit),
            credit=_money(x.credit), description=x.description,
        ) for x in row.lines],
    )


@router.get("/accounts", response_model=List[LedgerAccountOut], summary="دليل الحسابات")
def list_accounts(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _ensure_chart(db); db.commit()
    return db.query(Account).order_by(Account.code).all()


@router.post("/accounts", response_model=LedgerAccountOut, status_code=201, summary="إضافة حساب")
def create_account(payload: LedgerAccountCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    duplicate = db.query(Account).filter((Account.code == payload.code) | (Account.name == payload.name)).first()
    if duplicate:
        raise HTTPException(409, "كود الحساب أو اسمه مستخدم مسبقًا")
    if payload.parent_code and not db.query(Account).filter(Account.code == payload.parent_code).first():
        raise HTTPException(400, "الحساب الأب غير موجود")
    row = Account(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.get("/entries", response_model=List[JournalEntryOut], summary="القيود اليومية")
def list_entries(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [_entry_out(x) for x in db.query(JournalEntry).order_by(
        JournalEntry.entry_date.desc(), JournalEntry.id.desc()).limit(limit).all()]


@router.post("/entries", response_model=JournalEntryOut, status_code=201, summary="ترحيل قيد يدوي")
def create_entry(payload: JournalEntryCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    _ensure_chart(db)
    row = _new_entry(db, payload.entry_date, payload.description,
                     payload.reference_type or "manual", payload.reference_id or 0,
                     [{"code": x.account_code, "debit": x.debit, "credit": x.credit,
                       "description": x.description} for x in payload.lines], user.username)
    db.commit(); db.refresh(row)
    return _entry_out(row)


@router.post("/invoices/{invoice_id}/post", response_model=JournalEntryOut, summary="ترحيل فاتورة مريض")
def post_invoice(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    _ensure_chart(db)
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "الفاتورة غير موجودة")
    existing = db.query(JournalEntry).filter(
        JournalEntry.reference_type == "patient_invoice",
        JournalEntry.reference_id == invoice_id,
        JournalEntry.is_posted.is_(True),
    ).first()
    if existing:
        raise HTTPException(409, "تم ترحيل الفاتورة محاسبيًا مسبقًا")
    amount = _money(invoice.total)
    if amount <= 0:
        raise HTTPException(400, "لا يمكن ترحيل فاتورة بقيمة صفر")
    debit_code = "1110" if invoice.insurer else "1100"
    row = _new_entry(
        db, invoice.created_at or datetime.now(), invoice.description or f"فاتورة مريض #{invoice.id}",
        "patient_invoice", invoice.id,
        [{"code": debit_code, "debit": amount, "description": "ذمم من فاتورة مريض"},
         {"code": "4000", "credit": amount, "description": "إيراد خدمات"}], user.username,
    )
    db.commit(); db.refresh(row)
    return _entry_out(row)


@router.post("/invoices/{invoice_id}/payments", status_code=201, summary="ترحيل دفعة فاتورة مريض")
def post_invoice_payment(
    invoice_id: int, payload: InvoiceLedgerPaymentCreate,
    db: Session = Depends(get_db), user=Depends(require_admin),
):
    _ensure_chart(db)
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "الفاتورة غير موجودة")
    # لا يُسمح بالتحصيل قبل أن تكون الفاتورة قد رُحّلت إلى الدفتر.
    if not db.query(JournalEntry).filter(
        JournalEntry.reference_type == "patient_invoice",
        JournalEntry.reference_id == invoice_id,
        JournalEntry.is_posted.is_(True),
    ).first():
        raise HTTPException(409, "يجب ترحيل الفاتورة محاسبيًا قبل تسجيل التحصيل")
    amount = _money(payload.amount)
    outstanding = _money(invoice.total) - _money(invoice.paid_amount)
    if amount <= 0 or amount > outstanding + .01:
        raise HTTPException(400, "مبلغ الدفعة يجب أن يكون موجبًا ولا يتجاوز رصيد الفاتورة")
    if payload.reference:
        old = db.query(InvoiceLedgerPayment).filter(
            InvoiceLedgerPayment.invoice_id == invoice_id,
            InvoiceLedgerPayment.reference == payload.reference,
        ).first()
        if old:
            raise HTTPException(409, "مرجع الدفعة مستخدم مسبقًا")
    cash_code = "1000" if payload.method.lower() in ("cash", "نقدي") else "1010"
    receivable_code = "1110" if payload.method.lower() == "insurance" or invoice.insurer else "1100"
    entry = _new_entry(
        db, payload.paid_at, f"تحصيل فاتورة مريض #{invoice_id}",
        "patient_invoice_payment", invoice_id,
        [{"code": cash_code, "debit": amount, "description": "تحصيل نقدية/بنكي"},
         {"code": receivable_code, "credit": amount, "description": "سداد ذمم مريض"}], user.username,
    )
    payment = InvoiceLedgerPayment(
        invoice_id=invoice_id, amount=amount, method=payload.method,
        paid_at=payload.paid_at, reference=payload.reference,
        journal_entry_id=entry.id, created_by=user.username,
    )
    invoice.paid_amount = _money((invoice.paid_amount or 0) + amount)
    invoice.paid_at = payload.paid_at
    invoice.payment_method = payload.method
    invoice.status = InvoiceStatus.PAID if invoice.paid_amount >= _money(invoice.total) else InvoiceStatus.PARTIAL
    db.add(payment); db.commit(); db.refresh(payment)
    return {
        "id": payment.id, "invoice_id": invoice_id, "amount": amount,
        "method": payment.method, "paid_at": payment.paid_at,
        "reference": payment.reference, "journal_entry_id": entry.id,
        "invoice_status": invoice.status.value,
    }




@router.get("/vendors", response_model=List[VendorOut], summary="الموردون")
def list_vendors(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Vendor).order_by(Vendor.name).all()


@router.post("/vendors", response_model=VendorOut, status_code=201, summary="إضافة مورد")
def create_vendor(payload: VendorCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    if db.query(Vendor).filter((Vendor.code == payload.code) | (Vendor.name == payload.name)).first():
        raise HTTPException(409, "كود المورد أو اسمه مستخدم مسبقًا")
    _ensure_chart(db)
    row = Vendor(**{**payload.model_dump(), "opening_balance": _money(payload.opening_balance)})
    db.add(row); db.flush()
    if row.opening_balance > 0:
        _account(db, "5100")
        _new_entry(
            db, datetime.now(), f"رصيد افتتاحي للمورد {row.name}", "vendor_opening", row.id,
            [{"code": "5100", "debit": row.opening_balance},
             {"code": "2000", "credit": row.opening_balance}], user.username,
        )
    db.commit(); db.refresh(row)
    return row


def _bill_out(row: VendorBill) -> VendorBillOut:
    return VendorBillOut(
        id=row.id, bill_no=row.bill_no, vendor_id=row.vendor_id, vendor_name=row.vendor.name,
        bill_date=row.bill_date, due_date=row.due_date, amount=_money(row.amount),
        paid_amount=_money(row.paid_amount), outstanding=_money(row.amount-row.paid_amount),
        status=row.status, expense_account_code=row.expense_account_code,
        journal_entry_id=row.journal_entry_id, created_at=row.created_at,
    )


@router.get("/vendor-bills", response_model=List[VendorBillOut], summary="فواتير الموردين")
def list_vendor_bills(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [_bill_out(x) for x in db.query(VendorBill).order_by(VendorBill.bill_date.desc(), VendorBill.id.desc()).all()]


@router.post("/vendor-bills", response_model=VendorBillOut, status_code=201, summary="تسجيل فاتورة مورد")
def create_vendor_bill(payload: VendorBillCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    _ensure_chart(db)
    vendor = db.query(Vendor).filter(Vendor.id == payload.vendor_id, Vendor.is_active.is_(True)).first()
    if not vendor:
        raise HTTPException(404, "المورد غير موجود أو غير نشط")
    if db.query(VendorBill).filter(VendorBill.bill_no == payload.bill_no).first():
        raise HTTPException(409, "رقم فاتورة المورد مستخدم مسبقًا")
    expense = _account(db, payload.expense_account_code)
    if expense.account_type != "expense":
        raise HTTPException(400, "حساب المصروف المحدد ليس حساب مصروف")
    amount = _money(payload.amount)
    entry = _new_entry(
        db, payload.bill_date, f"فاتورة مورد {payload.bill_no}", "vendor_bill", 0,
        [{"code": expense.code, "debit": amount}, {"code": "2000", "credit": amount}], user.username,
    )
    row = VendorBill(
        bill_no=payload.bill_no, vendor_id=vendor.id, bill_date=payload.bill_date,
        due_date=payload.due_date, amount=amount, paid_amount=0, status="unpaid",
        expense_account_code=expense.code, journal_entry_id=entry.id, created_by=user.username,
    )
    db.add(row); db.flush(); entry.reference_id = row.id
    db.commit(); db.refresh(row)
    return _bill_out(row)


@router.post("/vendor-bills/{bill_id}/payments", status_code=201, summary="ترحيل دفعة إلى مورد")
def post_vendor_bill_payment(
    bill_id: int, payload: VendorPaymentCreate,
    db: Session = Depends(get_db), user=Depends(require_admin),
):
    _ensure_chart(db)
    bill = db.query(VendorBill).filter(VendorBill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, "فاتورة المورد غير موجودة")
    amount = _money(payload.amount)
    outstanding = _money(bill.amount - bill.paid_amount)
    if amount <= 0 or amount > outstanding + .01:
        raise HTTPException(400, "مبلغ الدفعة يجب أن يكون موجبًا ولا يتجاوز رصيد فاتورة المورد")
    if payload.reference and db.query(VendorPayment).filter(
        VendorPayment.bill_id == bill_id,
        VendorPayment.reference == payload.reference,
    ).first():
        raise HTTPException(409, "مرجع الدفعة مستخدم مسبقًا")
    credit_code = "1000" if payload.method.lower() in ("cash", "نقدي") else "1010"
    entry = _new_entry(
        db, payload.paid_at, f"دفع فاتورة مورد {bill.bill_no}",
        "vendor_bill_payment", bill.id,
        [{"code": "2000", "debit": amount},
         {"code": credit_code, "credit": amount}], user.username,
    )
    payment = VendorPayment(
        bill_id=bill.id, amount=amount, paid_at=payload.paid_at,
        method=payload.method, reference=payload.reference,
        journal_entry_id=entry.id, created_by=user.username,
    )
    bill.paid_amount = _money((bill.paid_amount or 0) + amount)
    bill.status = "paid" if bill.paid_amount >= _money(bill.amount) else "partial"
    db.add(payment); db.commit(); db.refresh(payment)
    return {
        "id": payment.id, "bill_id": bill.id, "amount": amount,
        "method": payment.method, "paid_at": payment.paid_at,
        "reference": payment.reference, "journal_entry_id": entry.id,
        "bill_status": bill.status,
    }


def _age_bucket(days: int) -> str:
    if days <= 0:
        return "current"
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def _aging(rows, date_field, outstanding_getter, as_of: datetime) -> List[AgingBucket]:
    buckets = {x: AgingBucket(bucket=x, count=0, total=0, outstanding=0)
               for x in ("current", "1-30", "31-60", "61-90", "90+")}
    for row in rows:
        due = getattr(row, date_field) or getattr(row, "created_at")
        days = max(0, (as_of.date() - due.date()).days)
        key = _age_bucket(days)
        amount = _money(outstanding_getter(row))
        if amount <= 0:
            continue
        buckets[key].count += 1
        buckets[key].outstanding = _money(buckets[key].outstanding + amount)
        if date_field == "due_date":
            buckets[key].total = _money(buckets[key].total + amount)
        else:
            buckets[key].total = _money(buckets[key].total + _money(row.total))
    return list(buckets.values())


@router.get("/aging", response_model=LedgerSummary, summary="أعمار ذمم المرضى والموردين")
def ledger_aging(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _summary(db)


@router.get("/trial-balance", summary="ميزان المراجعة")
def trial_balance(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = []
    for account in db.query(Account).order_by(Account.code).all():
        debit = _money(sum(x.debit for x in account.lines))
        credit = _money(sum(x.credit for x in account.lines))
        if debit or credit:
            rows.append({
                "code": account.code, "name": account.name,
                "account_type": account.account_type,
                "debit": debit, "credit": credit, "balance": _money(debit-credit),
            })
    total_debit = _money(sum(x["debit"] for x in rows))
    total_credit = _money(sum(x["credit"] for x in rows))
    return {"rows": rows, "total_debit": total_debit, "total_credit": total_credit,
            "difference": _money(total_debit-total_credit)}


def _summary(db: Session) -> LedgerSummary:
    _ensure_chart(db); db.commit()
    now = datetime.now()
    rows = trial_balance(db, _=None)
    def total(*codes):
        return _money(sum(x["balance"] for x in rows["rows"] if x["code"] in codes))
    revenue = _money(-total("4000"))
    expenses = _money(sum(x["balance"] for x in rows["rows"] if x["account_type"] == "expense"))
    invoices = db.query(Invoice).filter(Invoice.status != InvoiceStatus.PAID).all()
    bills = db.query(VendorBill).filter(VendorBill.status != "paid").all()
    return LedgerSummary(
        as_of=now,
        cash=total("1000", "1010"),
        accounts_receivable=total("1100", "1110"),
        inventory=total("1200"),
        accounts_payable=_money(-total("2000")),
        revenue=revenue, expenses=expenses,
        net_income=_money(revenue-expenses),
        trial_balance_difference=rows["difference"],
        debtors=_aging(invoices, "created_at", lambda x: x.total-(x.paid_amount or 0), now),
        creditors=_aging(bills, "due_date", lambda x: x.amount-(x.paid_amount or 0), now),
    )


@router.get("/summary", response_model=LedgerSummary, summary="الملخص المالي وميزان المراجعة")
def ledger_summary(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _summary(db)

