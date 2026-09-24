"""توليد ملفات PDF عربية (فواتير وتقارير) باستخدام fpdf2 + تشكيل النص العربي."""
import os
from io import BytesIO

from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

# البحث عن خط عربي يعمل على ويندوز ولينكس معًا (حاوية Docker)
# يمكن فرض مسار بمتغيري HMS_FONT_REGULAR / HMS_FONT_BOLD
_REGULAR_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",                        # ويندوز
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",    # الحاوية (fonts-dejavu-core)
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
]
_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
]


def _resolve_font(env_name: str, candidates: list) -> str:
    for path in [os.environ.get(env_name)] + list(candidates):
        if path and os.path.isfile(path):
            return str(path)
    return ""


FONT_REGULAR = _resolve_font("HMS_FONT_REGULAR", _REGULAR_CANDIDATES)
FONT_BOLD = _resolve_font("HMS_FONT_BOLD", _BOLD_CANDIDATES) or FONT_REGULAR

PRIMARY = (44, 123, 229)    # أزرق
DARK = (51, 51, 51)
GRAY = (136, 136, 136)
LIGHT_BG = (240, 246, 255)
GREEN = (40, 167, 69)
RED = (220, 53, 69)


def ar(text: str) -> str:
    """تشكيل وعكس اتجاه النص العربي لعرضه صحيحًا في PDF."""
    if not text:
        return ""
    try:
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except Exception:
        return str(text)


class ArabicPDF(FPDF):
    """PDF بخط عربي جاهز مع ترويسة وتذييل."""

    def __init__(self, title: str, lang: str = "ar"):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title = title
        self.lang = lang if lang in ("ar", "en") else "ar"
        self.footer_text = (
            "Hospital & Clinics Management System — computer-generated document"
            if self.lang == "en"
            else "نظام إدارة المستشفيات والعيادات — مستند مولّد إلكترونيًا"
        )
        if not FONT_REGULAR:
            raise RuntimeError(
                "لم يُعثر على خط عربي: ثبّت Arial (ويندوز) أو fonts-dejavu-core "
                "(لينكس) أو حدّد HMS_FONT_REGULAR"
            )
        self.add_font("ar", "", FONT_REGULAR)
        self.add_font("ar", "B", FONT_BOLD or FONT_REGULAR)
        self.set_auto_page_break(auto=True, margin=20)
        self.add_page()
        # ترويسة
        self.set_fill_color(*PRIMARY)
        self.rect(0, 0, 210, 28, "F")
        self.set_xy(10, 7)
        self.set_text_color(255, 255, 255)
        self.set_font("ar", "B", 16)
        self.cell(0, 8, ar(title), align="C")
        self.set_y(34)
        self.set_text_color(*DARK)

    def footer(self):
        self.set_y(-15)
        self.set_font("ar", "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 10, ar(self.footer_text), align="C")

    def kv_row(self, label: str, value, bold_label: bool = True):
        """سطر (تسمية: قيمة) — من اليمين لليسار بالعربية ومن اليسار بالإنجليزية."""
        self.set_font("ar", "B" if bold_label else "", 11)
        if self.lang == "en":
            self.set_text_color(*PRIMARY)
            self.set_xy(10, self.get_y())
            self.cell(45, 9, ar(f"{label}:"), align="L")
            self.set_font("ar", "", 11)
            self.set_text_color(*DARK)
            self.set_xy(55, self.get_y() - 9)
            self.cell(145, 9, ar(str(value)), align="L")
            self.ln(9)
            return
        self.set_text_color(*PRIMARY)
        label_w = 45
        x_label = 200 - label_w
        self.set_xy(x_label, self.get_y())
        self.cell(label_w, 9, ar(f"{label}:"), align="R")
        self.set_font("ar", "", 11)
        self.set_text_color(*DARK)
        self.set_xy(10, self.get_y() - 9)
        self.cell(145, 9, ar(str(value)), align="R")
        self.ln(9)

    def section(self, text: str):
        """عنوان قسم بخلفية فاتحة."""
        self.ln(3)
        self.set_fill_color(*LIGHT_BG)
        self.set_draw_color(*PRIMARY)
        self.set_font("ar", "B", 12)
        self.set_text_color(*PRIMARY)
        self.cell(0, 10, f"  {ar(text)}", border=1, fill=True,
                  align=("L" if self.lang == "en" else "R"),
                  new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*DARK)
        self.ln(2)


def invoice_pdf(invoice, patient_name: str) -> bytes:
    """توليد PDF لفاتورة."""
    pdf = ArabicPDF("فاتورة")
    pdf.section("بيانات الفاتورة")
    status_value = invoice.status.value if hasattr(invoice.status, "value") else str(invoice.status)
    status_labels = {"paid": "مدفوعة", "unpaid": "غير مدفوعة", "partial": "مدفوعة جزئيًا"}
    pdf.kv_row("رقم الفاتورة", f"#{invoice.id}")
    pdf.kv_row("التاريخ", invoice.created_at.strftime("%Y-%m-%d %H:%M") if invoice.created_at else "-")
    pdf.kv_row("الحالة", status_labels.get(status_value, status_value))

    pdf.section("بيانات المريض")
    pdf.kv_row("المريض", f"{patient_name} (#{invoice.patient_id})")
    pdf.kv_row("الوصف", invoice.description or "-")

    pdf.section("المبلغ")
    pdf.set_font("ar", "B", 20)
    pdf.set_text_color(*(RED if status_value == "unpaid" else PRIMARY))
    pdf.cell(0, 16, ar(f"الإجمالي: {invoice.total:,.2f} ر.س"), align="C", new_x="LMARGIN", new_y="NEXT")

    # تفاصيل الدفع والروابط
    pdf.kv_row("المبلغ الأساسي", f"{invoice.amount:,.2f} ر.س")
    if invoice.discount:
        pdf.kv_row("الخصم", f"-{invoice.discount:,.2f} ر.س")
    if invoice.tax_rate:
        pdf.kv_row(f"الضريبة ({invoice.tax_rate:g}%)", f"{invoice.tax:,.2f} ر.س")
    if invoice.paid_amount:
        pdf.kv_row("المدفوع", f"{invoice.paid_amount:,.2f} ر.س")
        remaining = invoice.total - invoice.paid_amount
        if remaining > 0.005:
            pdf.kv_row("المتبقي", f"{remaining:,.2f} ر.س")
    if invoice.paid_at:
        method = invoice.payment_method or "-"
        method_labels = {"cash": "نقدي", "card": "بطاقة", "insurance": "تأمين"}
        pdf.set_text_color(*DARK)
        pdf.kv_row("طريقة الدفع", method_labels.get(method, method))
        pdf.kv_row("تاريخ الدفع", invoice.paid_at.strftime("%Y-%m-%d %H:%M"))
    if getattr(invoice, "insurer", None):
        pdf.kv_row("شركة التأمين", invoice.insurer)
        if getattr(invoice, "policy_number", None):
            pdf.kv_row("رقم الوثيقة", invoice.policy_number)
    if getattr(invoice, "appointment_id", None):
        pdf.kv_row("الموعد المرتبط", f"#{invoice.appointment_id}")
    if getattr(invoice, "record_id", None):
        pdf.kv_row("السجل الطبي المرتبط", f"#{invoice.record_id}")

    pdf.ln(10)
    pdf.set_font("ar", "", 9)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(0, 6, ar("هذه الفاتورة صادرة إلكترونيًا من نظام إدارة المستشفيات والعيادات — تُعتبر صالحة دون توقيع."), align="C")

    return bytes(pdf.output())


def record_pdf(record, patient_name: str, doctor_name: str) -> bytes:
    """توليد PDF لسجل طبي."""
    pdf = ArabicPDF("سجل طبي")
    pdf.section("بيانات الزيارة")
    pdf.kv_row("رقم السجل", f"#{record.id}")
    pdf.kv_row("التاريخ", record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else "-")
    pdf.kv_row("المريض", f"{patient_name} (#{record.patient_id})")
    pdf.kv_row("الطبيب", doctor_name or "-")

    pdf.section("التشخيص")
    pdf.set_font("ar", "", 12)
    pdf.multi_cell(0, 8, ar(record.diagnosis or "-"), align="R")

    if record.prescription:
        pdf.section("الوصفة الطبية")
        pdf.set_font("ar", "", 12)
        pdf.multi_cell(0, 8, ar(record.prescription), align="R")

    if record.notes:
        pdf.section("ملاحظات")
        pdf.set_font("ar", "", 11)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(0, 7, ar(record.notes), align="R")
        pdf.set_text_color(*DARK)

    return bytes(pdf.output())


def stats_report_pdf(stats: dict, period_label: str, lang: str = "ar") -> bytes:
    """توليد تقرير إحصائي PDF (فترة شهر أو لحظي) — بالعربية أو الإنجليزية."""
    if lang == "en":
        return _stats_report_en(stats, period_label)
    pdf = ArabicPDF("تقرير إحصائي")
    pdf.section(f"الفترة: {period_label}")
    pdf.kv_row("تاريخ الإصدار", __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("الموارد")
    pdf.kv_row("المرضى", stats.get("total_patients", 0))
    pdf.kv_row("الأطباء", stats.get("total_doctors", 0))
    pdf.kv_row("الموظفون", stats.get("total_staff", 0))
    pdf.kv_row("الأقسام", stats.get("total_departments", 0))
    pdf.kv_row("الأسرّة (مشغولة/الكل)",
               f"{stats.get('beds_occupied', 0)} / {stats.get('beds_total', 0)}")

    pdf.section("المواعيد")
    pdf.kv_row("الإجمالي", stats.get("total_appointments", 0))
    pdf.kv_row("اليوم", stats.get("appointments_today", 0))
    pdf.kv_row("المعلّقة", stats.get("pending_appointments", 0))
    status_labels = {"pending": "معلّقة", "confirmed": "مؤكدة", "cancelled": "ملغاة", "completed": "مكتملة"}
    for k, v in (stats.get("appointments_by_status") or {}).items():
        pdf.kv_row(f"  • {status_labels.get(k, k)}", v)

    pdf.section("المالية (ر.س)")
    pdf.kv_row("إجمالي الفواتير", f"{stats.get('revenue_total', 0):,.2f}")
    pdf.kv_row("المحصّل", f"{stats.get('revenue_paid', 0):,.2f}")
    pdf.kv_row("المتبقي", f"{stats.get('revenue_unpaid', 0):,.2f}")

    pdf.ln(8)
    pdf.set_font("ar", "", 9)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(0, 6, ar("وُجد هذا التقرير آليًا من نظام إدارة المستشفيات والعيادات."), align="C")

    return bytes(pdf.output())


def patient_file_pdf(patient, records, appointments, invoices, attachments) -> bytes:
    """توليد الملف الشامل للمريض: بيانات + سجلات + مواعيد + فواتير + مرفقات."""
    from datetime import datetime as _dt

    pdf = ArabicPDF("الملف الشامل للمريض")

    # --- البيانات الشخصية ---
    pdf.section("البيانات الشخصية")
    pdf.kv_row("رقم الملف", f"#{patient.id}")
    pdf.kv_row("الاسم الكامل", patient.full_name)
    if patient.date_of_birth:
        age = (_dt.now() - patient.date_of_birth).days // 365
        pdf.kv_row("تاريخ الميلاد", f"{patient.date_of_birth:%Y-%m-%d} ({age} سنة)")
    pdf.kv_row("الجنس", patient.gender.value if hasattr(patient.gender, "value") else patient.gender)
    pdf.kv_row("الهاتف", patient.phone or "-")
    pdf.kv_row("البريد", patient.email or "-")
    pdf.kv_row("العنوان", patient.address or "-")
    pdf.kv_row("الهوية الوطنية", getattr(patient, "national_id", None) or "-")
    pdf.kv_row("التأمين", getattr(patient, "insurer", None) or "-")
    if getattr(patient, "policy_number", None):
        pdf.kv_row("رقم وثيقة التأمين", patient.policy_number)
    pdf.kv_row("مجموعة الدم", patient.blood_type or "-")
    pdf.kv_row("تاريخ التسجيل", f"{patient.created_at:%Y-%m-%d}" if patient.created_at else "-")

    # --- السجلات الطبية ---
    pdf.section(f"السجلات الطبية ({len(records)})")
    if records:
        for rec in records[:25]:
            doctor = rec.doctor.full_name if rec.doctor else "-"
            date = f"{rec.created_at:%Y-%m-%d}" if rec.created_at else "-"
            pdf.set_font("ar", "B", 10)
            pdf.set_text_color(*PRIMARY)
            pdf.cell(0, 7, ar(f"• {date} — {doctor}: {rec.diagnosis}"), align="R",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*DARK)
            if rec.prescription:
                pdf.set_font("ar", "", 9)
                pdf.set_text_color(*GRAY)
                pdf.multi_cell(0, 6, ar(f"  الوصفة: {rec.prescription}"), align="R")
                pdf.set_text_color(*DARK)
        if len(records) > 25:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, ar(f"… و{len(records) - 25} سجلًا آخر"), align="R",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*DARK)
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد سجلات طبية بعد."), align="R")

    # --- المواعيد ---
    pdf.section(f"المواعيد ({len(appointments)})")
    if appointments:
        status_labels = {"pending": "معلّقة", "confirmed": "مؤكدة",
                         "cancelled": "ملغاة", "completed": "مكتملة"}
        for appt in appointments[:15]:
            doctor = appt.doctor.full_name if appt.doctor else "-"
            st = status_labels.get(appt.status.value if hasattr(appt.status, "value") else str(appt.status), "-")
            pdf.set_font("ar", "", 10)
            pdf.cell(0, 7,
                     ar(f"• {appt.appointment_date:%Y-%m-%d %H:%M} — {doctor} — {st}"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد مواعيد."), align="R")

    # --- الفواتير ---
    total = sum(i.total for i in invoices)
    paid = sum((i.paid_amount or 0) for i in invoices)
    pdf.section(f"الفواتير ({len(invoices)})")
    pdf.kv_row("إجمالي المستحقات", f"{total:,.2f} ر.س")
    pdf.kv_row("المحصّل", f"{paid:,.2f} ر.س")
    pdf.kv_row("المتبقي", f"{max(0.0, total - paid):,.2f} ر.س")
    if invoices:
        status_labels = {"paid": "مدفوعة", "unpaid": "غير مدفوعة", "partial": "جزئية"}
        for inv in invoices[:15]:
            st = status_labels.get(inv.status.value if hasattr(inv.status, "value") else str(inv.status), "-")
            pdf.set_font("ar", "", 10)
            pdf.cell(0, 7,
                     ar(f"• فاتورة #{inv.id} — {inv.total:,.2f} ر.س — {st}"),
                     align="R", new_x="LMARGIN", new_y="NEXT")

    # --- المرفقات ---
    pdf.section(f"المرفقات الطبية ({len(attachments)})")
    if attachments:
        def _fmt(b):
            return f"{b / 1048576:.1f} MB" if b >= 1048576 else f"{b // 1024} KB"
        for att in attachments[:20]:
            pdf.set_font("ar", "", 10)
            pdf.cell(0, 7,
                     ar(f"• {att.original_name} ({_fmt(att.size_bytes)})"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد مرفقات."), align="R")

    # --- توقيع وتذييل ---
    pdf.ln(10)
    pdf.set_font("ar", "", 9)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(0, 6,
                   ar(f"صدر هذا الملف آليًا في {_dt.now():%Y-%m-%d %H:%M} "
                      f"من نظام إدارة المستشفيات والعيادات — سري ويخص المريض المذكور أعلاه."),
                   align="C")

    return bytes(pdf.output())


def lab_report_pdf(orders, label: str, lang: str = "ar") -> bytes:
    """تقرير طلبات المختبر والأشعة (ملخص الحالات + تفاصيل) — ar|en."""
    if lang == "en":
        return _lab_report_en(orders, label)
    from datetime import datetime as _dt

    status_labels = {"pending": "مسجّل", "in_progress": "قيد التنفيذ",
                     "ready": "جاهزة", "reviewed": "مراجَعة", "cancelled": "ملغاة"}
    counts = {}
    for o in orders:
        key = o.status.value if hasattr(o.status, "value") else str(o.status)
        counts[key] = counts.get(key, 0) + 1

    pdf = ArabicPDF("تقرير المختبر والأشعة")
    pdf.section(f"النطاق: {label}")
    pdf.kv_row("تاريخ الإصدار", _dt.now().strftime("%Y-%m-%d %H:%M"))
    pdf.kv_row("إجمالي الطلبات", len(orders))
    pdf.kv_row("نتائج مكتملة", counts.get("ready", 0) + counts.get("reviewed", 0))

    pdf.section("التوزيع حسب الحالة")
    for key in ("pending", "in_progress", "ready", "reviewed", "cancelled"):
        if key in counts:
            pdf.kv_row(f"  • {status_labels[key]}", counts[key])

    pdf.section("تفاصيل الطلبات")
    if orders:
        for o in orders[:40]:
            pat = o.patient.full_name if o.patient else "-"
            key = o.status.value if hasattr(o.status, "value") else str(o.status)
            ttype = o.test_type.value if hasattr(o.test_type, "value") else str(o.test_type)
            line = (f"• #{o.id} {pat} — {o.test_name} "
                    f"({'أشعة' if ttype == 'radiology' else 'تحليل'}) — "
                    f"{status_labels.get(key, key)}")
            if o.price:
                line += f" — {o.price:,.2f} ر.س"
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, ar(line[:115]), align="R", new_x="LMARGIN", new_y="NEXT")
        if len(orders) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, ar(f"… و{len(orders) - 40} طلبًا آخر (عُرضت أول 40)"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد طلبات مطابقة."), align="R")
    return bytes(pdf.output())


def pharmacy_report_pdf(medications, dispenses, label: str, dispense_count: int = 0,
                        lang: str = "ar") -> bytes:
    """تقرير الصيدلية: ملخص المخزون + تنبيهاته + آخر عمليات الصرف — ar|en."""
    if lang == "en":
        return _pharmacy_report_en(medications, dispenses, label, dispense_count)
    from datetime import datetime as _dt

    total_value = sum((m.price or 0) * (m.quantity or 0) for m in medications)
    low = [m for m in medications if (m.quantity or 0) <= (m.min_quantity or 0)]

    pdf = ArabicPDF("تقرير الصيدلية")
    pdf.section(f"النطاق: {label}")
    pdf.kv_row("تاريخ الإصدار", _dt.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("ملخص المخزون")
    pdf.kv_row("عدد الأدوية", len(medications))
    pdf.kv_row("قيمة المخزون (ر.س)", f"{total_value:,.2f}")
    pdf.kv_row("أدوية تحت حد التنبيه", len(low))
    pdf.kv_row("عمليات الصرف الإجمالية", dispense_count)

    if low:
        pdf.section("تنبيهات المخزون المنخفض")
        for m in low[:20]:
            line = (f"• {m.name} ({m.code}) — المتاح {m.quantity} {m.unit or ''} "
                    f"— الحد {m.min_quantity}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*RED)
            pdf.cell(0, 7, ar(line[:110]), align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.section("آخر عمليات الصرف")
    if dispenses:
        for d in dispenses[:30]:
            pat = d.patient.full_name if d.patient else "-"
            med = d.medication.name if d.medication else f"#{d.medication_id}"
            line = f"• {pat} — {med} × {d.quantity} — {(d.unit_price or 0):,.2f} ر.س"
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, ar(line[:110]), align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد عمليات صرف."), align="R")
    return bytes(pdf.output())


def payroll_report_pdf(entries, period_label: str, lang: str = "ar") -> bytes:
    """كشف رواتب: إجماليات الفترة + تفاصيل القيود — ar|en."""
    if lang == "en":
        return _payroll_report_en(entries, period_label)
    from datetime import datetime as _dt

    pdf = ArabicPDF("كشف الرواتب")
    pdf.section(f"الفترة: {period_label}")
    pdf.kv_row("تاريخ الإصدار", _dt.now().strftime("%Y-%m-%d %H:%M"))
    pdf.kv_row("عدد القيود", len(entries))

    pdf.section("الإجماليات (ر.س)")
    pdf.kv_row("إجمالي الأساسي", f"{sum(e.base_salary or 0 for e in entries):,.2f}")
    pdf.kv_row("إجمالي البدلات", f"{sum(e.bonus or 0 for e in entries):,.2f}")
    pdf.kv_row("إجمالي الاستقطاعات", f"{sum(e.deduction or 0 for e in entries):,.2f}")
    pdf.kv_row("إجمالي الصافي", f"{sum(e.net or 0 for e in entries):,.2f}")
    paid = sum(1 for e in entries
               if (e.status.value if hasattr(e.status, "value") else e.status) == "paid")
    pdf.kv_row("مصروف / غير مصروف", f"{paid} / {len(entries) - paid}")

    pdf.section("التفاصيل")
    if entries:
        for e in entries[:40]:
            staff = e.staff.full_name if e.staff else f"#{e.staff_id}"
            key = e.status.value if hasattr(e.status, "value") else str(e.status)
            line = (f"• {e.period} — {staff} — الأساسي {e.base_salary or 0:,.2f} — "
                    f"الصافي {e.net:,.2f} — "
                    f"{'مصروف' if key == 'paid' else 'غير مصروف'}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, ar(line[:115]), align="R", new_x="LMARGIN", new_y="NEXT")
        if len(entries) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, ar(f"… و{len(entries) - 40} قيدًا آخر (عُرضت أول 40)"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد قيود رواتب."), align="R")
    return bytes(pdf.output())


# ===== التقارير المتخصصة بالإنجليزية (lang=en) =====
# صيغ مستقلة تُستدعى من الدوال أعلاه عند طلب الإنجليزية — مسار العربية أعلاه
# يبقى متعديلاً بمفرده تمامًا.
def _stats_report_en(stats: dict, period_label: str) -> bytes:
    """English statistical report (month or live snapshot)."""
    from datetime import datetime as _dt

    pdf = ArabicPDF("Statistical Report", lang="en")
    pdf.section(f"Period: {period_label}")
    pdf.kv_row("Issued at", _dt.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("Resources")
    pdf.kv_row("Patients", stats.get("total_patients", 0))
    pdf.kv_row("Doctors", stats.get("total_doctors", 0))
    pdf.kv_row("Staff", stats.get("total_staff", 0))
    pdf.kv_row("Departments", stats.get("total_departments", 0))
    pdf.kv_row("Beds (occupied/total)",
               f"{stats.get('beds_occupied', 0)} / {stats.get('beds_total', 0)}")

    pdf.section("Appointments")
    pdf.kv_row("Total", stats.get("total_appointments", 0))
    pdf.kv_row("Today", stats.get("appointments_today", 0))
    pdf.kv_row("Pending", stats.get("pending_appointments", 0))
    st_en = {"pending": "Pending", "confirmed": "Confirmed",
             "cancelled": "Cancelled", "completed": "Completed"}
    for k, v in (stats.get("appointments_by_status") or {}).items():
        pdf.kv_row(f"  • {st_en.get(k, k)}", v)

    pdf.section("Finance (SAR)")
    pdf.kv_row("Total invoices", f"{stats.get('revenue_total', 0):,.2f}")
    pdf.kv_row("Collected", f"{stats.get('revenue_paid', 0):,.2f}")
    pdf.kv_row("Remaining", f"{stats.get('revenue_unpaid', 0):,.2f}")

    pdf.ln(8)
    pdf.set_font("ar", "", 9)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(0, 6,
                   "This report was generated automatically by the "
                   "Hospital & Clinics Management System.", align="C")
    return bytes(pdf.output())


def _lab_report_en(orders, label: str) -> bytes:
    """English lab & radiology orders report (status rollup + details)."""
    from datetime import datetime as _dt

    st_en = {"pending": "Registered", "in_progress": "In progress",
             "ready": "Ready", "reviewed": "Reviewed", "cancelled": "Cancelled"}
    counts = {}
    for o in orders:
        key = o.status.value if hasattr(o.status, "value") else str(o.status)
        counts[key] = counts.get(key, 0) + 1

    pdf = ArabicPDF("Lab & Radiology Report", lang="en")
    pdf.section(f"Scope: {label}")
    pdf.kv_row("Issued at", _dt.now().strftime("%Y-%m-%d %H:%M"))
    pdf.kv_row("Total orders", len(orders))
    pdf.kv_row("Completed results", counts.get("ready", 0) + counts.get("reviewed", 0))

    pdf.section("Distribution by status")
    for key in ("pending", "in_progress", "ready", "reviewed", "cancelled"):
        if key in counts:
            pdf.kv_row(f"  • {st_en[key]}", counts[key])

    pdf.section("Order details")
    if orders:
        for o in orders[:40]:
            pat = o.patient.full_name if o.patient else "-"
            key = o.status.value if hasattr(o.status, "value") else str(o.status)
            ttype = o.test_type.value if hasattr(o.test_type, "value") else str(o.test_type)
            line = (f"• #{o.id} {pat} — {o.test_name} "
                    f"({'Radiology' if ttype == 'radiology' else 'Lab test'}) — "
                    f"{st_en.get(key, key)}")
            if o.price:
                line += f" — {o.price:,.2f} SAR"
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, line[:115], align="L", new_x="LMARGIN", new_y="NEXT")
        if len(orders) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, f"... and {len(orders) - 40} more orders (first 40 shown)",
                     align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, "No matching orders.", align="L")
    return bytes(pdf.output())


def _pharmacy_report_en(medications, dispenses, label: str, dispense_count: int) -> bytes:
    """English pharmacy report: inventory summary + low stock + recent dispenses."""
    from datetime import datetime as _dt

    total_value = sum((m.price or 0) * (m.quantity or 0) for m in medications)
    low = [m for m in medications if (m.quantity or 0) <= (m.min_quantity or 0)]

    pdf = ArabicPDF("Pharmacy Report", lang="en")
    pdf.section(f"Scope: {label}")
    pdf.kv_row("Issued at", _dt.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("Inventory summary")
    pdf.kv_row("Medications count", len(medications))
    pdf.kv_row("Inventory value (SAR)", f"{total_value:,.2f}")
    pdf.kv_row("Low-stock medications", len(low))
    pdf.kv_row("Total dispenses", dispense_count)

    if low:
        pdf.section("Low stock alerts")
        for m in low[:20]:
            line = (f"• {m.name} ({m.code}) — Available {m.quantity} {m.unit or ''} "
                    f"— Threshold {m.min_quantity}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*RED)
            pdf.cell(0, 7, line[:110], align="L", new_x="LMARGIN", new_y="NEXT")

    pdf.section("Recent dispenses")
    if dispenses:
        for d in dispenses[:30]:
            pat = d.patient.full_name if d.patient else "-"
            med = d.medication.name if d.medication else f"#{d.medication_id}"
            line = f"• {pat} — {med} × {d.quantity} — {(d.unit_price or 0):,.2f} SAR"
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, line[:110], align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, "No dispense operations.", align="L")
    return bytes(pdf.output())


def _payroll_report_en(entries, period_label: str) -> bytes:
    """English payroll report: period totals + entry details."""
    from datetime import datetime as _dt

    pdf = ArabicPDF("Payroll Report", lang="en")
    pdf.section(f"Period: {period_label}")
    pdf.kv_row("Issued at", _dt.now().strftime("%Y-%m-%d %H:%M"))
    pdf.kv_row("Entries count", len(entries))

    pdf.section("Totals (SAR)")
    pdf.kv_row("Total base salary", f"{sum(e.base_salary or 0 for e in entries):,.2f}")
    pdf.kv_row("Total allowances", f"{sum(e.bonus or 0 for e in entries):,.2f}")
    pdf.kv_row("Total deductions", f"{sum(e.deduction or 0 for e in entries):,.2f}")
    pdf.kv_row("Net total", f"{sum(e.net or 0 for e in entries):,.2f}")
    paid = sum(1 for e in entries
               if (e.status.value if hasattr(e.status, "value") else e.status) == "paid")
    pdf.kv_row("Paid / unpaid", f"{paid} / {len(entries) - paid}")

    pdf.section("Details")
    if entries:
        for e in entries[:40]:
            staff = e.staff.full_name if e.staff else f"#{e.staff_id}"
            key = e.status.value if hasattr(e.status, "value") else str(e.status)
            line = (f"• {e.period} — {staff} — Base {e.base_salary or 0:,.2f} — "
                    f"Net {e.net:,.2f} — "
                    f"{'Paid' if key == 'paid' else 'Unpaid'}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, line[:115], align="L", new_x="LMARGIN", new_y="NEXT")
        if len(entries) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, f"... and {len(entries) - 40} more entries (first 40 shown)",
                     align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, "No payroll entries.", align="L")
    return bytes(pdf.output())


def accounts_sales_pdf(entries, period_label: str, lang: str = "ar") -> bytes:
    """تقرير مبيعات PDF — بالعربية أو الإنجليزية."""
    if lang == "en":
        return _accounts_sales_en(entries, period_label)
    from datetime import datetime as _dt

    total_sales = sum(e.total_price for e in entries)
    total_paid = sum(e.paid_amount for e in entries)
    outstanding = total_sales - total_paid
    pdf = ArabicPDF(period_label, lang=lang)
    pdf.section("الملخص")
    pdf.kv_row("عدد العمليات", str(len(entries)))
    pdf.kv_row("الإجمالي", f"{total_sales:,.2f} ر.س")
    pdf.kv_row("المدفوع", f"{total_paid:,.2f} ر.س")
    pdf.kv_row("المتبقي", f"{outstanding:,.2f} ر.س")
    pdf.section(f"المبيعات ({len(entries)})")
    if entries:
        st_labels = {"UNPAID": "غير مدفوع", "PARTIAL": "مدفوع جزئيًا", "PAID": "مدفوع"}
        for e in entries[:40]:
            pat = e.patient.full_name if e.patient else f"#{e.patient_id}"
            med = e.medication.name if e.medication else f"#{e.medication_id}"
            line = (f"• #{e.id} {pat} — {med} — "
                    f"{e.quantity}×{e.unit_price:,.2f} — "
                    f"{st_labels.get(e.status, e.status)}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, ar(line[:120]), align="R",
                     new_x="LMARGIN", new_y="NEXT")
        if len(entries) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, ar(f"… و{len(entries)-40} عملية أخرى (أُعرضت أول 40)"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد مبيعات."), align="R")
    return bytes(pdf.output())


def _accounts_sales_en(entries, period_label: str) -> bytes:
    """English sales report: period totals + details."""
    from datetime import datetime as _dt

    total_sales = sum(e.total_price for e in entries)
    total_paid = sum(e.paid_amount for e in entries)
    outstanding = total_sales - total_paid
    pdf = ArabicPDF("Sales Report", lang="en")
    pdf.section(f"Period: {period_label}")
    pdf.kv_row("Issued at", _dt.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("Summary (SAR)")
    pdf.kv_row("Number of sales", str(len(entries)))
    pdf.kv_row("Total", f"{total_sales:,.2f}")
    pdf.kv_row("Paid", f"{total_paid:,.2f}")
    pdf.kv_row("Outstanding", f"{outstanding:,.2f}")

    pdf.section("Details")
    if entries:
        st_labels = {"UNPAID": "Unpaid", "PARTIAL": "Partial", "PAID": "Paid"}
        for e in entries[:40]:
            pat = e.patient.full_name if e.patient else f"#{e.patient_id}"
            med = e.medication.name if e.medication else f"#{e.medication_id}"
            line = (f"• #{e.id} {pat} — {med} — "
                    f"{e.quantity}×{e.unit_price:,.2f} — "
                    f"{st_labels.get(e.status, e.status)}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, line[:120], align="L",
                     new_x="LMARGIN", new_y="NEXT")
        if len(entries) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, f"... and {len(entries)-40} more (first 40 shown)",
                     align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, "No sales.", align="L")
    return bytes(pdf.output())


def patient_statement_pdf(patient, sales, invoices, totals: dict,
                          lang: str = "ar") -> bytes:
    """كشف حساب مريض PDF — مبيعات + فواتير + الأرصدة (عربي/إنجليزي)."""
    if lang == "en":
        return _patient_statement_en(patient, sales, invoices, totals)
    from datetime import datetime as _dt

    _st = {"UNPAID": "غير مدفوع", "PARTIAL": "مدفوع جزئيًا", "PAID": "مدفوع"}
    pdf = ArabicPDF("كشف حساب مريض")
    pdf.section("بيانات المريض")
    pdf.kv_row("الاسم", patient.full_name)
    pdf.kv_row("رقم الملف", f"#{patient.id}")
    pdf.kv_row("الجوال", patient.phone or "-")
    pdf.kv_row("تاريخ الإصدار", _dt.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("الأرصدة (ر.س)")
    pdf.kv_row("مبيعات الصيدلية", f"{totals['sales_total']:,.2f}")
    pdf.kv_row("مدفوع من المبيعات", f"{totals['sales_paid']:,.2f}")
    pdf.kv_row("إجمالي الفواتير", f"{totals['inv_total']:,.2f}")
    pdf.kv_row("مدفوع من الفواتير", f"{totals['inv_paid']:,.2f}")
    pdf.kv_row("إجمالي المستحقات", f"{totals['dues']:,.2f}")
    pdf.kv_row("الرصيد المستحق", f"{totals['outstanding']:,.2f}")

    pdf.section(f"مبيعات الصيدلية ({len(sales)})")
    if sales:
        for s in sales[:40]:
            med = s.medication.name if s.medication else f"#{s.medication_id}"
            line = (f"• #{s.id} {med} — {s.quantity}×{s.unit_price:,.2f} — "
                    f"{s.total_price:,.2f} — {_st.get(s.status, s.status)}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, ar(line[:120]), align="R",
                     new_x="LMARGIN", new_y="NEXT")
        if len(sales) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, ar(f"… و{len(sales)-40} عملية أخرى (أُعرضت أول 40)"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد مبيعات."), align="R")

    pdf.section(f"الفواتير ({len(invoices)})")
    if invoices:
        for i in invoices[:40]:
            st = i["status"] if isinstance(i, dict) else (
                i.status.value if hasattr(i.status, "value") else str(i.status))
            desc = (i["description"] if isinstance(i, dict) else i.description) or "-"
            total = i["total"] if isinstance(i, dict) else i.total
            paid = i["paid_amount"] if isinstance(i, dict) else float(i.paid_amount or 0)
            line = (f"• #{i['id'] if isinstance(i, dict) else i.id} {desc} — "
                    f"{float(total):,.2f} — مدفوع {float(paid):,.2f} — "
                    f"{_st.get(st, st)}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, ar(line[:120]), align="R",
                     new_x="LMARGIN", new_y="NEXT")
        if len(invoices) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, ar(f"… و{len(invoices)-40} فاتورة أخرى (أُعرضت أول 40)"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, ar("لا توجد فواتير."), align="R")
    return bytes(pdf.output())


def _patient_statement_en(patient, sales, invoices, totals: dict) -> bytes:
    """English patient statement PDF: balances + sales + invoices."""
    from datetime import datetime as _dt

    _st = {"UNPAID": "Unpaid", "PARTIAL": "Partial", "PAID": "Paid"}
    pdf = ArabicPDF("Patient Statement", lang="en")
    pdf.section("Patient")
    pdf.kv_row("Name", patient.full_name)
    pdf.kv_row("File no.", f"#{patient.id}")
    pdf.kv_row("Phone", patient.phone or "-")
    pdf.kv_row("Issued at", _dt.now().strftime("%Y-%m-%d %H:%M"))

    pdf.section("Balances (SAR)")
    pdf.kv_row("Pharmacy sales", f"{totals['sales_total']:,.2f}")
    pdf.kv_row("Sales paid", f"{totals['sales_paid']:,.2f}")
    pdf.kv_row("Invoices total", f"{totals['inv_total']:,.2f}")
    pdf.kv_row("Invoices paid", f"{totals['inv_paid']:,.2f}")
    pdf.kv_row("Total dues", f"{totals['dues']:,.2f}")
    pdf.kv_row("Outstanding", f"{totals['outstanding']:,.2f}")

    pdf.section(f"Pharmacy sales ({len(sales)})")
    if sales:
        for s in sales[:40]:
            med = s.medication.name if s.medication else f"#{s.medication_id}"
            line = (f"• #{s.id} {med} — {s.quantity}x{s.unit_price:,.2f} — "
                    f"{s.total_price:,.2f} — {_st.get(s.status, s.status)}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, line[:120], align="L",
                     new_x="LMARGIN", new_y="NEXT")
        if len(sales) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, f"... and {len(sales)-40} more (first 40 shown)",
                     align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, "No sales.", align="L")

    pdf.section(f"Invoices ({len(invoices)})")
    if invoices:
        for i in invoices[:40]:
            st = i["status"] if isinstance(i, dict) else (
                i.status.value if hasattr(i.status, "value") else str(i.status))
            desc = (i["description"] if isinstance(i, dict) else i.description) or "-"
            total = i["total"] if isinstance(i, dict) else i.total
            paid = i["paid_amount"] if isinstance(i, dict) else float(i.paid_amount or 0)
            line = (f"• #{i['id'] if isinstance(i, dict) else i.id} {desc} — "
                    f"{float(total):,.2f} — paid {float(paid):,.2f} — "
                    f"{_st.get(st, st)}")
            pdf.set_font("ar", "", 10)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, line[:120], align="L",
                     new_x="LMARGIN", new_y="NEXT")
        if len(invoices) > 40:
            pdf.set_font("ar", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 7, f"... and {len(invoices)-40} more (first 40 shown)",
                     align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("ar", "", 11)
        pdf.multi_cell(0, 7, "No invoices.", align="L")
    return bytes(pdf.output())
