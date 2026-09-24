"""طباعة الفاتورة كصفحة HTML جاهزة للطباعة (RTL عربي)."""

INVOICE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>فاتورة رقم {id}</title>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
  .invoice {{ background: #fff; max-width: 700px; margin: auto; padding: 32px; border: 1px solid #ddd; border-radius: 8px; }}
  .header {{ display: flex; justify-content: space-between; border-bottom: 3px solid #2c7be5; padding-bottom: 16px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0; color: #2c7be5; font-size: 24px; }}
  .meta {{ color: #555; font-size: 14px; line-height: 1.8; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  th, td {{ padding: 10px 12px; text-align: right; border-bottom: 1px solid #eee; }}
  th {{ background: #f0f6ff; color: #2c7be5; }}
  .total {{ font-size: 20px; font-weight: bold; color: #2c7be5; text-align: left; }}
  .status-paid {{ color: #28a745; font-weight: bold; }}
  .status-unpaid {{ color: #dc3545; font-weight: bold; }}
  .status-partial {{ color: #ffc107; font-weight: bold; }}
  .footer {{ margin-top: 30px; padding-top: 16px; border-top: 1px dashed #ccc; color: #888; font-size: 12px; text-align: center; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .invoice {{ border: none; }} }}
</style>
</head>
<body>
<div class="invoice">
  <div class="header">
    <div>
      <h1>🏥 نظام إدارة المستشفيات</h1>
      <div class="meta">فاتورة رقم: <strong>#{id}</strong></div>
    </div>
    <div class="meta" style="text-align:left">
      تاريخ الإصدار: {created_at}<br>
      الحالة: <span class="status-{status_class}">{status_label}</span>
    </div>
  </div>

  <div class="meta">
    <strong>المريض:</strong> {patient_name} (#{patient_id})<br>
    <strong>الوصف:</strong> {description}
  </div>

  <table>
    <thead>
      <tr><th>البيان</th><th>المبلغ</th></tr>
    </thead>
    <tbody>
      <tr><td>{description}</td><td>{amount} ر.س</td></tr>
{extra_rows}
    </tbody>
    <tfoot>
      <tr class="total"><td>الإجمالي</td><td class="total">{total} ر.س</td></tr>
{footer_rows}
    </tfoot>
  </table>

  <div class="footer">
    هذه الفاتورة صادرة إلكترونيًا من نظام إدارة المستشفيات والعيادات — تُعتبر صالحة دون توقيع.
  </div>
</div>
</body>
</html>"""

STATUS_LABELS = {
    "paid": "مدفوعة",
    "unpaid": "غير مدفوعة",
    "partial": "مدفوعة جزئيًا",
}


def render_invoice_html(invoice, patient_name: str) -> str:
    """توليد HTML للفاتورة من كائن Invoice واسم المريض."""
    status_value = invoice.status.value if hasattr(invoice.status, "value") else str(invoice.status)
    extra_rows = []
    footer_rows = []
    if invoice.discount:
        extra_rows.append(
            f'      <tr><td>الخصم</td><td>-{invoice.discount:,.2f} ر.س</td></tr>')
    if invoice.tax_rate:
        extra_rows.append(
            f'      <tr><td>الضريبة ({invoice.tax_rate:g}%)</td>'
            f'<td>{invoice.tax:,.2f} ر.س</td></tr>')
    if invoice.paid_amount:
        footer_rows.append(
            f'      <tr><td>المدفوع</td><td>{invoice.paid_amount:,.2f} ر.س</td></tr>')
        remaining = invoice.total - invoice.paid_amount
        if remaining > 0.005:
            footer_rows.append(
                f'      <tr><td>المتبقي</td><td>{remaining:,.2f} ر.س</td></tr>')
    return INVOICE_HTML_TEMPLATE.format(
        id=invoice.id,
        created_at=invoice.created_at.strftime("%Y-%m-%d %H:%M") if invoice.created_at else "",
        status_class=status_value,
        status_label=STATUS_LABELS.get(status_value, status_value),
        patient_name=patient_name,
        patient_id=invoice.patient_id,
        description=invoice.description or "-",
        amount=f"{invoice.amount:,.2f}",
        total=f"{invoice.total:,.2f}",
        extra_rows="\n".join(extra_rows),
        footer_rows="\n".join(footer_rows),
    )
