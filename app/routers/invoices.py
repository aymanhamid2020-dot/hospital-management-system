from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import (
    Invoice, InvoiceLine, Patient, User, Appointment, MedicalRecord, InvoiceStatus,
)
from app.schemas import (
    InvoiceCreate, InvoiceUpdate, InvoiceInDB, InvoicePayment,
    InvoiceLineBase, InvoiceLineInDB,
)
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/invoices", tags=["Invoices"])

PAYMENT_METHODS = {"cash", "card", "insurance"}


def _validate_totals(invoice) -> None:
    """الخصم لا يتجاوز المبلغ الأساسي."""
    if (invoice.discount or 0) > (invoice.amount or 0) + 1e-9:
        raise HTTPException(status_code=400, detail="الخصم يتجاوز المبلغ الأساسي")


def _sync_paid_for_status(inv) -> None:
    """مزامنة المدفوع والحالة بعد تعديل يدوي للحالة."""
    if inv.status == InvoiceStatus.PAID:
        inv.paid_amount = inv.total
        if not inv.paid_at:
            inv.paid_at = datetime.now()
    elif inv.status == InvoiceStatus.UNPAID:
        inv.paid_amount = 0
        inv.paid_at = None
    # PARTIAL: لا نمسّ ما هو مدفوع فعلًا


def _validate_links(db: Session, patient_id: int, appointment_id, record_id):
    """التحقق من أن الموعد/السجل موجودين وينتميان لنفس المريض."""
    if appointment_id is not None:
        appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appt:
            raise HTTPException(status_code=404, detail="الموعد غير موجود")
        if appt.patient_id != patient_id:
            raise HTTPException(status_code=400, detail="الموعد لا ينتمي لهذا المريض")
    if record_id is not None:
        rec = db.query(MedicalRecord).filter(MedicalRecord.id == record_id).first()
        if not rec:
            raise HTTPException(status_code=404, detail="السجل الطبي غير موجود")
        if rec.patient_id != patient_id:
            raise HTTPException(status_code=400, detail="السجل الطبي لا ينتمي لهذا المريض")


def _attach_lines(db: Session, inv: Invoice, lines) -> None:
    """يضيف بنود الفاتورة ويضبط المبلغ = مجموعها (إن وُجدت بنود)."""
    if not lines:
        return
    total = 0.0
    for line in lines:
        inv.lines.append(InvoiceLine(
            kind=line.kind, description=line.description,
            quantity=line.quantity, unit_price=line.unit_price,
            amount=line.amount, ref_type=line.ref_type, ref_id=line.ref_id,
        ))
        total += line.amount or 0
    inv.amount = round(total, 2)


def _refresh_total(inv: Invoice) -> None:
    """يعيد حساب المبلغ من السطور بعد إضافة/حذف سطر."""
    if inv.lines:
        inv.amount = round(sum(float(x.amount or 0) for x in inv.lines), 2)
    _validate_totals(inv)


def _locked_invoice(db: Session, invoice_id: int) -> Invoice:
    """فاتورة لا يجوز تعديل بنودها بعد سدادها (الإيصال نهائي)."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة")
    if inv.status == InvoiceStatus.PAID or (inv.paid_amount or 0) > 0:
        raise HTTPException(status_code=409, detail="لا يمكن تعديل بنود فاتورة مدفوعة")
    return inv


@router.get("/", response_model=List[InvoiceInDB], summary="عرض قائمة الفواتير")
async def list_invoices(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    status_filter: Optional[str] = Query(None, alias="status", description="paid/unpaid/partial"),
    appointment_id: Optional[int] = Query(None, description="فلترة حسب الموعد"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """جلب الفواتير مع فلاتر اختيارية"""
    q = db.query(Invoice)
    if patient_id is not None:
        q = q.filter(Invoice.patient_id == patient_id)
    if status_filter:
        q = q.filter(Invoice.status == status_filter)
    if appointment_id is not None:
        q = q.filter(Invoice.appointment_id == appointment_id)
    return q.order_by(Invoice.created_at.desc()).all()


@router.get("/export.csv", summary="تصدير الفواتير إلى CSV (Excel)")
async def export_invoices_csv(
    status_filter: Optional[str] = Query(None, alias="status", description="فلترة: paid/unpaid/partial"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """تصدير الفواتير إلى CSV (UTF-8 + BOM) — يشمل الدفع والتأمين والروابط"""
    import csv as _csv
    import io as _io
    from fastapi.responses import Response

    q = db.query(Invoice)
    if status_filter:
        q = q.filter(Invoice.status == status_filter)

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow([
        "#", "التاريخ", "المريض", "الوصف", "المبلغ", "الخصم", "الضريبة %",
        "الإجمالي", "المدفوع", "الحالة",
        "طريقة الدفع", "تاريخ الدفع", "شركة التأمين", "رقم الوثيقة",
        "الموعد", "السجل الطبي",
    ])
    for inv in q.order_by(Invoice.id.asc()).all():
        w.writerow([
            inv.id,
            inv.created_at.strftime("%Y-%m-%d") if inv.created_at else "",
            inv.patient.full_name if inv.patient else "",
            inv.description, f"{inv.amount:.2f}",
            f"{(inv.discount or 0):.2f}", f"{(inv.tax_rate or 0):.2f}",
            f"{inv.total:.2f}", f"{(inv.paid_amount or 0):.2f}",
            inv.status.value if inv.status else "",
            inv.payment_method or "",
            inv.paid_at.strftime("%Y-%m-%d %H:%M") if inv.paid_at else "",
            inv.insurer or "", inv.policy_number or "",
            inv.appointment_id or "", inv.record_id or "",
        ])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="invoices.csv"'},
    )


@router.get("/{invoice_id}", response_model=InvoiceInDB, summary="عرض فاتورة معينة")
async def get_invoice(invoice_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب فاتورة بواسطة المعرف"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد فاتورة بالمعرف المحدد"
        )
    return invoice


@router.post("/", response_model=InvoiceInDB, summary="إنشاء فاتورة جديدة")
async def create_invoice(invoice: InvoiceCreate, db = Depends(get_db),
                         user = Depends(get_current_user)):
    """إنشاء فاتورة جديدة"""
    # التحقق من وجود المريض
    patient = db.query(Patient).filter(Patient.id == invoice.patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد مريض بالمعرف المحدد"
        )
    
    db_invoice = Invoice(
        patient_id=invoice.patient_id,
        appointment_id=invoice.appointment_id,
        record_id=invoice.record_id,
        amount=invoice.amount,
        discount=invoice.discount,
        tax_rate=invoice.tax_rate,
        paid_amount=0,
        description=invoice.description,
        status=invoice.status,
        insurer=invoice.insurer,
        policy_number=invoice.policy_number,
    )
    # البنود أولًا: المبلغ يُشتقّ منها فلا يتخلّف الإجمالي عن سطر واحد
    _attach_lines(db, db_invoice, invoice.lines)
    _validate_totals(db_invoice)
    _validate_links(db, invoice.patient_id, invoice.appointment_id, invoice.record_id)
    # فاتورة تُنشأ كمدفوعة ⇒ المدفوع = الإجمالي
    if db_invoice.status == InvoiceStatus.PAID:
        db_invoice.paid_amount = db_invoice.total
        db_invoice.paid_at = datetime.now()
    db.add(db_invoice)
    db.commit()
    db.refresh(db_invoice)
    # قيد تلقائي لحظة الإنشاء: ذمم المريض/التأمين مقابل إيراد الخدمات.
    # يلتزم وحده بعد التزام الفاتورة، فالفشل لا يُسقط الإنشاء — يبقى
    # الترحيل اليدوي من شاشة المحاسبة متاحًا للتصحيح.
    from app.routers.accounting import auto_post_invoice
    auto_post_invoice(db, db_invoice, user.username)
    db.refresh(db_invoice)
    return db_invoice


@router.post("/{invoice_id}/lines", response_model=InvoiceInDB,
             summary="إضافة بند إلى فاتورة غير مدفوعة")
async def add_invoice_line(
    invoice_id: int, line: InvoiceLineBase,
    db = Depends(get_db), _ = Depends(get_current_user),
):
    """يضيف سطرًا (كشفية، فحص، أشعة، دواء…) ويُعيد حساب المبلغ.

    الفواتير المدفوعة مُقفلة: الإيصال نهائيّ ولا يجوز سحب بند منه.
    """
    inv = _locked_invoice(db, invoice_id)
    inv.lines.append(InvoiceLine(
        kind=line.kind, description=line.description,
        quantity=line.quantity, unit_price=line.unit_price,
        amount=line.amount, ref_type=line.ref_type, ref_id=line.ref_id,
    ))
    _refresh_total(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.delete("/{invoice_id}/lines/{line_id}", response_model=InvoiceInDB,
               summary="حذف بند من فاتورة غير مدفوعة")
async def delete_invoice_line(
    invoice_id: int, line_id: int,
    db = Depends(get_db), _ = Depends(get_current_user),
):
    """يحذف سطرًا ويُعيد حساب المبلغ — ممنوع على فاتورة مدفوعة."""
    inv = _locked_invoice(db, invoice_id)
    row = next((x for x in inv.lines if x.id == line_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="البند غير موجود في هذه الفاتورة")
    inv.lines.remove(row)
    _refresh_total(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/{invoice_id}/pay", response_model=InvoiceInDB, summary="تسوية/دفع الفاتورة")
async def pay_invoice(
    invoice_id: int,
    payment: InvoicePayment,
    db = Depends(get_db),
    user = Depends(get_current_user),
):
    """دفع الفاتورة كاملًا أو دفعة جزئية مع تسجيل طريقة الدفع والوقت"""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="لا توجد فاتورة بالمعرف المحدد")
    if inv.status == InvoiceStatus.PAID:
        raise HTTPException(status_code=400, detail="الفاتورة مدفوعة بالفعل")
    if payment.method not in PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"طريقة دفع غير مسموحة — المسموحة: {', '.join(sorted(PAYMENT_METHODS))}",
        )
    if payment.method == "insurance" and not inv.insurer:
        raise HTTPException(
            status_code=400,
            detail="الدفع بالتأمين يتطلب تحديد شركة التأمين في الفاتورة أولًا",
        )

    total = inv.total
    remaining = round(total - (inv.paid_amount or 0), 2)
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="الفاتورة مسددة بالفعل")
    pay_amount = payment.amount if payment.amount is not None else remaining
    if pay_amount > remaining + 1e-6:
        raise HTTPException(
            status_code=400,
            detail=f"مبلغ الدفع ({pay_amount:.2f}) يتجاوز المتبقي ({remaining:.2f})",
        )

    # قيد التحصيل في معاملة واحدة مع تطبيق الدفعة: إن تعذّر الترحيل
    # تُرفض الدفعة برسالة صريحة بدل ترك ثغرة في الدفتر المحاسبي.
    from app.models import InvoiceLedgerPayment
    from app.routers.accounting import build_payment_entry

    paid_at = datetime.now()
    try:
        entry = build_payment_entry(db, inv, pay_amount, payment.method,
                                    user.username, paid_at)
    except HTTPException:
        db.rollback()
        raise

    inv.paid_amount = round((inv.paid_amount or 0) + pay_amount, 2)
    inv.payment_method = payment.method
    inv.paid_at = paid_at
    if inv.paid_amount >= total - 1e-6:
        inv.paid_amount = total
        inv.status = InvoiceStatus.PAID
    else:
        inv.status = InvoiceStatus.PARTIAL
    # صفّ سجل التحصيل حتى تراه شاشة المحاسبة كما هو — ربطه بالقيد
    db.add(InvoiceLedgerPayment(
        invoice_id=inv.id, amount=pay_amount, method=payment.method,
        paid_at=paid_at, reference=None, journal_entry_id=entry.id,
        created_by=user.username))
    db.commit()
    db.refresh(inv)
    return inv


@router.get("/{invoice_id}/print", summary="طباعة الفاتورة (HTML)")
async def print_invoice(invoice_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """إرجاع الفاتورة كصفحة HTML جاهزة للطباعة"""
    from fastapi.responses import HTMLResponse
    from app.invoice_template import render_invoice_html

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="لا يوجد فاتورة بالمعرف المحدد")
    return HTMLResponse(render_invoice_html(invoice, invoice.patient.full_name))


@router.get("/{invoice_id}/pdf", summary="تحميل الفاتورة PDF")
async def download_invoice_pdf(invoice_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """توليد الفاتورة كملف PDF عربي للتحميل/الطباعة"""
    from fastapi.responses import Response
    from app.pdf_utils import invoice_pdf

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="لا يوجد فاتورة بالمعرف المحدد")
    pdf_bytes = invoice_pdf(invoice, invoice.patient.full_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice_{invoice_id}.pdf"'},
    )


@router.put("/{invoice_id}", response_model=InvoiceInDB, summary="تحديث فاتورة")
async def update_invoice(invoice_id: int, invoice: InvoiceUpdate, db = Depends(get_db), _ = Depends(get_current_user)):
    """تحديث فاتورة"""
    db_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not db_invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد فاتورة بالمعرف المحدد"
        )

    data = invoice.model_dump(exclude_unset=True)
    # التحقق من الروابط الجديدة إن وُجدت
    _validate_links(db, db_invoice.patient_id, data.get("appointment_id"), data.get("record_id"))
    for field, value in data.items():
        setattr(db_invoice, field, value)
    _validate_totals(db_invoice)

    if "status" in data:
        _sync_paid_for_status(db_invoice)
    elif any(f in data for f in ("amount", "discount", "tax_rate")):
        # تغيير المبالغ: مدفوعة تظل تساوي الإجمالي، ولا يتجاوز المدفوع الإجمالي
        if db_invoice.status == InvoiceStatus.PAID:
            db_invoice.paid_amount = db_invoice.total
        elif (db_invoice.paid_amount or 0) > db_invoice.total:
            db_invoice.paid_amount = db_invoice.total

    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف فاتورة")
async def delete_invoice(invoice_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف فاتورة (للمدير فقط)"""
    db_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not db_invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد فاتورة بالمعرف المحدد"
        )

    # القيود المرحّلة على هذا المرجع تصبح معلّقة بمصدر مفقود بعد الحذف،
    # وخطرها أعمق من التشويه: قد يُعاد استخدام المعرّف فيُخمَد قيد الفاتورة
    # الجديدة «كمرحّل سابقًا» فلا يُرحَّل أبدًا — فيضيع الإيراد بصمت.
    from app.routers.accounting import purge_invoice_entries
    purge_invoice_entries(db, [invoice_id])

    db.delete(db_invoice)
    db.commit()
    return None