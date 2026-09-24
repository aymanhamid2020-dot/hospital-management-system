from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Report, User, Dispense, Medication, Patient
from app.schemas import ReportCreate, ReportUpdate, ReportInDB
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/reports", tags=["Reports"])


def _check_lang(lang: str) -> None:
    """لغة تقرير PDF: ar (افتراضي) أو en — غير ذلك 400."""
    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")


@router.get("/", response_model=List[ReportInDB], summary="عرض قائمة التقارير")
async def list_reports(db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب كل التقارير"""
    reports = db.query(Report).all()
    return reports


# ===== تقارير PDF المتخصصة =====
@router.get("/lab/pdf", summary="تقرير المختبر والأشعة PDF")
async def download_lab_report(
    status_filter: Optional[str] = Query(None, alias="status", description="فلترة بالحالة"),
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تقرير PDF لطلبات المختبر — للمدير (الكل) وللطبيب (طلباته فقط) — ar|en"""
    from fastapi.responses import Response
    from app.auth import get_user_role
    from app.models import LabOrder, Doctor
    from app.pdf_utils import lab_report_pdf

    _check_lang(lang)
    role = get_user_role(current_user)
    if role not in ("admin", "doctor"):
        raise HTTPException(status_code=403, detail="تقرير المختبر متاح للمدير والطبيب فقط")

    q = db.query(LabOrder)
    if role == "admin":
        label = "المستشفى كلها" if lang == "ar" else "Whole hospital"
    else:
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            raise HTTPException(status_code=403, detail="حسابك غير مرتبط بسجل طبيب")
        q = q.filter(LabOrder.doctor_id == linked.id)
        label = (f"طلبات د. {linked.full_name}" if lang == "ar"
                 else f"Orders of Dr. {linked.full_name}")
    if status_filter:
        q = q.filter(LabOrder.status == status_filter)
        label += (f" — الحالة: {status_filter}" if lang == "ar"
                  else f" — Status: {status_filter}")

    orders = q.order_by(LabOrder.ordered_at.desc()).all()
    return Response(
        content=lab_report_pdf(orders, label, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="lab_report{"_en" if lang == "en" else ""}.pdf"'},
    )


@router.get("/pharmacy/pdf", summary="تقرير الصيدلية PDF")
async def download_pharmacy_report(
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تقرير PDF لمخزون الصيدلية وتنبيهاته وآخر الصرف (للمدير فقط) — ar|en"""
    from fastapi.responses import Response
    from sqlalchemy import func as _func
    from app.models import Medication, Dispense
    from app.pdf_utils import pharmacy_report_pdf

    _check_lang(lang)
    meds = db.query(Medication).order_by(Medication.name.asc()).all()
    recent = db.query(Dispense).order_by(Dispense.created_at.desc()).limit(30).all()
    total = db.query(_func.count(Dispense.id)).scalar() or 0
    from app.models import StockMovement
    movements = (db.query(StockMovement)
                 .filter(StockMovement.type.in_(("disposal", "return")))
                 .order_by(StockMovement.created_at.desc()).limit(20).all())
    scope = "المخزون كله" if lang == "ar" else "Full inventory"
    return Response(
        content=pharmacy_report_pdf(meds, recent, scope, total, lang=lang,
                                    movements=movements),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="pharmacy_report{"_en" if lang == "en" else ""}.pdf"'},
    )


@router.get("/pharmacy/stats/pdf", summary="تقرير إحصاءات الصيدلية PDF")
async def download_pharmacy_stats_report(
    from_date: Optional[str] = Query(None, description="من تاريخ YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ YYYY-MM-DD (شامل)"),
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تقرير إحصاءات الصيدلية PDF لفترة (للمدير فقط) — ar|en"""
    from fastapi.responses import Response
    from app.pdf_utils import pharmacy_stats_pdf
    from app.routers.pharmacy import build_pharmacy_stats

    _check_lang(lang)
    stats = build_pharmacy_stats(db, from_date, to_date)
    return Response(
        content=pharmacy_stats_pdf(stats, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="pharmacy_stats'
                 f'{"_en" if lang == "en" else ""}.pdf"'},
    )


@router.get("/pharmacy/stats/csv", summary="تصدير إحصاءات الصيدلية CSV")
async def export_pharmacy_stats_csv(
    from_date: Optional[str] = Query(None, description="من تاريخ YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="إلى تاريخ YYYY-MM-DD (شامل)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تصدير إحصاءات الصيدلية CSV (للمدير فقط) — فترة + مخزون + أفضل الأدوية + يومي"""
    from app.routers.pharmacy import build_pharmacy_stats

    stats = build_pharmacy_stats(db, from_date, to_date)
    rows = [
        ["الفترة", "النطاق", stats.period, ""],
        ["الفترة", "عدد عمليات الصرف", stats.dispense_count, ""],
        ["الفترة", "الوحدات المصروفة", stats.units, ""],
        ["الفترة", "الإيراد (ر.س)", f"{stats.revenue:.2f}", ""],
        ["الفترة", "المحصّل (ر.س)", f"{stats.paid:.2f}", ""],
        ["الفترة", "المتبقي (ر.س)", f"{stats.outstanding:.2f}", ""],
        ["المخزون", "القيمة (ر.س)", f"{stats.inventory_value:.2f}", ""],
        ["المخزون", "منخفض", stats.low, ""],
        ["المخزون", "نافد", stats.out, ""],
        ["المخزون", "منتهٍ", stats.expired, ""],
        ["المخزون", "قارب الانتهاء", stats.expiring, ""],
    ]
    for t in stats.top_medications:
        rows.append(["أدوية", f"{t.name} ({t.code})", t.units, f"{t.revenue:.2f}"])
    for p in stats.daily:
        rows.append(["يومي", p.date, p.units, f"{p.revenue:.2f}"])
    return _csv_response(["القسم", "البند", "القيمة", "ملاحظة"],
                         rows, "pharmacy_stats.csv")


@router.get("/payroll/pdf", summary="كشف الرواتب PDF")
async def download_payroll_report(
    period: Optional[str] = Query(None, description="الشهر YYYY-MM (اختياري)"),
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """كشف رواتب PDF (للمدير فقط) — كل الفترات أو شهر محدد — ar|en"""
    from datetime import datetime as _dt
    from fastapi.responses import Response
    from app.models import Payroll
    from app.pdf_utils import payroll_report_pdf

    _check_lang(lang)
    label = "كل الفترات" if lang == "ar" else "All periods"
    q = db.query(Payroll)
    if period:
        try:
            _dt.strptime(period, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="صيغة الفترة يجب أن تكون YYYY-MM")
        q = q.filter(Payroll.period == period)
        label = f"شهر {period}" if lang == "ar" else f"Month {period}"

    entries = q.order_by(Payroll.period.desc(), Payroll.id.asc()).all()
    return Response(
        content=payroll_report_pdf(entries, label, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="payroll_report{"_en" if lang == "en" else ""}.pdf"'},
    )


# ===== تصدير CSV للتقارير المتخصصة (UTF-8 + BOM يفتح عربيًا في Excel) =====
def _csv_response(header: list, rows: list, filename: str):
    """استجابة CSV جاهزة بترميز UTF-8 مع BOM."""
    import csv as _csv
    import io as _io
    from fastapi.responses import Response

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _lab_scope_query(db, current_user, status_filter=None):
    """نطاق تقرير المختبر: المدير (الكل) / الطبيب (طلباته فقط)."""
    from app.auth import get_user_role
    from app.models import LabOrder, Doctor

    role = get_user_role(current_user)
    if role not in ("admin", "doctor"):
        raise HTTPException(status_code=403, detail="تقرير المختبر متاح للمدير والطبيب فقط")
    q = db.query(LabOrder)
    if role == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            raise HTTPException(status_code=403, detail="حسابك غير مرتبط بسجل طبيب")
        q = q.filter(LabOrder.doctor_id == linked.id)
    if status_filter:
        q = q.filter(LabOrder.status == status_filter)
    return q


_ST_LABELS = {"pending": "مسجّل", "in_progress": "قيد التنفيذ", "ready": "جاهزة",
              "reviewed": "مراجَعة", "cancelled": "ملغاة"}


@router.get("/lab/csv", summary="تصدير طلبات المختبر CSV")
async def export_lab_csv(
    status_filter: Optional[str] = Query(None, alias="status",
                                          description="فلترة بالحالة"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CSV لطلبات المختبر — للمدير (الكل) وللطبيب (طلباته فقط)"""
    from app.models import LabOrder
    orders = (_lab_scope_query(db, current_user, status_filter)
              .order_by(LabOrder.ordered_at.desc()).all())
    rows = []
    for o in orders:
        st = o.status.value if hasattr(o.status, "value") else str(o.status)
        tt = o.test_type.value if hasattr(o.test_type, "value") else str(o.test_type)
        rows.append([
            o.id, f"{o.ordered_at:%Y-%m-%d %H:%M}" if o.ordered_at else "",
            o.patient.full_name if o.patient else "",
            o.doctor.full_name if o.doctor else "",
            "أشعة" if tt == "radiology" else "تحليل",
            o.test_name, o.price or 0, _ST_LABELS.get(st, st), o.result or "",
        ])
    return _csv_response(
        ["#", "التاريخ", "المريض", "الطبيب", "النوع", "التحليل", "السعر (ر.س)",
         "الحالة", "النتيجة"],
        rows, "lab_orders.csv")


@router.get("/pharmacy/csv", summary="تصدير الصيدلية CSV")
async def export_pharmacy_csv(
    section: str = Query("inventory", description="inventory | dispenses | disposals"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """CSV مخزون الصيدلية أو سجل الصرف أو الإتلاف/الإرجاع (للمدير فقط)"""
    from app.models import Medication, Dispense

    if section == "inventory":
        meds = db.query(Medication).order_by(Medication.name.asc()).all()
        rows = [[m.id, m.code, m.name, m.quantity, m.unit, m.price,
                 round((m.price or 0) * (m.quantity or 0), 2), m.min_quantity,
                 f"{m.expiry_date:%Y-%m-%d}" if m.expiry_date else ""]
                for m in meds]
        return _csv_response(
            ["#", "الرمز", "الاسم", "الكمية", "الوحدة", "السعر (ر.س)",
             "قيمة السطر (ر.س)", "حد التنبيه", "تاريخ الانتهاء"],
            rows, "pharmacy_inventory.csv")

    if section == "dispenses":
        disps = db.query(Dispense).order_by(Dispense.created_at.desc()).all()
        st_labels = {"UNPAID": "غير مدفوع", "PARTIAL": "مدفوع جزئيًا", "PAID": "مدفوع"}
        rows = [[d.id,
                 f"{d.created_at:%Y-%m-%d %H:%M}" if d.created_at else "",
                 d.patient.full_name if d.patient else "",
                 d.medication.name if d.medication else f"#{d.medication_id}",
                 d.quantity, d.unit_price or 0,
                 round(float(d.total_price or 0), 2),
                 d.dispensed_by or "",
                 d.dosage or "", d.frequency or "", d.duration or "",
                 st_labels.get(d.status, d.status),
                 "مرتجع" if d.returned_at is not None else ""]
                for d in disps]
        return _csv_response(
            ["#", "التاريخ", "المريض", "الدواء", "الكمية", "سعر الوحدة",
             "الإجمالي (ر.س)", "صرفه", "الجرعة", "التكرار", "المدة",
             "حالة الدفع", "المرتجع"],
            rows, "pharmacy_dispenses.csv")

    if section == "disposals":
        from app.models import StockMovement
        mvs = (db.query(StockMovement)
               .filter(StockMovement.type.in_(("disposal", "return")))
               .order_by(StockMovement.created_at.desc()).all())
        mv_labels = {"disposal": "إتلاف", "return": "إرجاع"}
        rows = [[mv.id,
                 f"{mv.created_at:%Y-%m-%d %H:%M}" if mv.created_at else "",
                 mv_labels.get(mv.type, mv.type),
                 mv.medication.name if mv.medication else f"#{mv.medication_id}",
                 abs(int(mv.change or 0)),
                 mv.quantity_after if mv.quantity_after is not None else "",
                 mv.note or "", mv.made_by or ""]
                for mv in mvs]
        return _csv_response(
            ["#", "التاريخ", "النوع", "الدواء", "الكمية", "الرصيد بعد",
             "السبب", "بواسطة"],
            rows, "pharmacy_disposals.csv")

    raise HTTPException(status_code=400,
                        detail="section يجب أن يكون inventory أو dispenses أو disposals")


@router.get("/payroll/csv", summary="تصدير كشف الرواتب CSV")
async def export_payroll_csv(
    period: Optional[str] = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """CSV كشف الرواتب (للمدير فقط)"""
    from datetime import datetime as _dt
    from app.models import Payroll

    q = db.query(Payroll)
    if period:
        try:
            _dt.strptime(period, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="صيغة الفترة يجب أن تكون YYYY-MM")
        q = q.filter(Payroll.period == period)
    entries = q.order_by(Payroll.period.desc(), Payroll.id.asc()).all()
    rows = []
    for e in entries:
        st = e.status.value if hasattr(e.status, "value") else str(e.status)
        rows.append([
            e.id, e.period,
            e.staff.full_name if e.staff else f"#{e.staff_id}",
            e.base_salary or 0, e.bonus or 0, e.deduction or 0, e.net,
            "مصروف" if st == "paid" else "غير مصروف",
            f"{e.paid_at:%Y-%m-%d}" if e.paid_at else "",
        ])
    return _csv_response(
        ["#", "الفترة", "الموظف", "الأساسي", "البدلات", "الاستقطاعات",
         "الصافي (ر.س)", "الحالة", "تاريخ الصرف"],
        rows, "payroll.csv")


@router.get("/{report_id}", response_model=ReportInDB, summary="عرض تقرير معين")
async def get_report(report_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب تقرير بواسطة المعرف"""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد تقرير بالمعرف المحدد"
        )
    return report


@router.post("/", response_model=ReportInDB, summary="إنشاء تقرير جديد")
async def create_report(report: ReportCreate, db = Depends(get_db), _ = Depends(get_current_user)):
    """إنشاء تقرير جديد"""
    db_report = Report(
        title=report.title,
        description=report.description,
        report_type=report.report_type,
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report


@router.put("/{report_id}", response_model=ReportInDB, summary="تحديث تقرير")
async def update_report(report_id: int, report: ReportUpdate, db = Depends(get_db), _ = Depends(get_current_user)):
    """تحديث تقرير"""
    db_report = db.query(Report).filter(Report.id == report_id).first()
    if not db_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد تقرير بالمعرف المحدد"
        )
    
    for field, value in report.model_dump(exclude_unset=True).items():
        setattr(db_report, field, value)

    db.commit()
    db.refresh(db_report)
    return db_report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف تقرير")
async def delete_report(report_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف تقرير (للمدير فقط)"""
    db_report = db.query(Report).filter(Report.id == report_id).first()
    if not db_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد تقرير بالمعرف المحدد"
        )
    
    db.delete(db_report)
    db.commit()
    return None


# ===== تقارير الحسابات والمبيعات =====
def _period_range(period: Optional[str]):
    """تحويل YYYY-MM إلى (from, to) لتصفية SQL — ترفع 400 إذا الصيغة خاطئة."""
    if not period:
        return None, None
    try:
        from datetime import datetime as _dt
        dt = _dt.strptime(period, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="صيغة الفترة يجب أن تكون YYYY-MM")
    nxt = _dt(dt.year + (1 if dt.month == 12 else 0),
              1 if dt.month == 12 else dt.month + 1, 1)
    return dt, nxt


@router.get("/accounts/sales/csv", summary="تصدير سجل المبيعات CSV")
async def export_accounts_csv(
    period: Optional[str] = Query(None, description="الشهر YYYY-MM"),
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """سجل المبيعات CSV (مدير فقط) — عربي أو إنجليزي"""
    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")
    from datetime import datetime as _dt
    q = db.query(Dispense).filter(Dispense.returned_at.is_(None))  # المرتجع مستثنى
    fr, to = _period_range(period)
    if fr:
        q = q.filter(Dispense.created_at >= fr, Dispense.created_at < to)
    entries = q.order_by(Dispense.created_at.desc()).all()
    if lang == "en":
        headers = ["#", "Date", "Patient", "Medicine", "Qty", "Unit Price",
                    "Total", "Payment", "Status", "Paid", "Outstanding", "Dispensed By"]
        rows = [[d.id, (d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "-"),
                 d.patient.full_name if d.patient else f"#{d.patient_id}",
                 d.medication.name if d.medication else f"#{d.medication_id}",
                 d.quantity, f"{d.unit_price:,.2f}", f"{d.total_price:,.2f}",
                 d.payment_method, d.status, f"{d.paid_amount:,.2f}",
                 f"{round(d.total_price-d.paid_amount,2):,.2f}", d.dispensed_by or "-"]
                for d in entries]
    else:
        headers = ["#", "التاريخ", "المريض", "الدواء", "الكمية", "سعر الوحدة",
                    "الإجمالي", "طريقة الدفع", "الحالة", "المدفوع", "المتبقي", "صرفه"]
        st_labels = {"UNPAID": "غير مدفوع", "PARTIAL": "مدفوع جزئيًا", "PAID": "مدفوع"}
        pm_labels = {"cash": "نقدي", "card": "بطاقة", "insurance": "تأمين"}
        rows = [[d.id, (d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "-"),
                 d.patient.full_name if d.patient else f"#{d.patient_id}",
                 d.medication.name if d.medication else f"#{d.medication_id}",
                 d.quantity, f"{d.unit_price:,.2f}", f"{d.total_price:,.2f}",
                 pm_labels.get(d.payment_method, d.payment_method),
                 st_labels.get(d.status, d.status), f"{d.paid_amount:,.2f}",
                 f"{round(d.total_price-d.paid_amount,2):,.2f}", d.dispensed_by or "-"]
                for d in entries]
    return _csv_response(headers, rows,
                         f"accounts_sales{"_en" if lang == "en" else ""}.csv")


@router.get("/accounts/sales/pdf", summary="تقرير المبيعات PDF")
async def download_accounts_report(
    period: Optional[str] = Query(None, description="الشهر YYYY-MM"),
    lang: str = Query("ar", description="لغة التقرير: ar أو en"),
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تقرير المبيعات PDF (للمدير فقط) — ar|en"""
    from fastapi.responses import Response
    from app.pdf_utils import accounts_sales_pdf

    _check_lang(lang)
    q = db.query(Dispense).filter(Dispense.returned_at.is_(None))  # المرتجع مستثنى
    fr, to = _period_range(period)
    if fr:
        q = q.filter(Dispense.created_at >= fr, Dispense.created_at < to)
    entries = q.order_by(Dispense.created_at.desc()).all()
    label = period or "كل الفترات"
    return Response(
        content=accounts_sales_pdf(entries, label, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="accounts_sales{"_en" if lang == "en" else ""}.pdf"'},
    )