"""مركز العمليات السريعة: بيع · شراء · ترحيل في عملية واحدة.

الهدف: إنهاج العملية اليومية بأقل عدد من الخطوات دون كسر أي منطق قائم:

  🛒 **بيع سريع**  → سلة (أدوية + مستلزمات) في عملية واحدة:
     - الأدوية تُصرف كسجلات `Dispense` ⇒ تظهر فورًا في «🛒 المبيعات» والصيدلية
       وتُنقص رصيد الدواء مع حركة `StockMovement` وتنبيه حد التنبيه.
     - المستلزمات تُصرف بمستند `issue` مرحّل (FEFO + أرصدة + دفتر حركات).
     - فاتورة مريض واحدة للأصناف، وقيد مزدوج واحد للعملية كاملة.
  📥 **شراء سريع**  → إذن استلام مرحّل + فاتورة مورد + قيد ذمم دائنة في طلب واحد.
  (نقل) **ترحيل سريع** → تحويل بين مستودعين مرحّلًا مع حركتي خروج ودخول.

كل عملية تستدعي محرّك المستندات في `stock_ops` ومحرك القيود في `accounting` ومنطق
الصرف في `pharmacy`، فالرصيد والحركة والقيد والضريبة تبقى متسقة كما لو نُفّذت من
شاشاتها المنفصلة. والمعاملات ذرّية: أي خطأ (كمية غير كافية، دواء منتهٍ، خصم أكبر
من الإجمالي، مورد غير نشط…) يُلغي العملية كاملة ولا يترك سجلًا ناقصًا.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Dispense, GeneralStockItem, GeneralStockMovement, Invoice, InvoiceStatus,
    JournalEntry, Medication, Notification, Patient, StockBalance, StockDoc,
    StockDocLine, StockMovement, User, Vendor, VendorBill, Warehouse,
)
from app.routers.accounting import _account, _ensure_chart, _money, _new_entry
from app.routers.pharmacy import _ensure_not_expired, _low_stock_crossed
from app.routers.stock_ops import (
    _default_warehouse, _item, _next_doc_no, _post_doc, _seed_legacy_balance,
    _warehouse,
)
from app.schemas import (
    QuickCatalogItem, QuickOpLine, QuickOpsOverview, QuickPurchaseCreate,
    QuickPurchaseOut, QuickRecentOp, QuickSaleCreate, QuickSaleLineOut, QuickSaleOut,
    QuickTransferCreate, QuickTransferOut,
)

router = APIRouter(prefix="/quick-ops", tags=["Quick Operations"])

# هامش السعر المقترح فوق التكلفة — اقتراح قابل للتعديل في البيع السريع
DEFAULT_MARKUP = 1.15
PAYMENT_METHODS = ("cash", "card", "insurance")
VALID_KINDS = ("item", "med")


# ===== أدوات مساعدة =====
def _line_key(ln: QuickOpLine):
    """مفتاح السطر: نوع + معرّف — حتى لا يختلط الصنف بالدواء بنفس الرقم."""
    return (ln.kind or "item", ln.medication_id if ln.kind == "med" else ln.item_id)


def _merged_lines(lines: List[QuickOpLine]) -> List[dict]:
    """يدمج تكرار السطر في سطر واحد (كمية + آخر سعر/تكلفة صريح)."""
    merged: dict = {}
    for ln in lines:
        if (ln.kind or "item") not in VALID_KINDS:
            raise HTTPException(400, f"نوع السطر «{ln.kind}» غير معروف — item أو med")
        if ln.kind == "med" and not ln.medication_id:
            raise HTTPException(400, "سطر الدواء يحتاج medication_id")
        if ln.kind != "med" and not ln.item_id:
            raise HTTPException(400, "سطر الصنف يحتاج item_id")
        key = _line_key(ln)
        row = merged.get(key)
        if row is None:
            row = {"kind": ln.kind,
                   "item_id": ln.item_id if ln.kind != "med" else None,
                   "medication_id": ln.medication_id if ln.kind == "med" else None,
                   "quantity": 0, "unit_price": ln.unit_price, "unit_cost": ln.unit_cost,
                   "batch_no": ln.batch_no, "expiry_date": ln.expiry_date, "note": ln.note}
            merged[key] = row
        row["quantity"] += int(ln.quantity)
        # آخر قيمة صريحة تكتب الأسبق، والحقول الفارغة لا تمسّ الموجود
        for field in ("unit_price", "unit_cost", "batch_no", "expiry_date", "note"):
            if getattr(ln, field) is not None:
                row[field] = getattr(ln, field)
    return list(merged.values())


def _allocate_paid(paid: float, weights: List[float]) -> List[float]:
    """يوزّع المدفوع على الأسطر بالتناسب مع قيمتها — بلا فقد في التقريب."""
    if not weights:
        return []
    weight_sum = _money(sum(weights))
    paid = _money(paid)
    if weight_sum <= 0:
        return [0.0] * len(weights)
    if paid >= weight_sum - .01:
        return [_money(w) for w in weights]
    if paid <= 0:
        return [0.0] * len(weights)
    out = [_money(paid * w / weight_sum) for w in weights]
    drift = _money(paid - sum(out))
    if drift:
        top = out.index(max(out))
        out[top] = _money(out[top] + drift)
    return out


def _status_of(total: float, paid: float) -> str:
    """حالة السجل: PAID عند السداد الكامل، PARTIAL عند جزء، UNPAID عند لا شيء."""
    if paid >= _money(total) - .01:
        return "PAID"
    return "PARTIAL" if paid > 0 else "UNPAID"


def _available(db: Session, item_id: int, wh_id: int) -> int:
    row = (db.query(StockBalance)
           .filter(StockBalance.item_id == item_id, StockBalance.warehouse_id == wh_id)
           .first())
    return int(row.quantity or 0) if row else 0


def _total_quantity(db: Session, item_id: int) -> int:
    db.flush()
    return int(db.query(StockBalance)
               .filter(StockBalance.item_id == item_id)
               .with_entities(func.coalesce(func.sum(StockBalance.quantity), 0))
               .scalar() or 0)


def _suggested_price(item: GeneralStockItem) -> float:
    """السعر المقترح للبيع = التكلفة + هامش افتراضي، مقرّب لأقرب 0.25."""
    return round(float(item.unit_cost or 0) * DEFAULT_MARKUP * 4) / 4 or 0.0


def _item_card(db: Session, item: GeneralStockItem, wh_id: int) -> QuickCatalogItem:
    avail = _available(db, item.id, wh_id)
    point = item.reorder_point or item.min_quantity or 0
    return QuickCatalogItem(
        kind="item", id=item.id, code=item.code, name=item.name, unit=item.unit,
        category=item.category, trade_name=item.trade_name,
        generic_name=item.generic_name, barcode=item.barcode,
        unit_cost=round(float(item.unit_cost or 0), 2),
        suggested_price=_suggested_price(item),
        available=avail, total_quantity=_total_quantity(db, item.id),
        expiry_date=item.expiry_date, low_stock=bool(point and avail <= point))


def _med_card(med: Medication) -> QuickCatalogItem:
    return QuickCatalogItem(
        kind="med", id=med.id, code=med.code, name=med.name, unit=med.unit,
        category="medication", unit_cost=0.0, suggested_price=_money(med.price),
        available=int(med.quantity or 0), total_quantity=int(med.quantity or 0),
        expiry_date=med.expiry_date, low_stock=bool(med.quantity <= med.min_quantity))


def _patient_names(db: Session, ids) -> dict:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return {p.id: p.full_name
            for p in db.query(Patient).filter(Patient.id.in_(ids)).all()}


def _auto_bill_no(db: Session, prefix: str = "V") -> str:
    """رقم فاتورة مورد تلقائي: V-00001 لا يتعارض مع رقم مدخل يدويًا."""
    n = 1
    while (db.query(VendorBill).filter(VendorBill.bill_no == f"{prefix}-{n:05d}").first()
           or db.query(StockDoc).filter(StockDoc.doc_no == f"{prefix}-{n:05d}").first()):
        n += 1
    return f"{prefix}-{n:05d}"


def _notify_low_stock(kind: str, message: str) -> None:
    """إشعار خارجي (تلغرام/ويبهوك) لا يُعطّل العملية أبدًا."""
    try:
        from app.notifier import notify
        notify(kind, message)
    except Exception:  # pragma: no cover - الإشعار相助 فقط
        pass


# ===== لوحة المؤشرات =====
@router.get("/overview", response_model=QuickOpsOverview,
            summary="مؤشرات اليوم + آخر العمليات + الأكثر حركة")
def overview(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """أرقام اليوم لكل مستخدم: مبيعات (فواتير + صرف أدوية) ومشتريات وحركات وتنبيهات."""
    wh = _default_warehouse(db)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    inv_sum, inv_count = (db.query(func.coalesce(func.sum(Invoice.amount - Invoice.discount), 0),
                                   func.count(Invoice.id))
                          .filter(Invoice.created_at >= today).first())
    med_sum, med_count = (db.query(func.coalesce(func.sum(Dispense.total_price), 0),
                                   func.count(Dispense.id))
                          .filter(Dispense.created_at >= today,
                                  Dispense.returned_at.is_(None)).first())
    grn_sum, grn_count = (db.query(func.coalesce(func.sum(GeneralStockMovement.change), 0),
                                    func.count(GeneralStockMovement.id))
                          .filter(GeneralStockMovement.type == "grn",
                                  GeneralStockMovement.created_at >= today).first())
    movements = (db.query(func.count(GeneralStockMovement.id))
                 .filter(GeneralStockMovement.created_at >= today).scalar() or 0)
    low = (db.query(func.count(func.distinct(StockBalance.item_id)))
           .join(GeneralStockItem, GeneralStockItem.id == StockBalance.item_id)
           .filter(StockBalance.warehouse_id == wh.id)
           .filter(or_(StockBalance.quantity <= GeneralStockItem.reorder_point,
                       StockBalance.quantity <= GeneralStockItem.min_quantity))
           .scalar() or 0)
    low += (db.query(func.count(Medication.id))
            .filter(Medication.quantity <= Medication.min_quantity).scalar() or 0)
    soon = datetime.now() + timedelta(days=30)
    expiring = (db.query(func.count(GeneralStockMovement.item_id))
                .filter(GeneralStockMovement.created_at >= today,
                        GeneralStockMovement.type == "issue",
                        GeneralStockMovement.expiry_date.isnot(None),
                        GeneralStockMovement.expiry_date <= soon)
                .scalar() or 0)

    # آخر العمليات: فواتير اليوم ثم صرف أدوية اليوم ثم استلامات اليوم
    recent: List[QuickRecentOp] = []
    inv_rows = (db.query(Invoice).filter(Invoice.created_at >= today)
                .order_by(Invoice.id.desc()).limit(5).all())
    names = _patient_names(db, [i.patient_id for i in inv_rows])
    for inv in inv_rows:
        recent.append(QuickRecentOp(
            kind="sale", icon="🧾", title=f"بيع أصناف #{inv.id} — {names.get(inv.patient_id) or 'مريض'}",
            subtitle=(inv.description or "فاتورة أصناف")[:60],
            amount=_money(inv.amount - inv.discount), reference=f"فاتورة #{inv.id}",
            created_at=inv.created_at))
    disp_rows = (db.query(Dispense).filter(Dispense.created_at >= today,
                                           Dispense.returned_at.is_(None))
                 .order_by(Dispense.id.desc()).limit(5).all())
    med_names = _patient_names(db, [d.patient_id for d in disp_rows])
    for d in disp_rows:
        med = db.query(Medication).filter(Medication.id == d.medication_id).first()
        recent.append(QuickRecentOp(
            kind="sale", icon="🛒",
            title=f"{med.name if med else 'دواء'} × {d.quantity} — {med_names.get(d.patient_id) or ''}".strip(),
            subtitle="صرف صيدلية" + (f" — {d.dispensed_by}" if d.dispensed_by else ""),
            amount=_money(d.total_price), reference=f"صرف #{d.id}", created_at=d.created_at))
    for mv in (db.query(GeneralStockMovement)
               .filter(GeneralStockMovement.type == "grn",
                       GeneralStockMovement.created_at >= today)
               .order_by(GeneralStockMovement.id.desc()).limit(3).all()):
        item = db.query(GeneralStockItem).filter(GeneralStockItem.id == mv.item_id).first()
        recent.append(QuickRecentOp(
            kind="purchase", icon="📥",
            title=f"استلام {item.name if item else mv.item_id} × {mv.change}",
            subtitle=(mv.note or "إذن استلام")[:60], amount=0.0,
            reference=f"مستند #{mv.doc_id}" if mv.doc_id else None, created_at=mv.created_at))
    recent.sort(key=lambda x: x.created_at, reverse=True)

    # الأكثر حركة اليوم — مرشّحات سريعة للسلة
    top: List[QuickCatalogItem] = []
    for iid in [r[0] for r in (db.query(GeneralStockMovement.item_id)
                              .filter(GeneralStockMovement.created_at >= today,
                                      GeneralStockMovement.type.in_(
                                          ("issue", "grn", "transfer_out")))
                              .group_by(GeneralStockMovement.item_id)
                              .order_by(func.count(GeneralStockMovement.id).desc())
                              .limit(4).all())]:
        item = db.query(GeneralStockItem).filter(GeneralStockItem.id == iid).first()
        if item and item.is_active:
            top.append(_item_card(db, item, wh.id))
    for mid in [r[0] for r in (db.query(Dispense.medication_id)
                              .filter(Dispense.created_at >= today,
                                      Dispense.returned_at.is_(None))
                              .group_by(Dispense.medication_id)
                              .order_by(func.count(Dispense.id).desc()).limit(4).all())]:
        med = db.query(Medication).filter(Medication.id == mid).first()
        if med:
            top.append(_med_card(med))
    db.commit()
    return QuickOpsOverview(
        sales_today=_money(inv_sum) + _money(med_sum),
        sales_count_today=int(inv_count or 0) + int(med_count or 0),
        purchases_today=_money(grn_sum), purchases_count_today=int(grn_count or 0),
        movements_today=int(movements), low_stock_count=int(low),
        expiring_soon_count=int(expiring), top_items=top, recent=recent[:8])


# ===== البحث السريع عن الأصناف والأدوية =====
@router.get("/catalog", response_model=List[QuickCatalogItem],
            summary="بحث سريع بالأدوية والمستلزمات مع المتاح والسعر المقترح")
def catalog(q: str = Query("", description="نص البحث — حرفان على الأقل"),
            warehouse_id: Optional[int] = Query(None, gt=0),
            limit: int = Query(10, ge=1, le=50),
            db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """يغذّي قوائم البيع/الشراء/الترحيل: بحث لحظي بلا إعادة تحميل الصفحة."""
    wh = _warehouse(db, warehouse_id, "المستودع")
    text = (q or "").strip()
    out: List[QuickCatalogItem] = []
    if len(text) >= 2:
        like = f"%{text}%"
        items = (db.query(GeneralStockItem)
                 .filter(GeneralStockItem.is_active.is_(True))
                 .filter(or_(GeneralStockItem.name.ilike(like),
                             GeneralStockItem.code.ilike(like),
                             GeneralStockItem.barcode.ilike(like),
                             GeneralStockItem.trade_name.ilike(like),
                             GeneralStockItem.generic_name.ilike(like)))
                 .order_by(GeneralStockItem.name.asc()).limit(limit).all())
        meds = (db.query(Medication)
                .filter(or_(Medication.name.ilike(like), Medication.code.ilike(like)))
                .order_by(Medication.name.asc()).limit(limit).all())
        out = [_item_card(db, it, wh.id) for it in items] + [_med_card(m) for m in meds]
    else:
        out = [_med_card(m) for m in (db.query(Medication)
                .order_by(func.coalesce(Medication.quantity, 0).desc())
                .limit(limit).all())]
    # مطابقة الرمز بالضبط أولًا ثم الاسم
    if text:
        out.sort(key=lambda x: (0 if x.code.lower() == text.lower() else 1, x.name))
    return out[:limit * 2]

# ===== 🛒 بيع سريع =====
@router.post("/sales", response_model=QuickSaleOut, status_code=201,
             summary="بيع سريع: أدوية + مستلزمات في عملية واحدة مع فاتورة وقيد")
def quick_sale(payload: QuickSaleCreate, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    """سلة بيع كاملة بأقل خطوة:

    - الأدوية ⇒ سجلات `Dispense` تظهر في «🛒 المبيعات» والصيدلية وتُنقص رصيد الدواء.
    - المستلزمات ⇒ فاتورة + إذن صرف مرحّل (FEFO) من المستودع.
    - المدفوع يوزَّع على الأسطر بالتناسب، والقيد المزدوج يغطي العملية كاملة.
    """
    _ensure_chart(db)
    patient = db.query(Patient).filter(Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(404, "المريض غير موجود")
    method = (payload.payment_method or "cash").strip().lower()
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, "طريقة الدفع يجب أن تكون cash أو card أو insurance")
    wh = _warehouse(db, payload.warehouse_id, "مستودع البيع")
    lines = _merged_lines(payload.lines)
    if not lines:
        raise HTTPException(400, "أضف صنفًا واحدًا على الأقل")
    now = datetime.now()

    # ===== 1) فحص كل السطور قبل أي كتابة — فشل واحد يُلغي العملية كاملة =====
    items: List[dict] = []          # أصناف المخزون ⇒ فاتورة + إذن صرف
    meds: List[dict] = []           # الأدوية ⇒ سجلات صرف صيدلية
    for ln in lines:
        if ln["kind"] == "med":
            med = db.query(Medication).filter(Medication.id == ln["medication_id"]).first()
            if not med:
                raise HTTPException(404, f"الدواء برقم {ln['medication_id']} غير موجود")
            _ensure_not_expired(med, now)
            if ln["quantity"] > med.quantity:
                raise HTTPException(400, f"الكمية غير كافية من «{med.name}»: المتوفر "
                                         f"{med.quantity} والمطلوب {ln['quantity']}")
            price = _money(ln["unit_price"] if ln["unit_price"] is not None else med.price)
            meds.append({"med": med, "quantity": ln["quantity"], "unit_price": price,
                         "total": _money(price * ln["quantity"]), "note": ln["note"]})
        else:
            item = _item(db, ln["item_id"])
            _seed_legacy_balance(db, item)
            avail = _available(db, item.id, wh.id)
            if ln["quantity"] > avail:
                raise HTTPException(400, f"الكمية غير كافية في «{wh.name}»: المتوفر {avail} "
                                         f"والمطلوب {ln['quantity']} من الصنف «{item.name}»")
            price = _money(ln["unit_price"] if ln["unit_price"] is not None
                           else _suggested_price(item))
            if price < 0:
                raise HTTPException(400, f"سعر الصنف «{item.name}» لا يكون سالبًا")
            items.append({"item": item, "quantity": ln["quantity"], "unit_price": price,
                          "total": _money(price * ln["quantity"]), "available": avail,
                          "note": ln["note"]})

    items_total = _money(sum(x["total"] for x in items))
    meds_total = _money(sum(x["total"] for x in meds))
    if not items and not meds:
        raise HTTPException(400, "أضف صنفًا واحدًا على الأقل")
    # الخصم والضريبة على أصناف المستلزمات (الفاتورة)، والأدوية تُسعّر كما هي
    if payload.discount > items_total + .01:
        raise HTTPException(400, "الخصم يتجاوز إجمالي المستلزمات")
    tax = _money((items_total - _money(payload.discount)) * payload.tax_rate / 100.0)
    items_net = _money(items_total - _money(payload.discount) + tax)
    grand_total = _money(items_net + meds_total)
    if grand_total <= 0:
        raise HTTPException(400, "لا يمكن تسجيل عملية بيع بقيمة صفر")
    paid = _money(payload.paid_amount)
    if paid > grand_total + .01:
        raise HTTPException(400, "المدفوع أكبر من إجمالي الفاتورة")
    remaining = _money(grand_total - paid)

    # توزيع المدفوع بالتناسب على كل الأسطر (أصناف + أدوية)
    weights = [x["total"] for x in items] + [x["total"] for x in meds]
    shares = _allocate_paid(paid, weights)

    # ===== 2) صرف الأدوية: سجلات صيدلية + خصم الرصيد + حركات + تنبيه حد التنبيه =====
    dispenses: List[Dispense] = []
    for idx, row in enumerate(meds):
        med = row["med"]
        was_above_min = _low_stock_crossed(med, med.quantity > med.min_quantity)
        med.quantity -= row["quantity"]
        entry = Dispense(
            medication_id=med.id, patient_id=patient.id, quantity=row["quantity"],
            unit_price=row["unit_price"], total_price=row["total"],
            payment_method=method, paid_amount=shares[len(items) + idx],
            status=_status_of(row["total"], shares[len(items) + idx]),
            paid_at=now if shares[len(items) + idx] > 0 else None,
            notes=payload.notes, dispensed_by=user.username)
        db.add(entry)
        dispenses.append(entry)
        db.add(StockMovement(
            medication_id=med.id, type="out", change=-row["quantity"],
            quantity_after=med.quantity,
            note=f"بيع سريع للمريض: {patient.full_name}"
                 + (f" — {payload.notes}" if payload.notes else ""),
            made_by=user.username))
        if was_above_min and med.quantity <= med.min_quantity:
            db.add(Notification(
                type="low_stock", title="مخزون منخفض",
                message=f"كمية «{med.name}» أصبحت {med.quantity} {med.unit} "
                        f"(حد التنبيه {med.min_quantity})"))
    db.flush()
    if any(d.returned_at is None for d in dispenses):
        for med_row, entry in zip(meds, dispenses):
            med = med_row["med"]
            if med.quantity <= med.min_quantity:
                _notify_low_stock("low_stock",
                                  f"كمية «{med.name}» أصبحت {med.quantity} {med.unit}")

    # ===== 3) فاتورة المستلزمات + إذن الصرف المرحّل من المستودع =====
    invoice = None
    doc = None
    if items:
        items_paid = _money(sum(shares[:len(items)]))
        invoice = Invoice(
            patient_id=patient.id, amount=items_total, discount=_money(payload.discount),
            tax_rate=payload.tax_rate, paid_amount=items_paid,
            status=InvoiceStatus(_status_of(items_net, items_paid).lower()),
            payment_method=method, paid_at=now if items_paid > 0 else None,
            description=payload.description or "بيع سريع: " + " + ".join(
                f"{x['item'].name}×{x['quantity']}" for x in items[:3])[:200])
        db.add(invoice)
        db.flush()
        doc = StockDoc(
            doc_type="issue", doc_no=_next_doc_no(db, "issue"), status="completed",
            from_warehouse_id=wh.id, patient_id=patient.id,
            reference=f"فاتورة #{invoice.id}", notes=payload.notes,
            created_by=user.username, completed_at=now)
        db.add(doc)
        db.flush()
        for row in items:
            db.add(StockDocLine(
                doc_id=doc.id, item_id=row["item"].id, quantity=row["quantity"],
                unit_cost=_money(row["item"].unit_cost or 0), note=row["note"]))
        db.flush()
        _post_doc(db, doc, user)

    # ===== 4) القيد المحاسبي: دفعة كاملة ⇒ نقدية/بنك، وإلا ⇒ ذمم مريض أو تأمين =====
    if remaining <= .01:
        cash_code = "1000" if method == "cash" else "1010"
        head = {"code": cash_code, "debit": grand_total, "description": "تحصيل بيع سريع"}
    else:
        debit_code = "1110" if (method == "insurance" or patient.insurer) else "1100"
        head = {"code": debit_code, "debit": grand_total, "description": "ذمم من بيع سريع"}
    je_lines = [head]
    if items_net:
        je_lines.append({"code": "4000", "credit": items_net, "description": "إيراد مستلزمات"})
    if meds_total:
        je_lines.append({"code": "4000", "credit": meds_total, "description": "إيراد صيدلية"})
    if invoice is not None:
        entry = _new_entry(db, now, f"بيع سريع — فاتورة #{invoice.id}",
                           "patient_invoice", invoice.id, je_lines, user.username)
    else:
        entry = _new_entry(db, now, f"بيع سريع — صرف أدوية للمريض {patient.full_name}",
                           "quick_sale_medicines", dispenses[0].id if dispenses else 0,
                           je_lines, user.username)
    db.commit()
    db.refresh(invoice) if invoice is not None else None

    out_lines: List[QuickSaleLineOut] = []
    for idx, row in enumerate(items):
        out_lines.append(QuickSaleLineOut(
            kind="item", ref_id=row["item"].id, name=row["item"].name,
            code=row["item"].code, unit=row["item"].unit, quantity=row["quantity"],
            unit_price=row["unit_price"], total=row["total"],
            available=row["available"], paid=shares[idx], record_id=invoice.id if invoice else None))
    for idx, row in enumerate(meds):
        out_lines.append(QuickSaleLineOut(
            kind="med", ref_id=row["med"].id, name=row["med"].name, code=row["med"].code,
            unit=row["med"].unit, quantity=row["quantity"], unit_price=row["unit_price"],
            total=row["total"], available=row["med"].quantity,
            paid=shares[len(items) + idx], record_id=dispenses[idx].id))
    return QuickSaleOut(
        invoice_id=invoice.id if invoice is not None else None,
        dispense_ids=[d.id for d in dispenses], dispense_count=len(dispenses),
        items_total=items_total, medicines_total=meds_total,
        patient_id=patient.id, patient_name=patient.full_name,
        doc_id=doc.id if doc is not None else None, doc_no=doc.doc_no if doc else None,
        warehouse=wh.name if items else None,
        subtotal=_money(items_total + meds_total), discount=_money(payload.discount),
        tax=tax, total=grand_total, paid_amount=paid, remaining=remaining,
        status=("PAID" if remaining <= .01 else "PARTIAL" if paid > 0 else "UNPAID"),
        payment_method=method, journal_entry_id=entry.id,
        journal_entry_no=entry.entry_no, lines=out_lines)


# ===== 📥 شراء سريع =====
@router.post("/purchases", response_model=QuickPurchaseOut, status_code=201,
             summary="شراء سريع: إذن استلام مرحّل + فاتورة مورد + قيد في طلب واحد")
def quick_purchase(payload: QuickPurchaseCreate, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    """استلام مورد فوري: أصناف + تشغيلات + انتهاء ⇒ مخزون داخل + ذمم دائنة للمورد."""
    _ensure_chart(db)
    vendor = db.query(Vendor).filter(Vendor.id == payload.vendor_id,
                                     Vendor.is_active.is_(True)).first()
    if not vendor:
        raise HTTPException(404, "المورد غير موجود أو غير نشط")
    wh = _warehouse(db, payload.warehouse_id, "مستودع الاستلام")
    expense = _account(db, payload.expense_account_code)
    if expense.account_type != "expense":
        raise HTTPException(400, "حساب المشتريات المحدد ليس حساب مصروف")
    lines = _merged_lines(payload.lines)
    if not lines:
        raise HTTPException(400, "أضف صنفًا واحدًا على الأقل")
    bill_no = (payload.bill_no or "").strip() or _auto_bill_no(db)
    if db.query(VendorBill).filter(VendorBill.bill_no == bill_no).first():
        raise HTTPException(409, "رقم فاتورة المورد مستخدم مسبقًا")
    bill_date = payload.bill_date or datetime.now()
    now = datetime.now()

    # 1) إذن الاستلام المرحّل: دفعات + أرصدة + حركات grn
    amount = 0.0
    out_lines: List[dict] = []
    doc = StockDoc(doc_type="grn", doc_no=_next_doc_no(db, "grn"), status="completed",
                   to_warehouse_id=wh.id, vendor_id=vendor.id, reference=bill_no,
                   notes=f"شراء سريع — فاتورة {bill_no}",
                   created_by=user.username, completed_at=now)
    db.add(doc)
    db.flush()
    for ln in lines:
        item = _item(db, ln["item_id"])
        _seed_legacy_balance(db, item)
        cost = _money(ln["unit_cost"] if ln["unit_cost"] is not None else (item.unit_cost or 0))
        db.add(StockDocLine(doc_id=doc.id, item_id=item.id, quantity=ln["quantity"],
                            unit_cost=cost, batch_no=ln["batch_no"],
                            expiry_date=ln["expiry_date"], note=ln["note"]))
        amount = _money(amount + cost * ln["quantity"])
        out_lines.append({"item_id": item.id, "quantity": ln["quantity"],
                          "unit_cost": cost, "batch_no": ln["batch_no"],
                          "expiry_date": ln["expiry_date"]})
    db.flush()
    if amount <= 0:
        raise HTTPException(400, "قيمة الشراء يجب أن تكون أكبر من صفر — حدّد تكلفة الصنف")
    _post_doc(db, doc, user)

    # 2) فاتورة المورد + قيد ذمم الدائنة
    entry = _new_entry(db, bill_date, f"فاتورة مورد {bill_no}", "vendor_bill", 0,
                       [{"code": expense.code, "debit": amount,
                         "description": f"مشتريات من {vendor.name}"},
                        {"code": "2000", "credit": amount,
                         "description": f"ذمم مورد {vendor.name}"}], user.username)
    bill = VendorBill(
        bill_no=bill_no, vendor_id=vendor.id, bill_date=bill_date, due_date=payload.due_date,
        amount=amount, paid_amount=0, status="unpaid",
        expense_account_code=expense.code, journal_entry_id=entry.id,
        created_by=user.username)
    db.add(bill)
    db.flush()
    entry.reference_id = bill.id
    db.commit()
    db.refresh(bill)
    return QuickPurchaseOut(
        doc_id=doc.id, doc_no=doc.doc_no, warehouse=wh.name,
        vendor_id=vendor.id, vendor_name=vendor.name,
        bill_id=bill.id, bill_no=bill.bill_no, bill_amount=amount, outstanding=amount,
        expense_account_code=expense.code, journal_entry_id=entry.id,
        journal_entry_no=entry.entry_no,
        total_quantity=sum(x["quantity"] for x in lines), total_value=amount,
        lines=[QuickOpLine(item_id=x["item_id"], quantity=x["quantity"],
                           unit_cost=x["unit_cost"], batch_no=x["batch_no"],
                           expiry_date=x["expiry_date"]) for x in out_lines])


# ===== 🔄 ترحيل سريع =====
@router.post("/transfers", response_model=QuickTransferOut, status_code=201,
             summary="ترحيل سريع بين المستودعات مع قيد حركتين (خروج ودخول)")
def quick_transfer(payload: QuickTransferCreate, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    """تحويل فوري من مستودع إلى آخر: يتحقق من التوافر ثم يرحّل خرج/دخول ودفتر الحركات."""
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(400, "لا يمكن الترحيل إلى نفس المستودع")
    src = _warehouse(db, payload.from_warehouse_id, "مستودع المصدر")
    dst = _warehouse(db, payload.to_warehouse_id, "مستودع الوجهة")
    lines = _merged_lines(payload.lines)
    if not lines:
        raise HTTPException(400, "أضف صنفًا واحدًا على الأقل")
    for ln in lines:
        if ln["kind"] != "item":
            raise HTTPException(400, "الترحيل يعمل على أصناف المستلزمات فقط")
        item = _item(db, ln["item_id"])
        _seed_legacy_balance(db, item)
        avail = _available(db, item.id, src.id)
        if ln["quantity"] > avail:
            raise HTTPException(400, f"الكمية غير كافية في «{src.name}»: المتوفر {avail} "
                                     f"والمطلوب {ln['quantity']} من الصنف «{item.name}»")
    now = datetime.now()
    doc = StockDoc(doc_type="transfer", doc_no=_next_doc_no(db, "transfer"), status="completed",
                   from_warehouse_id=src.id, to_warehouse_id=dst.id,
                   department_id=payload.department_id,
                   notes=payload.notes or f"ترحيل سريع {src.name} ← {dst.name}",
                   created_by=user.username, completed_at=now)
    db.add(doc)
    db.flush()
    out_lines: List[QuickOpLine] = []
    value = 0.0
    for ln in lines:
        item = _item(db, ln["item_id"])
        cost = _money(ln["unit_cost"] if ln["unit_cost"] is not None else (item.unit_cost or 0))
        db.add(StockDocLine(doc_id=doc.id, item_id=item.id, quantity=ln["quantity"],
                            unit_cost=cost, note=ln["note"]))
        value = _money(value + cost * ln["quantity"])
        out_lines.append(QuickOpLine(item_id=item.id, quantity=ln["quantity"],
                                    unit_cost=cost, note=ln["note"]))
    db.flush()
    _post_doc(db, doc, user)
    db.commit()
    return QuickTransferOut(
        doc_id=doc.id, doc_no=doc.doc_no, from_warehouse=src.name, to_warehouse=dst.name,
        total_quantity=sum(x["quantity"] for x in lines), total_value=value,
        lines=out_lines)
