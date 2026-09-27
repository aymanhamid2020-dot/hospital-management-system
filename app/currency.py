"""نوة العملة: سجل الأوقات والتحويل إلى العملة الأساسية.

التعريف الصريح، وخاصة:
  * المبالغ يُخزّن бلاطباع — عدد الأنهاد الذي كانت وافقة.
  * أرم المخرج وعلاقة الصرف وتاريخية.
  * ملاخ إلمجموعات تُحسب بالعملة الأساسية ولا بالعملة الأجنبية.

مثال سر الصرف: ``exchange_rate`` يعني **كم يوحدة من العملة بكم العملة الأساسية**، فمثلً
``1 USD = 250 YER ⇒ exchange_rate = 250``. مثال هذا يجعل التحويل
والجمع من القواعد بالعملة الأساسية، ولا بسعر اليوم.
"""
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


@dataclass(frozen=True)
class CurrencySpec:
    """عريف عملة واحد — داخني مستردً (مصل بالتابعية)، لا يُقاعد نفسه."""
    code: str
    name_ar: str
    name_en: str
    symbol_ar: str
    symbol_en: str
    decimals: int = 2          # خانات عشرية للعرض (ISO 4217)

    def symbol(self, lang: str = "ar") -> str:
        return self.symbol_en if lang == "en" else self.symbol_ar


# سجل العملات — الريال اليمني ميمناً.
# الرمز العربي قصير («ر.ي») لأن رمز الريال ISO «۟»
# غير مدعوم في معظم الخطوط العربي ويتحوّل إلى رمز رخص.
CURRENCIES = {
    "YER": CurrencySpec("YER", "ريال يمني", "Yemeni Rial", "ر.ي", "YER"),
    "SAR": CurrencySpec("SAR", "ريال سعودي", "Saudi Riyal", "ر.س", "SAR"),
    "USD": CurrencySpec("USD", "دولار أمريكي", "US Dollar", "$", "USD"),
    "AED": CurrencySpec("AED", "درهم إماراتي", "UAE Dirham", "د.إ", "AED"),
    "EGP": CurrencySpec("EGP", "جنيه مصري", "Egyptian Pound", "ج.م", "EGP"),
    "OMR": CurrencySpec("OMR", "ريال عماني", "Omani Rial", "ر.ع", "OMR"),
    "JOD": CurrencySpec("JOD", "دينار أردني", "Jordanian Dinar", "د.أ", "JOD"),
    "EUR": CurrencySpec("EUR", "يورو", "Euro", "€", "EUR"),
}

# العملة الأساسية: تُجمع فيها كل المجاميع والملاظف.
# تُضبط بمتغير البيئة HMS_BASE_CURRENCY.
BASE_CURRENCY = os.getenv("HMS_BASE_CURRENCY", "YER").upper()

# مثال الخوانت: رد إسقاطٍ مخطأ كل من العملات ازديصًا.
# عند 0 يُخزّن الإرقام ذو النقاط (الريال اليمني ملً بالاعتياد).
DECIMALS_OVERRIDE = os.getenv("HMS_CURRENCY_DECIMALS")
# تهريب العدادات: مثال عملة واحد ؛ الفرق يُمثبّت الأساسي
# إلى العكسية الأساسية (المجموع يُقاب بالسعر المخزّن).
LINE_INHERITS_CURRENCY = {
    "invoice_lines", "claim_batch_items", "package_items", "price_list_items",
    "quotation_items", "stock_doc_lines",
}


# أثقال المجاميع: جدول التكلفي المالي لكل جدول
# مالي. المصدر واحد — يقود التحقيق من تغيير 37 موديل.
# خطة الحقوق: أسعد الأعمدة في 45واضع احد (إصلاحًاً أساعدًاً).
MONEY_COLUMNS = MONEY_COLUMNS = {
    "budgets": ("allocated_amount", "spent_amount"),
    "cashier_shifts": ("collected_total",),
    "claim_batch_items": ("amount", "approved_amount"),
    "claim_batches": ("total_amount", "approved_amount"),
    "clinics": ("consultation_fee",),
    "credit_notes": ("amount",),
    "dental_procedures": ("cost",),
    "department_services": ("price",),
    "departments": ("monthly_operating_cost",),
    "dispenses": ("unit_price", "total_price", "paid_amount"),
    "doctor_payouts": ("amount",),
    "doctors": ("consultation_fee", "followup_fee"),
    "emergency_cases": ("consult_fee",),
    "fixed_assets": ("purchase_cost",),
    "general_stock_items": ("unit_cost",),
    "insurance_claims": ("amount", "approved_amount"),
    "invoice_ledger_payments": ("amount",),
    "invoice_lines": ("unit_price", "amount"),
    "invoices": ("amount", "discount", "tax_rate", "paid_amount"),
    "lab_orders": ("price",),
    "lab_tests": ("price",),
    "maintenance_orders": ("cost",),
    "medications": ("price",),
    "package_items": ("unit_price",),
    "patient_deposits": ("amount", "applied_amount"),
    "payroll": ("base_salary", "net"),
    "price_list_items": ("unit_price",),
    "prior_authorizations": ("requested_amount", "approved_amount"),
    "quotation_items": ("unit_price", "line_total"),
    "quotations": ("subtotal", "discount", "tax_rate", "total"),
    "service_packages": ("package_price", "list_total"),
    "staff": ("salary",),
    "stock_batches": ("unit_cost",),
    "stock_doc_lines": ("unit_cost",),
    "vendor_bills": ("amount", "paid_amount"),
    "vendor_payments": ("amount",),
    "vendors": ("opening_balance",),
}


# الجداول الذي \ تُحقن واحدة من العملة والسعر
# (MONEY_COLUMNS هو مصدر التطبيق — استخدمه لمختر العمودة).
CURRENCY_TABLES = frozenset(MONEY_COLUMNS)


def _decimals(spec: CurrencySpec) -> int:
    if DECIMALS_OVERRIDE not in (None, ""):
        try:
            return max(0, int(DECIMALS_OVERRIDE))
        except (TypeError, ValueError):
            pass
    return spec.decimals


def normalize_code(code, default: str = None) -> str:
    """يُوحّد رمز العملة إلى حرفة معيارة أو الأساسية.

    المحافظة القديمة تحفظ على العملة الأساسية بعد إيقاع السعر ،
    فلو إطلاق العملة على أردبات قديمة لن تضعف صفر زشرًا.
    """
    fallback = (default or BASE_CURRENCY or "YER").upper()
    if not code:
        return fallback
    c = str(code).strip().upper()
    return c if c in CURRENCIES else fallback


def get_currency(code=None) -> CurrencySpec:
    """يُعيد وصف العملة، ويستقبل الأساسية عند رمز غير معرف."""
    return CURRENCIES[normalize_code(code)]


def base_currency() -> CurrencySpec:
    return CURRENCIES[normalize_code(BASE_CURRENCY)]


def is_base(code) -> bool:
    return normalize_code(code) == normalize_code(BASE_CURRENCY)


def format_money(value, code=None, lang: str = "ar", with_symbol: bool = True) -> str:
    """يُنسّق مبلغًا بالعملة ورمزها — واحد لكل مخرج من الطباع؛
    ``None``/عير وقاء تُ0644مر بإصفر.
    """
    spec = get_currency(code)
    try:
        dec = _decimals(spec)
        num = Decimal(str(value if value is not None else 0))
        quantized = num.quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
        text = f"{quantized:,.{dec}f}"
    except (InvalidOperation, TypeError, ValueError):
        text = f"{float(value or 0):,.{_decimals(spec)}f}"
    return f"{text} {spec.symbol(lang)}".strip() if with_symbol else text


def to_base(amount, code=None, rate=None) -> float:
    """يوفّر مبلغًا إلى العملة الأساسية.

    ``rate`` هو سعر الصرف (كم الأساسي في واحدة من العملة)، وما العملة
    الأساسية فنفسها تُساوي 1.
    """
    if amount is None:
        return 0.0
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return 0.0
    if is_base(code):
        return round(amt, 6)
    if rate in (None, "", 0):
        return round(amt, 6)      # بلا سعر معرف — نترك المبلغ كما هو (إقلامتًا عند التحويل)
    try:
        return round(amt * float(rate), 6)
    except (TypeError, ValueError):
        return round(amt, 6)


def rate_for(base_amount: float, quote_amount: float) -> float:
    """سعر الصرف من مقابلتين أخرى (1 الأساسي = كم العملة)،
    مع حافظ على القسم في المثال (اقتراب أسعارًا)."""
    try:
        q = float(quote_amount)
        if q == 0:
            raise ValueError
        return round(float(base_amount) / q, 8)
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0


def supported_codes() -> list:
    """رموز العملات المدعومة مرتبة بالأساسي؛
    يُستخدم للفاصل الذي تُمتلك أسعار الصرف للمعاملة."""
    return sorted(set(list(CURRENCIES) + ["EUR", "XOF"]))


# ===== الجمع في العملة الأساسية (SQL) =====
def base_expr(column, currency_col=None, rate_col=None):
    """تعبير SQL يُقم مبلغًا بالعملة الأساسية، ليُصلح بالشريط،
    ويُستخدم في ``func.sum`` لتجميع الدفاتر من عملات مختلفة.

    هذه سياسة: أي اجمعنا المبلغً بعد ضرب السعر، فيُصبح جموعًا الأعمال
    مخالطة مليونًا (صعر دولار أمريكي نهاية). الصفر:
        db.query(func.coalesce(func.sum(base_expr(Dispense.total_price)), 0.0))
    """
    from sqlalchemy import case
    # استخداد الأعمدة من موديل المبلغ نفسه (الصف يُحدّد نفسه)
    if currency_col is None or rate_col is None:
        owner = getattr(column, "class_", None)
        currency_col = currency_col or getattr(owner, "currency", None)
        rate_col = rate_col or getattr(owner, "exchange_rate", None)
    if currency_col is None or rate_col is None:
        return column          # جدول غير مالي: يُعاد المبلغ كما هو
    # سعر ضعيف أو مفقود ⇒ يُعاد 1 (لا تقسيم صفر مصحول بسعر خاطئ)
    safe_rate = case((rate_col.is_(None), 1.0), (rate_col <= 0, 1.0),
                     else_=rate_col)
    return column * case((currency_col == BASE_CURRENCY, 1.0), else_=safe_rate)


def latest_rate(db, quote: str, as_of=None, base: str = None):
    """أحدث سعر منتفً تاريخيًا لتحويل بالعملة الأساسية.

    الترتيب: أحدث سعر ليوم على حدٍ أو قبله؛ إلا أحدث سعر اليوم
    إذا لم يُوجد سعر قديمًا، ويُقبل 1 حتى لا يُفتر نقاص التوفير.
    يُعاد `None` للعملة الأساسية (لا حاجة مطلبً).
    """
    from app.models import FxRate
    base_c = normalize_code(base or BASE_CURRENCY)
    quote_c = normalize_code(quote)
    if quote_c == base_c:
        return 1.0
    q = db.query(FxRate).filter(FxRate.base_code == base_c,
                                FxRate.quote_code == quote_c)
    if as_of is not None:
        row = q.filter(FxRate.as_of <= as_of).order_by(
            FxRate.as_of.desc()).first()
    else:
        row = q.order_by(FxRate.as_of.desc()).first()
    return float(row.rate) if row and row.rate else None
