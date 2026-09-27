"""العملات وأسعار الصرف — إدارة العملات وأسعار الصرف التاريخية.

القراءة متاحة لكل مستخدم مسجّل (تحتاجها شاشات الفوترة والتقارير)، والكتابة
للمدير فقط: سعر الصرف قرار مالي يغيّر أرقام كل التقارير اللاحقة.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.currency import (
    BASE_CURRENCY, CURRENCIES, base_currency, format_money, latest_rate,
    normalize_code, to_base,
)
from app.database import get_db
from app.models import FxRate

router = APIRouter(prefix="/currencies", tags=["Currencies & FX"])


class CurrencyOut(BaseModel):
    code: str
    name_ar: str
    name_en: str
    symbol_ar: str
    symbol_en: str
    decimals: int
    is_base: bool = False


class FxRateIn(BaseModel):
    quote_code: str = Field(..., min_length=3, max_length=3,
                            description="عملة العرض (مثال: USD)")
    rate: float = Field(..., gt=0,
                        description="كم وحدة من العملة الأساسية تساوي وحدة واحدة منها")
    as_of: Optional[datetime] = None
    source: Optional[str] = None


class FxRateOut(BaseModel):
    id: int
    base_code: str
    quote_code: str
    rate: float
    as_of: datetime
    source: Optional[str] = None


class ConvertOut(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    rate: float
    converted: float
    formatted: str


@router.get("", response_model=List[CurrencyOut], summary="العملات المدعومة")
def list_currencies(_=Depends(get_current_user)):
    base = normalize_code(BASE_CURRENCY)
    return [CurrencyOut(**vars(spec), is_base=(spec.code == base))
            for spec in CURRENCIES.values()]


@router.get("/config", summary="إعدادات العملة للواجهة")
def currency_config(_=Depends(get_current_user)):
    """ما تحتاجه الواجهة: العملة الأساسية ورمزها وعدد الخانات العشرية."""
    spec = base_currency()
    return {
        "base_code": spec.code, "symbol_ar": spec.symbol_ar,
        "symbol_en": spec.symbol_en, "name_ar": spec.name_ar,
        "name_en": spec.name_en, "decimals": spec.decimals,
        "currencies": [c.code for c in CURRENCIES.values()],
    }


@router.get("/rates", response_model=List[FxRateOut], summary="أسعار الصرف المحفوظة")
def list_rates(
    quote: Optional[str] = Query(None, description="تصفية بعملة عرض واحدة"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    base = normalize_code(BASE_CURRENCY)
    q = db.query(FxRate).filter(FxRate.base_code == base)
    if quote:
        q = q.filter(FxRate.quote_code == normalize_code(quote, base))
    return (q.order_by(FxRate.quote_code.asc(), FxRate.as_of.desc())
             .limit(limit).all())


@router.post("/rates", response_model=FxRateOut, status_code=201,
             summary="تسجيل سعر صرف")
def upsert_rate(payload: FxRateIn, db: Session = Depends(get_db),
                _=Depends(require_admin)):
    """تسجيل سعر صرف لتاريخ — إعادة نفس التاريخ تُحدّث (upsert).

    رفض `quote_code = base` صراحةً: سعر العملة الأساسية لنفسها ثابت 1
    دائماً، والسماح به يُنشئ صفً يوهم بأنه سعر قابل للتعديل.
    """
    base = normalize_code(BASE_CURRENCY)
    quote = normalize_code(payload.quote_code, base)
    if quote not in CURRENCIES:
        raise HTTPException(400, f"عملة غير مدعومة: {payload.quote_code}")
    if quote == base:
        raise HTTPException(400, f"سعر {base} مقابل نفسها ثابت (1) — لا يُسجّل")
    as_of = payload.as_of or datetime.now()
    row = (db.query(FxRate)
           .filter(FxRate.base_code == base, FxRate.quote_code == quote,
                   FxRate.as_of == as_of).first())
    if row:
        row.rate = float(payload.rate)
        row.source = payload.source
    else:
        row = FxRate(base_code=base, quote_code=quote,
                     rate=float(payload.rate), as_of=as_of, source=payload.source)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/rates/{rate_id}", status_code=204, summary="حذف سعر صرف")
def delete_rate(rate_id: int, db: Session = Depends(get_db),
                _=Depends(require_admin)):
    row = db.get(FxRate, rate_id)
    if not row:
        raise HTTPException(404, "سعر الصرف غير موجود")
    db.delete(row)
    db.commit()


@router.get("/latest/{quote_code}", summary="آخر سعر صرف معروف")
def latest(quote_code: str, db: Session = Depends(get_db),
           _=Depends(get_current_user)):
    """أحدث سعر محفوظ — مفيد للواجهة قبل الحفظ."""
    code = normalize_code(quote_code)
    rate = latest_rate(db, code)
    return {"base_code": normalize_code(BASE_CURRENCY), "quote_code": code,
            "rate": rate, "known": rate is not None}


@router.get("/convert", response_model=ConvertOut, summary="تحويل مبلغ")
def convert(
    amount: float = Query(..., description="المبلغ"),
    from_currency: str = Query("YER"),
    to_currency: str = Query("YER"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """تحويل بسعر اليوم المحفوظ. لا تُخزّن أسعار اليوم تلقائًاً (بلا مصدر)."""
    src = normalize_code(from_currency)
    dst = normalize_code(to_currency)
    if src == dst:
        rate, converted = 1.0, float(amount)
    else:
        r = latest_rate(db, src)
        if r is None:
            raise HTTPException(400, f"لا يُوجد سعر صرف محفوظ للعملة {src} — سجّله أولاً")
        base_amount = to_base(amount, src, r)
        inv = latest_rate(db, dst)
        if not inv:
            raise HTTPException(400, f"لا يُوجد سعر صرف محفوظ للعملة {dst} — سجّله أولاً")
        converted = base_amount / float(inv)
        rate = float(r) / float(inv)
    return ConvertOut(amount=float(amount), from_currency=src, to_currency=dst,
                      rate=round(float(rate), 8), converted=round(converted, 4),
                      formatted=format_money(converted, dst))
