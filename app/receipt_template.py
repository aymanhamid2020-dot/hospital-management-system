"""قوالب HTML للطباعة: إيصال دفعة بيع وكشف حساب مريض (عربي/إنجليزي).

الشكل يأتي من `app/print_kit.py` — **نفس نظام التصميم** الذي يُولّد ملفات
PDF، فتبقى الهوية واحدة بين المستند المطبوع وملف الـ PDF. لا CSS خاص هنا.
"""
import html as _html
from datetime import datetime
from typing import Iterable, Optional

from app.print_kit import (
    foot_html, grid_html, head_html, ltr_html, page_html, sign_html, tiles_html,
)

_ST = {"PAID": ("مدفوع", "paid"), "PARTIAL": ("مدفوع جزئيًا", "partial"),
       "UNPAID": ("غير مدفوع", "unpaid")}
_ST_EN = {"PAID": ("Paid", "paid"), "PARTIAL": ("Partially paid", "partial"),
          "UNPAID": ("Unpaid", "unpaid")}
_PM = {"cash": "نقدًا", "card": "بطاقة", "insurance": "تأمين"}
_PM_EN = {"cash": "Cash", "card": "Card", "insurance": "Insurance"}


def L(en: bool, ar: str, en_lb: str) -> str:
    """اختيار تسمية حسب اللغة: `en=True` → الإنجليزية، `en=False` → العربية.

    preferable لما كان يُكتب `("البيان", "Item")[en]` مباشرةً: الأول جزءً من
    شرط يُنتج نصًا (لا tuple) فيقصّ تُقصّ إلى حرف واحد عند الفهرسة.
    """
    return en_lb if en else ar


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _money(v) -> str:
    return f"{float(v or 0):,.2f}"


def _badge(status: str, lang: str) -> str:
    table = _ST_EN if lang == "en" else _ST
    label, cls = table.get(status, (status, "unpaid"))
    return f'<span class="badge {cls}">{_e(label)}</span>'


def _sec(title: str) -> str:
    return f'<div class="pk-section">{_e(title)}</div>'


def _rows_table(headers, rows, empty_text: str) -> str:
    """جدول نظيف مع صف فارغ بديل — بنمط `pk-` الموحّد."""
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = rows or (f'<tr><td colspan="{len(headers)}" style="text-align:center;'
                    f'color:var(--muted);padding:14px">{_e(empty_text)}</td></tr>')
    return (f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")



# ==================== إيصال دفعة ====================
def sale_receipt_html(d, lang: str = "ar") -> str:
    """إيصال طباعة لعملية صرف/بيع واحدة — بنظام التصميم الموحّد."""
    en = lang == "en"
    sar = "SAR" if en else "ر.س"
    patient = d.patient.full_name if d.patient else f"#{d.patient_id}"
    med = d.medication.name if d.medication else f"#{d.medication_id}"
    rest = round(float(d.total_price or 0) - float(d.paid_amount or 0), 2)
    title = "Payment receipt" if en else "إيصال دفعة"
    kind = "Sales receipt" if en else "إيصال بيع"
    pm = (_PM_EN if en else _PM).get(d.payment_method, d.payment_method)

    fields = [
        (("المريض", "Patient")[en], patient),
        (("الدواء", "Medicine")[en], med),
        (("الكمية", "Quantity")[en], d.quantity),
        (("سعر الوحدة", "Unit price")[en], f"{_money(d.unit_price)} {sar}"),
        (("طريقة الدفع", "Payment method")[en], pm),
        (("صرفه", "Dispensed by")[en], d.dispensed_by or "-"),
    ]
    for attr, ar_lb, en_lb in (("dosage", "الجرعة", "Dosage"),
                               ("frequency", "التكرار", "Frequency"),
                               ("duration", "المدة", "Duration"),
                               ("instructions", "تعليمات", "Instructions")):
        val = getattr(d, attr, None)
        if val:
            fields.append((ar_lb if not en else en_lb, val))
    if getattr(d, "returned_at", None) is not None:
        reason = getattr(d, "return_reason", None) or "-"
        fields.append((("مرتجع", "Returned")[en],
                       ("نعم — " if not en else "Yes — ") + str(reason)))

    date = d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "-"
    l_total = ("الإجمالي", "Total")[en]
    l_paid = ("المدفوع", "Paid")[en]
    l_rest = ("المتبقي", "Outstanding")[en]
    totals_rows = (
        f'<tr><td>{_e(l_total)}</td>'
        f'<td style="text-align:end">{_money(d.total_price)} {sar}</td></tr>'
        f'<tr><td>{_e(l_paid)}</td>'
        f'<td style="text-align:end;color:var(--ok)">'
        f'{_money(d.paid_amount)} {sar}</td></tr>'
        f'<tr><td><b>{_e(l_rest)}</b></td>'
        f'<td style="text-align:end"><b>{_money(rest)} {sar}</b></td></tr>')

    body = f"""
{head_html(title, lang, kind=kind, number=f"#{d.id}",
           subtitle_html=f'{ltr_html(date)} &nbsp;·&nbsp; {_badge(d.status, lang)}')}
<div class="pk-body">
  {_sec("بيانات العملية" if not en else "Transaction")}
  {grid_html(fields, cols=2)}
  {_sec("الملخص المالي" if not en else "Financial summary")}
  {tiles_html([(l_total, f"{_money(d.total_price)} {sar}"),
               (l_paid, f"{_money(d.paid_amount)} {sar}",
                "ok" if rest <= 0 else ""),
               (l_rest, f"{_money(rest)} {sar}", "" if rest <= 0 else "warn")])}
  {_rows_table([L(en, "البيان", "Item"), l_total], totals_rows, "")}
</div>
{sign_html("توقيع المستلم" if not en else "Received by",
           "توقيع المحاسب" if not en else "Cashier")}
{foot_html(("حالة السداد: " + ("مسدَّد بالكامل" if rest <= 0 else "يوجد متبقٍ"))
            if not en else ("Settlement: " + ("Settled" if rest <= 0
                                              else "Outstanding")), lang)}
"""
    return page_html(f"{title} #{d.id}", body, lang)



# ==================== كشف حساب مريض ====================
def patient_statement_html(patient, sales: Iterable, invoices: Iterable,
                           totals: dict, lang: str = "ar") -> str:
    """كشف حساب مريض: مبيعات الصيدلية + الفواتير + الأرصدة."""
    en = lang == "en"
    sar = "SAR" if en else "ر.س"
    title = "Patient statement" if en else "كشف حساب مريض"
    kind = "Statement" if en else "كشف حساب"
    pm = _PM_EN if en else _PM
    st = _ST_EN if en else _ST

    fields = [
        (("المريض", "Patient")[en], patient.full_name),
        (("رقم الملف", "File #")[en], f"#{patient.id}"),
        (("الجوال", "Phone")[en], patient.phone or "-"),
        (("تاريخ الميلاد", "Date of birth")[en],
         patient.date_of_birth.strftime("%Y-%m-%d") if patient.date_of_birth else "-"),
    ]
    if getattr(patient, "national_id", None):
        fields.append((("الرقم الوطني", "National ID")[en], patient.national_id))
    if getattr(patient, "insurer", None):
        fields.append((("شركة التأمين", "Insurer")[en], patient.insurer))

    sales = list(sales)
    sales_rows = "".join(
        f"<tr><td>#{s.id}</td>"
        f"<td>{_e(s.created_at.strftime('%Y-%m-%d') if s.created_at else '-')}</td>"
        f"<td>{_e(s.medication.name if s.medication else '#' + str(s.medication_id))}</td>"
        f"<td>{s.quantity}</td>"
        f"<td style='text-align:end'>{_money(s.total_price)}</td>"
        f"<td style='text-align:end;color:var(--ok)'>{_money(s.paid_amount)}</td>"
        f"<td style='text-align:end'>{_money(round(float(s.total_price or 0) - float(s.paid_amount or 0), 2))}</td>"
        f"<td>{_e(pm.get(s.payment_method, s.payment_method))}</td>"
        f"<td>{_badge(s.status, lang)}</td></tr>"
        for s in sales)
    sales_block = (_sec(f"أدوية الصيدلية ({len(sales)})" if not en
                         else f"Pharmacy sales ({len(sales)})")
                   + _rows_table(["#", "التاريخ" if not en else "Date",
                                  "الدواء" if not en else "Medicine",
                                  "الكمية" if not en else "Qty",
                                  "الإجمالي" if not en else "Total",
                                  "المدفوع" if not en else "Paid",
                                  "المتبقي" if not en else "Rest",
                                  "الطريقة" if not en else "Method",
                                  "الحالة" if not en else "Status"],
                                 sales_rows, "لا توجد حركات" if not en
                                 else "No transactions"))

    invoices = list(invoices)
    inv_rows = "".join(
        f"<tr><td>#{i.id}</td>"
        f"<td>{_e(i.created_at.strftime('%Y-%m-%d') if i.created_at else '-')}</td>"
        f"<td>{_e(i.description or '-')}</td>"
        f"<td style='text-align:end'>{_money(i.total)}</td>"
        f"<td style='text-align:end;color:var(--ok)'>{_money(i.paid_amount)}</td>"
        f"<td>{_e(pm.get(i.payment_method or '', i.payment_method or '-'))}</td>"
        f"<td>{_e(str(i.status.value if hasattr(i.status, 'value') else i.status)).upper()}</td></tr>"
        for i in invoices)
    inv_block = (_sec(f"الفواتير الطبية ({len(invoices)})" if not en
                      else f"Medical invoices ({len(invoices)})")
                 + _rows_table(["#", "التاريخ" if not en else "Date",
                                "البيان" if not en else "Description",
                                "الإجمالي" if not en else "Total",
                                "المدفوع" if not en else "Paid",
                                "الطريقة" if not en else "Method",
                                "الحالة" if not en else "Status"],
                               inv_rows, "لا توجد فواتير" if not en
                               else "No invoices"))

    outstanding = float(totals.get("outstanding", 0) or 0)
    tiles = [
        (("إجمالي المستحقات", "Total dues")[en], f"{_money(totals.get('dues'))} {sar}"),
        (("المحصَّل", "Collected")[en],
         f"{_money(float(totals.get('sales_paid') or 0) + float(totals.get('inv_paid') or 0))} {sar}",
         "ok"),
        (("الرصيد المستحق", "Outstanding")[en], f"{_money(outstanding)} {sar}",
         "ok" if outstanding <= 0 else "danger"),
    ]
    summary_rows = "".join(
        f"<tr><td>{_e(lbl)}</td><td style='text-align:end'>{_money(val)} {sar}</td></tr>"
        for lbl, val in ((("مبيعات الصيدلية", "Pharmacy sales")[en],
                          totals.get("sales_total")),
                         (("مدفوع من المبيعات", "Sales paid")[en],
                          totals.get("sales_paid")),
                         (("إجمالي الفواتير", "Invoices total")[en],
                          totals.get("inv_total")),
                         (("مدفوع من الفواتير", "Invoices paid")[en],
                          totals.get("inv_paid"))))

    body = f"""
{head_html(title, lang, kind=kind, number=f"#{patient.id}",
           subtitle=patient.full_name)}
<div class="pk-body">
  {_sec("بيانات المريض" if not en else "Patient")}
  {grid_html(fields, cols=2)}
  {_sec("الملخص المالي" if not en else "Financial summary")}
  {tiles_html(tiles)}
  {_rows_table([L(en, "البيان", "Item"),
                L(en, "المبلغ", "Amount")], summary_rows, "")}
  {sales_block}
  {inv_block}
</div>
{sign_html("توقيع المريض" if not en else "Patient signature",
           "المحاسب" if not en else "Accountant")}
{foot_html(("الرصيد المستحق: " + _money(outstanding) + " " + sar) if not en
            else ("Outstanding: " + _money(outstanding) + " " + sar), lang)}
"""
    return page_html(f"{title} — {patient.full_name}", body, lang)
