"""اختبارات العملات المتعددة: التنسيق، التحويل، أسعار الصرف، والترحيل."""
from datetime import datetime, timedelta

import pytest

from app.currency import (
    BASE_CURRENCY, CURRENCIES, CURRENCY_TABLES, MONEY_COLUMNS, base_currency,
    format_money, get_currency, is_base, latest_rate, normalize_code, rate_for,
    to_base,
)


# ------------------------------------------------------------------ السجل
def test_riyali_is_the_primary_currency():
    """العملة الأساسية الافتراضية هي الريال اليمني."""
    assert BASE_CURRENCY == "YER"
    assert base_currency().code == "YER"
    assert base_currency().symbol_ar == "ر.ي"
    assert is_base("YER") and is_base("yer") and is_base(None)


def test_registry_covers_common_currencies():
    for code in ("YER", "SAR", "USD", "AED", "EGP"):
        assert code in CURRENCIES
        spec = CURRENCIES[code]
        assert spec.code == code
        assert spec.symbol_ar and spec.symbol_en
        assert spec.name_ar and spec.name_en


def test_every_currency_uses_two_decimals():
    """قرار صريح: خانتان عشريتان لكل العملات بما فيها الريال اليمني."""
    for code, spec in CURRENCIES.items():
        assert spec.decimals == 2, code
    assert format_money(5000, "YER") == "5,000.00 ر.ي"


def test_normalize_code_falls_back_to_base():
    assert normalize_code("usd") == "USD"
    assert normalize_code(" SAR ") == "SAR"
    assert normalize_code("") == "YER"
    assert normalize_code(None) == "YER"
    assert normalize_code("ZZZ") == "YER"          # رمز غير معروف ⇒ الأساس
    assert normalize_code("ZZZ", "SAR") == "SAR"
    assert get_currency("ZZZ").code == "YER"


# ---------------------------------------------------------------- التنسيق
def test_format_money_uses_symbol_per_currency_and_lang():
    assert format_money(148500) == "148,500.00 ر.ي"
    assert format_money(148500, "YER", "en") == "148,500.00 YER"
    assert format_money(1234.5, "SAR") == "1,234.50 ر.س"
    assert format_money(10, "USD", "en") == "10.00 USD"
    assert format_money(10, "USD", "ar") == "10.00 $"


def test_format_money_handles_bad_input_without_raising():
    assert format_money(None) == "0.00 ر.ي"
    assert format_money(0) == "0.00 ر.ي"
    assert format_money(5, with_symbol=False) == "5.00"


def test_format_money_rounds_half_up():
    """تقريب مصرفي (٢٫٦٧٥ ⇒ ٢٫٦٨) لا التقاط نحو الصفر."""
    assert format_money(2.675, "YER", with_symbol=False) == "2.68"
    assert format_money(1.005, "YER", with_symbol=False) == "1.01"
    assert format_money(0.004, "YER", with_symbol=False) == "0.00"


def test_format_money_adds_thousands_separators():
    assert format_money(1234567.891, with_symbol=False) == "1,234,567.89"


# ---------------------------------------------------------------- التحويل
def test_to_base_multiplies_by_rate():
    # 1 USD = 250 YER
    assert to_base(100, "USD", 250) == 25000.0
    assert to_base(1, "SAR", 75.5) == 75.5
    assert to_base(250, "YER", 250) == 250.0        # الأساسية لا تُضرب


def test_to_base_tolerates_missing_or_bad_rate():
    assert to_base(100, "USD", None) == 100.0       # لا سعر ⇒ بلا تحويل
    assert to_base(100, "USD", 0) == 100.0
    assert to_base(100, "USD", "abc") == 100.0
    assert to_base(None, "USD", 250) == 0.0
    assert to_base("bad", "USD", 250) == 0.0


def test_rate_for_derives_rate_from_two_amounts():
    assert rate_for(250, 1) == 250.0     # 1 USD = 250 YER
    assert rate_for(1000, 100) == 10.0
    assert rate_for(10, 0) == 1.0       # قسمة على صفر ⇒ لا انفجار


# ------------------------------------------------------------- المخطّط
def test_money_registry_matches_scanned_tables():
    assert len(CURRENCY_TABLES) == len(MONEY_COLUMNS) == 37
    for table, cols in MONEY_COLUMNS.items():
        assert cols and all(isinstance(c, str) and c for c in cols), table
    assert CURRENCY_TABLES == frozenset(MONEY_COLUMNS)


def test_single_column_entries_are_tuples_not_strings():
    """`("x")` نص لا tuple في Python — لازم فاصلة حتى لا ينهار len()."""
    for table, cols in MONEY_COLUMNS.items():
        assert isinstance(cols, tuple), f"{table} ليس tuple"


def test_every_money_model_has_currency_columns():
    from app.database import Base
    from sqlalchemy.orm import class_mapper
    seen = 0
    for mapper in list(Base.registry.mappers):
        cls = mapper.class_
        tbl = getattr(cls, "__tablename__", "")
        cols = {c.name for c in class_mapper(cls).columns}
        if tbl in CURRENCY_TABLES:
            assert "currency" in cols, tbl
            assert "exchange_rate" in cols, tbl
            seen += 1
    assert seen == 37


def test_non_money_models_are_untouched():
    """لا حقن عملة في غير الجداول المالية (المرضى/المستخدمون)."""
    from app.models import Patient, User
    from sqlalchemy.orm import class_mapper
    for cls in (Patient, User):
        cols = {c.name for c in class_mapper(cls).columns}
        assert "currency" not in cols and "exchange_rate" not in cols


def test_migration_adds_columns_to_existing_db():
    """قاعدة قائمة (بلا الأعمدة) تترحل عبر PENDING_COLUMNS بلا فقد بيانات."""
    from app.database import PENDING_COLUMNS
    for table in CURRENCY_TABLES:
        cols = PENDING_COLUMNS.get(table, {})
        assert "currency" in cols and "exchange_rate" in cols, table
        assert "NOT NULL" in cols["currency"]
        assert f"'{BASE_CURRENCY}'" in cols["currency"]
        assert cols["exchange_rate"].endswith("DEFAULT 1")


# ------------------------------------------------- أسعار الصرف (تحتاج قاعدة)
@pytest.fixture
def fx_db(client):
    from app.database import SessionLocal
    return SessionLocal()


def _clear_fx(quote):
    from app.database import SessionLocal
    from app.models import FxRate
    db = SessionLocal()
    try:
        db.query(FxRate).filter(FxRate.quote_code == quote).delete()
        db.commit()
    finally:
        db.close()


def test_latest_rate_returns_one_for_base(fx_db):
    assert latest_rate(fx_db, "YER") == 1.0


def test_latest_rate_respects_date_history(fx_db):
    from app.models import FxRate
    base = normalize_code(BASE_CURRENCY)
    day = datetime(2026, 1, 10, 12, 0)
    _clear_fx("USD")
    fx_db.add_all([
        FxRate(base_code=base, quote_code="USD", rate=250.0, as_of=day),
        FxRate(base_code=base, quote_code="USD", rate=260.0,
               as_of=day + timedelta(days=10)),
    ])
    fx_db.commit()
    # قبل تاريخ السعر الثاني ⇒ سعر اليوم الأول
    assert latest_rate(fx_db, "USD", day + timedelta(days=2)) == 250.0
    # بعده ⇒ السعر الأحدث
    assert latest_rate(fx_db, "USD", day + timedelta(days=20)) == 260.0
    # بلا تاريخ ⇒ الأحدث
    assert latest_rate(fx_db, "USD") == 260.0
    _clear_fx("USD")


def test_latest_rate_returns_none_for_unknown_quote(fx_db):
    assert latest_rate(fx_db, "EUR") is None


# --------------------------------------------------------------- الواجهة البرمجية
def test_currency_api_config_and_rates(client, admin):
    r = client.get("/currencies/config", headers=admin)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["base_code"] == "YER"
    assert cfg["symbol_ar"] == "ر.ي"
    assert "USD" in cfg["currencies"]

    r = client.get("/currencies", headers=admin)
    assert r.status_code == 200
    rows = r.json()
    assert {"YER", "SAR", "USD"} <= {c["code"] for c in rows}
    assert [c for c in rows if c["code"] == "YER"][0]["is_base"] is True


def test_currency_api_requires_auth(client):
    assert client.get("/currencies/config").status_code in (401, 403)


def test_fx_rate_upsert_and_convert(client, admin):
    _clear_fx("USD")
    r = client.post("/currencies/rates", headers=admin,
                    json={"quote_code": "USD", "rate": 250.0})
    assert r.status_code == 201, r.text
    assert r.json()["rate"] == 250.0
    assert r.json()["base_code"] == "YER"

    r = client.get("/currencies/convert", headers=admin,
                   params={"amount": 100, "from_currency": "USD",
                           "to_currency": "YER"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["converted"] == 25000.0
    assert body["formatted"] == "25,000.00 ر.ي"
    _clear_fx("USD")


def test_fx_rate_rejects_base_against_itself(client, admin):
    r = client.post("/currencies/rates", headers=admin,
                    json={"quote_code": "YER", "rate": 2.0})
    assert r.status_code == 400
    assert "ثابت" in r.json()["detail"]


def test_fx_rate_rejects_unknown_currency(client, admin):
    r = client.post("/currencies/rates", headers=admin,
                    json={"quote_code": "ZZZ", "rate": 2.0})
    assert r.status_code == 400


def test_fx_rate_write_is_admin_only(client):
    r = client.post("/currencies/rates",
                    json={"quote_code": "USD", "rate": 250.0})
    assert r.status_code in (401, 403)


def test_convert_without_rate_is_400(client, admin):
    _clear_fx("EUR")
    r = client.get("/currencies/convert", headers=admin,
                   params={"amount": 10, "from_currency": "EUR",
                           "to_currency": "YER"})
    assert r.status_code == 400
    assert "سعر" in r.json()["detail"]


# ------------------------------------ التقارير تجمع بالعملة الأساسية
def test_invoice_accepts_foreign_currency(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض العملة", "phone": "777000911",
        "date_of_birth": "1990-01-01", "gender": "ذكر",
        "email": "cur_invoice@test.com"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    inv = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 100, "description": "دولار",
        "currency": "USD", "exchange_rate": 250.0})
    assert inv.status_code == 200, inv.text
    body = inv.json()
    assert body["currency"] == "USD"
    assert float(body["exchange_rate"]) == 250.0


def test_dashboard_revenue_aggregates_in_base_currency(client, admin):
    """فاتورة بالدولار تُجمع بالريال في لوحة المراند."""
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض الإيراد", "phone": "777000922",
        "date_of_birth": "1990-01-01", "gender": "ذكر",
        "email": "cur_revenue@test.com"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    inv = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 100, "description": "كلف دولار",
        "currency": "USD", "exchange_rate": 250.0})
    assert inv.status_code == 200, inv.text

    r = client.get("/dashboard/stats", headers=admin)
    assert r.status_code == 200, r.text
    # 100 USD × 250 = 25,000 YER وليس 100
    assert float(r.json()["revenue_total"]) >= 25000.0
