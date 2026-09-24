"""قوالب HTML للطباعة: إيصال دفعة بيع وكشف حساب مريض (عربي/إنجليزي)."""
import html as _html
from datetime import datetime
from typing import Iterable, Optional

_CSS = """
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', Tahoma, Arial, sans-serif; margin: 0;
         padding: 24px; background: #f4f6fb; color: #222; }
  .sheet { background: #fff; max-width: 820px; margin: auto; padding: 28px;
           border-radius: 14px; box-shadow: 0 8px 30px rgba(0,0,0,.10); }
  h1 { margin: 0 0 4px; font-size: 22px; color: #2c7be5; text-align: center; }
  .sub { text-align: center; color: #777; font-size: 13px; margin-bottom: 18px; }
  .kv { display: flex; justify-content: space-between; padding: 7px 10px;
        border-bottom: 1px dashed #e3e7ef; font-size: 14px; }
  .kv b { color: #2c7be5; }
  h2 { font-size: 15px; margin: 22px 0 8px; color: #2c7be5;
       background: #eef4ff; border: 1px solid #d7e4ff; padding: 7px 10px;
       border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 7px 8px; border-bottom: 1px solid #eceff5; text-align: right; }
  th { background: #f7f9ff; color: #444; font-weight: 700; }
  tfoot td { font-weight: 700; background: #fbfcff; }
  .total { display: flex; justify-content: space-between; font-size: 15px;
           padding: 9px 10px; margin-top: 8px; border-radius: 8px;
           background: #eef4ff; font-weight: 700; }
  .ok { color: #28a745; } .bad { color: #dc3545; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 999px;
           font-size: 12px; font-weight: 700; }
  .badge.paid { background: #e6f7ec; color: #1e7e34; }
  .badge.partial { background: #fff4d6; color: #a06a00; }
  .badge.unpaid { background: #ffe8e8; color: #b02a37; }
  .sign { display: flex; justify-content: space-between; margin-top: 34px;
          font-size: 13px; color: #555; }
  .sign div { width: 45%; border-top: 1px solid #999; padding-top: 6px;
              text-align: center; }
  .foot { text-align: center; font-size: 11px; color: #999; margin-top: 22px; }
  .actions { text-align: center; margin-top: 18px; }
  .actions button { background: #2c7be5; color: #fff; border: 0; padding: 10px 26px;
                    border-radius: 8px; font-size: 14px; cursor: pointer; }
  @media print {
    body { background: #fff; padding: 0; }
    .sheet { box-shadow: none; border-radius: 0; padding: 0; max-width: 100%; }
    .actions { display: none; }
  }
"""

_ST = {"PAID": ("مدفوع", "paid"), "PARTIAL": ("مدفوع جزئيًا", "partial"),
       "UNPAID": ("غير مدفوع", "unpaid")}
_ST_EN = {"PAID": ("Paid", "paid"), "PARTIAL": ("Partially paid", "partial"),
          "UNPAID": ("Unpaid", "unpaid")}
_PM = {"cash": "نقدًا", "card": "بطاقة", "insurance": "تأمين"}
_PM_EN = {"cash": "Cash", "card": "Card", "insurance": "Insurance"}


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _money(v) -> str:
    return f"{float(v or 0):,.2f}"


def _page(title: str, body: str, lang: str = "ar") -> str:
    """غلاف HTML كامل + زر الطباعة."""
    rtl = "rtl" if lang == "ar" else "ltr"
    btn = "🖨️ طباعة" if lang == "ar" else "🖨️ Print"
    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{rtl}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="sheet">
{body}
<div class="actions"><button onclick="window.print()">{btn}</button></div>
</div>
</body>
</html>"""


def _head(title: str, sub: str) -> str:
    return f"<h1>{_e(title)}</h1><div class=\"sub\">{_e(sub)}</div>"


def _badge(status: str, lang: str) -> str:
    table = _ST_EN if lang == "en" else _ST
    label, cls = table.get(status, (status, "unpaid"))
    return f'<span class="badge {cls}">{_e(label)}</span>'


def _kv(label: str, value, lang: str = "ar") -> str:
    return (f'<div class="kv"><span>{_e(label)}</span>'
            f"<b>{value if isinstance(value, str) and value.startswith(('<',)) else _e(value)}</b></div>")


# ==================== إيصال دفعة ====================
def sale_receipt_html(d, lang: str = "ar") -> str:
    """إيصال طباعة لعملية صرف/بيع واحدة."""
    en = lang == "en"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    patient = d.patient.full_name if d.patient else f"#{d.patient_id}"
    med = d.medication.name if d.medication else f"#{d.medication_id}"
    rest = round(float(d.total_price or 0) - float(d.paid_amount or 0), 2)
    title = "إيصال دفعة" if not en else "Payment receipt"
    sub = ("نظام إدارة المستشفيات والعيادات"
           if not en else "Hospital & Clinics Management System")
    pm = (_PM_EN if en else _PM).get(d.payment_method, d.payment_method)
    # حقول توجيه الاستخدام (إن وُجدت) + تنبيه الإرجاع
    usage = []
    for attr, ar, en_lb in (("dosage", "الجرعة", "Dosage"),
                            ("frequency", "التكرار", "Frequency"),
                            ("duration", "المدة", "Duration"),
                            ("instructions", "تعليمات", "Instructions")):
        val = getattr(d, attr, None)
        if val:
            usage.append(_kv(ar if not en else en_lb, val, lang))
    returned_row = ""
    if getattr(d, "returned_at", None) is not None:
        reason = getattr(d, "return_reason", None) or "-"
        returned_row = _kv(
            "مرتجع" if not en else "Returned",
            f'<span class="badge unpaid">{"نعم — " if not en else "Yes — "}{_e(reason)}</span>',
            lang,
        )
    rows = "".join([
        _kv("رقم الإيصال" if not en else "Receipt #", f"#{d.id}", lang),
        _kv("التاريخ" if not en else "Date",
            d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "-", lang),
        _kv("المريض" if not en else "Patient", patient, lang),
        _kv("الدواء" if not en else "Medicine", med, lang),
        _kv("الكمية" if not en else "Quantity", d.quantity, lang),
        _kv("سعر الوحدة" if not en else "Unit price",
            f"{_money(d.unit_price)} SAR" if en else f"{_money(d.unit_price)} ر.س", lang),
        *usage,
        _kv("طريقة الدفع" if not en else "Payment method", pm, lang),
        _kv("صرفه" if not en else "Dispensed by", d.dispensed_by or "-", lang),
        _kv("الحالة" if not en else "Status", _badge(d.status, lang), lang),
        returned_row,
    ])
    body = f"""
{_head(title, sub)}
{rows}
<div class="total"><span>{'الإجمالي' if not en else 'Total'}</span>
  <span>{_money(d.total_price)} {'SAR' if en else 'ر.س'}</span></div>
<div class="total"><span>{'المدفوع' if not en else 'Paid'}</span>
  <span class="ok">{_money(d.paid_amount)} {'SAR' if en else 'ر.س'}</span></div>
<div class="total"><span>{'المتبقي' if not en else 'Outstanding'}</span>
  <span class="{'ok' if rest <= 0 else 'bad'}">{_money(rest)} {'SAR' if en else 'ر.س'}</span></div>
{('<div class="kv"><span>' + ('تاريخ التسديد' if not en else 'Paid at') + '</span><b>' +
  (d.paid_at.strftime('%Y-%m-%d %H:%M') if d.paid_at else '-') + '</b></div>') if d.paid_at else ''}
<div class="sign">
  <div>{'توقيع المستلم' if not en else 'Received by'}</div>
  <div>{'توقيع المحاسب' if not en else 'Cashier signature'}</div>
</div>
<div class="foot">{_e(sub)} — {_e(now)}</div>
"""
    return _page(f"{title} #{d.id}", body, lang)


# ==================== كشف حساب مريض ====================
def patient_statement_html(patient, sales: Iterable, invoices: Iterable,
                           totals: dict, lang: str = "ar") -> str:
    """كشف حساب مريض: مبيعات الصيدلية + الفواتير + الأرصدة."""
    en = lang == "en"
    title = "كشف حساب مريض" if not en else "Patient statement"
    sub = ("نظام إدارة المستشفيات والعيادات"
           if not en else "Hospital & Clinics Management System")
    head = "".join([
        _kv("المريض" if not en else "Patient", patient.full_name, lang),
        _kv("رقم الملف" if not en else "File #", f"#{patient.id}", lang),
        _kv("الجوال" if not en else "Phone", patient.phone or "-", lang),
        _kv("تاريخ الميلاد" if not en else "Date of birth",
            patient.date_of_birth.strftime("%Y-%m-%d") if patient.date_of_birth else "-", lang),
        _kv("تاريخ الإصدار" if not en else "Issued",
            datetime.now().strftime("%Y-%m-%d %H:%M"), lang),
    ])

    sales = list(sales)
    pm = _PM_EN if en else _PM
    st = _ST_EN if en else _ST
    sales_rows = "".join(
        f"<tr><td>#{s.id}</td>"
        f"<td>{_e(s.created_at.strftime('%Y-%m-%d') if s.created_at else '-')}</td>"
        f"<td>{_e(s.medication.name if s.medication else '#' + str(s.medication_id))}</td>"
        f"<td>{s.quantity}</td>"
        f"<td>{_money(s.total_price)}</td>"
        f"<td class='ok'>{_money(s.paid_amount)}</td>"
        f"<td class='{'ok' if s.status == 'PAID' else 'bad'}'>"
        f"{_money(round(float(s.total_price or 0) - float(s.paid_amount or 0), 2))}</td>"
        f"<td>{_e(pm.get(s.payment_method, s.payment_method))}</td>"
        f"<td>{_e(st.get(s.status, (s.status,))[0])}</td></tr>"
        for s in sales)
    sales_block = f"""
<h2>{'أدوية الصيدلية' if not en else 'Pharmacy sales'} ({len(sales)})</h2>
<table>
<thead><tr><th>{'#' if not en else '#'}</th><th>{'التاريخ' if not en else 'Date'}</th>
<th>{'الدواء' if not en else 'Medicine'}</th><th>{'الكمية' if not en else 'Qty'}</th>
<th>{'الإجمالي' if not en else 'Total'}</th><th>{'المدفوع' if not en else 'Paid'}</th>
<th>{'المتبقي' if not en else 'Rest'}</th><th>{'الطريقة' if not en else 'Method'}</th>
<th>{'الحالة' if not en else 'Status'}</th></tr></thead>
<tbody>{sales_rows or '<tr><td colspan="9" style="text-align:center;color:#999">'
        + ('لا توجد حركات' if not en else 'No transactions') + '</td></tr>'}</tbody>
</table>"""

    invoices = list(invoices)
    inv_rows = "".join(
        f"<tr><td>#{i.id}</td>"
        f"<td>{_e(i.created_at.strftime('%Y-%m-%d') if i.created_at else '-')}</td>"
        f"<td>{_e(i.description or '-')}</td>"
        f"<td>{_money(i.total)}</td>"
        f"<td class='ok'>{_money(i.paid_amount)}</td>"
        f"<td>{_e(pm.get(i.payment_method or '', i.payment_method or '-'))}</td>"
        f"<td>{_e(str(i.status.value if hasattr(i.status, 'value') else i.status)).upper()}</td></tr>"
        for i in invoices)
    inv_block = f"""
<h2>{'الفواتير الطبية' if not en else 'Medical invoices'} ({len(invoices)})</h2>
<table>
<thead><tr><th>{'#' if not en else '#'}</th><th>{'التاريخ' if not en else 'Date'}</th>
<th>{'البيان' if not en else 'Description'}</th><th>{'الإجمالي' if not en else 'Total'}</th>
<th>{'المدفوع' if not en else 'Paid'}</th><th>{'الطريقة' if not en else 'Method'}</th>
<th>{'الحالة' if not en else 'Status'}</th></tr></thead>
<tbody>{inv_rows or '<tr><td colspan="7" style="text-align:center;color:#999">'
        + ('لا توجد فواتير' if not en else 'No invoices') + '</td></tr>'}</tbody>
</table>"""

    sar = "SAR" if en else "ر.س"
    body = f"""
{_head(title, sub)}
{head}
<h2>{'الملخص المالي' if not en else 'Financial summary'}</h2>
{_kv('مبيعات الصيدلية' if not en else 'Pharmacy sales', f"{_money(totals['sales_total'])} {sar}", lang)}
{_kv('مدفوع من المبيعات' if not en else 'Sales paid', f"{_money(totals['sales_paid'])} {sar}", lang)}
{_kv('إجمالي الفواتير' if not en else 'Invoices total', f"{_money(totals['inv_total'])} {sar}", lang)}
{_kv('مدفوع من الفواتير' if not en else 'Invoices paid', f"{_money(totals['inv_paid'])} {sar}", lang)}
<div class="total"><span>{'إجمالي المستحقات' if not en else 'Total dues'}</span>
  <span>{_money(totals['dues'])} {sar}</span></div>
<div class="total"><span>{'الرصيد المستحق' if not en else 'Outstanding balance'}</span>
  <span class="{'ok' if totals['outstanding'] <= 0 else 'bad'}">
    {_money(totals['outstanding'])} {sar}</span></div>
{sales_block}
{inv_block}
<div class="sign">
  <div>{'توقيع المريض' if not en else 'Patient signature'}</div>
  <div>{'المحاسب' if not en else 'Accountant'}</div>
</div>
<div class="foot">{_e(sub)}</div>
"""
    return _page(f"{title} — {patient.full_name}", body, lang)
