"""إدارة المخازن المتقدّمة — المستودعات والمستندات والتقارير.

يجمع النقاط الستّ في طبقة واحدة فوق `general_stock_items`:
  1. دليل المواد  → حقول تفصيلية + مستويات إعادة الطلب (حد/نقطة/حد أقصى)
  2. حركة المخازن → إذن استلام · تحويل بين المخازن · صرف للأقسام/المرضى · مرتجعات
  3. الجرد        → جلسة جرد فعلية تُغلق بتسويات (فروقات) وحركات
  4. الصلاحية     → دفعات/تشغيلات بتواريخ انتهاء + صرف FEFO + إهلاك موثّق
  5. المشتريات   → طلب شراء · أمر شراء (استلامه يولّد إذن استلام)
  6. التقارير     → بطاقة الصنف · تنبيهات انتهاء · تقييم (متوسط/FIFO) · الركود

كل مستند يُنشئ حركات في `general_stock_movements` وأرصدة في `stock_balances`،
فالرصيد والتقرير وبطاقة الصنف مشتقّة من سجل واحد.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Department, GeneralStockItem, GeneralStockMovement, Patient, StockBatch,
    StockBalance, StockDoc, StockDocLine, User, Vendor, Warehouse,
)
from app.schemas import (
    ExpiryAlertRow, GeneralStockMovementOut, SlowMovingRow, StockDocAction,
    StockDocCreate, StockDocLineOut, StockDocOut, ValuationRow, WarehouseCreate,
    WarehouseOut, WarehouseUpdate,
)

router = APIRouter(prefix="/stock", tags=["Stock Operations"])

DOC_TYPES = ("grn", "transfer", "issue", "return", "supplier_return",
             "stocktake", "pr", "po")
# مستندات تُرحّل حركة مخزون فور الإنشاء؛ أما pr/po/stocktake فمسودّة حتى تُعتمد/تُغلق
POSTING_TYPES = ("grn", "transfer", "issue", "return", "supplier_return")
DRAFT_TYPES = ("pr", "po", "stocktake")
TYPE_LABELS = {
    "grn": "إذن استلام", "transfer": "تحويل", "issue": "صرف",
    "return": "مرتجع", "supplier_return": "مرتجع مورد",
    "stocktake": "جرد", "pr": "طلب شراء", "po": "أمر شراء",
}


# ===== أدوات مساعدة =====
def _default_warehouse(db: Session) -> Warehouse:
    """المستودع الافتراضي — يُنشأ «المستودع الرئيسي» عند أول استخدام."""
    wh = db.query(Warehouse).filter(Warehouse.is_default.is_(True)).first()
    if wh:
        return wh
    wh = db.query(Warehouse).order_by(Warehouse.id).first()
    if wh:
        return wh
    wh = Warehouse(name="المستودع الرئيسي", kind="main", is_default=True)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


def _warehouse(db: Session, wid: Optional[int], label: str) -> Warehouse:
    if wid is None:
        return _default_warehouse(db)
    wh = db.query(Warehouse).filter(Warehouse.id == wid).first()
    if not wh:
        raise HTTPException(404, f"{label} غير موجود")
    if not wh.is_active:
        raise HTTPException(400, f"{label} «{wh.name}» معطّل")
    return wh


def _balance(db: Session, item_id: int, wh_id: int) -> StockBalance:
    row = (db.query(StockBalance)
           .filter(StockBalance.item_id == item_id, StockBalance.warehouse_id == wh_id)
           .first())
    if row is None:
        row = StockBalance(item_id=item_id, warehouse_id=wh_id, quantity=0)
        db.add(row)
        db.flush()
    return row


def _item(db: Session, item_id: int) -> GeneralStockItem:
    item = db.query(GeneralStockItem).filter(GeneralStockItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "الصنف غير موجود")
    return item


def _seed_legacy_balance(db: Session, item: GeneralStockItem) -> None:
    """أصناف سابقة لجدول الأرصدة: رصيدها الافتتاحي يدخل المستودع الافتراضي."""
    has_row = db.query(StockBalance).filter(StockBalance.item_id == item.id).first()
    if has_row or not item.quantity:
        return
    wh = _default_warehouse(db)
    bal = _balance(db, item.id, wh.id)
    bal.quantity += item.quantity
    db.add(GeneralStockMovement(
        item_id=item.id, warehouse_id=wh.id, type="adjust",
        change=item.quantity, quantity_after=bal.quantity,
        note="رصيد افتتاحي (ترحيل من النظام القديم)", made_by="system"))


# ===== الدفعات وFEFO =====
def _fefo_batches(db: Session, item_id: int, wh_id: int):
    """دفعات الصنف مرتّبة FEFO: الأقرب انتهاءً أولًا، ثم ما بلا تاريخ."""
    return (db.query(StockBatch)
            .filter(StockBatch.item_id == item_id, StockBatch.warehouse_id == wh_id,
                    StockBatch.quantity > 0)
            .order_by(StockBatch.expiry_date.is_(None), StockBatch.expiry_date.asc(),
                      StockBatch.received_at.asc(), StockBatch.id.asc())
            .all())


def _consume_batches(db: Session, item_id: int, wh_id: int, qty: int) -> None:
    """استهلاك FEFO — يخصم من أقرب دفعة انتهاءً، والمتبقي يُسجَّل كدفعة بلا تاريخ."""
    left = qty
    for batch in _fefo_batches(db, item_id, wh_id):
        if left <= 0:
            break
        take = min(batch.quantity, left)
        batch.quantity -= take
        left -= take
    if left > 0:
        db.add(StockBatch(item_id=item_id, warehouse_id=wh_id, quantity=left,
                          unit_cost=0))


def _add_batch(db: Session, item_id: int, wh_id: int, qty: int,
               batch_no: Optional[str], expiry: Optional[datetime],
               cost: float) -> None:
    """دفعة جديدة — نفس رقم التشغيلة في نفس المخزن تُدمج في دفعة واحدة."""
    if batch_no:
        existing = (db.query(StockBatch)
                    .filter(StockBatch.item_id == item_id,
                            StockBatch.warehouse_id == wh_id,
                            StockBatch.batch_no == batch_no).first())
        if existing:
            existing.quantity += qty
            if cost:
                existing.unit_cost = cost
            if expiry and not existing.expiry_date:
                existing.expiry_date = expiry
            return
    db.add(StockBatch(item_id=item_id, warehouse_id=wh_id, quantity=qty,
                      unit_cost=cost or 0, batch_no=batch_no, expiry_date=expiry))


def _sync_item_expiry(db: Session, item: GeneralStockItem) -> None:
    """انتهاء الصنف = أقرب دفعة (FEFO) فلا يبقى تاريخ قديم بعد توريد جديد."""
    nxt = (db.query(StockBatch)
           .filter(StockBatch.item_id == item.id, StockBatch.quantity > 0)
           .order_by(StockBatch.expiry_date.is_(None), StockBatch.expiry_date.asc())
           .first())
    item.expiry_date = nxt.expiry_date if nxt else None


def _item_total(db: Session, item_id: int) -> int:
    """إجمالي رصيد الصنف عبر كل المخازن — flush أولًا لأن الجلسة بلا autoflush."""
    db.flush()
    return (db.query(StockBalance)
            .filter(StockBalance.item_id == item_id)
            .with_entities(func.coalesce(func.sum(StockBalance.quantity), 0))
            .scalar() or 0)


# ===== قيد الحركة =====
def _post(db: Session, item: GeneralStockItem, wh_id: int, mtype: str, change: int,
          user: User, doc: Optional[StockDoc] = None,
          line: Optional[StockDocLine] = None, patient_id: Optional[int] = None,
          department_id: Optional[int] = None, note: Optional[str] = None
          ) -> Optional[GeneralStockMovement]:
    """قيد حركة: رصيد المخزن + إجمالي الصنف + الدفعات + دفتر الحركات."""
    bal = _balance(db, item.id, wh_id)
    if change < 0 and abs(change) > bal.quantity:
        wh = db.query(Warehouse).filter(Warehouse.id == wh_id).first()
        raise HTTPException(
            400,
            f"الكمية غير كافية في «{wh.name if wh else wh_id}»: المتوفر "
            f"{bal.quantity} والمطلوب {abs(change)} من الصنف «{item.name}»",
        )
    if change < 0:
        _consume_batches(db, item.id, wh_id, abs(change))
    bal.quantity += change
    if not change:
        return None  # جرد مطابق — فرق صفر فلا حركة
    item.quantity = _item_total(db, item.id)
    mv = GeneralStockMovement(
        item_id=item.id, warehouse_id=wh_id, type=mtype, change=change,
        quantity_after=bal.quantity, doc_id=doc.id if doc else None,
        batch_no=line.batch_no if line else None,
        expiry_date=line.expiry_date if line else None,
        patient_id=patient_id, department_id=department_id,
        note=note, made_by=user.username if user else None)
    db.add(mv)
    return mv


def _next_doc_no(db: Session, doc_type: str) -> str:
    """ترقيم متسلسل لكل نوع على حدة: GRN-000012."""
    prefix = doc_type.upper()
    last = (db.query(StockDoc).filter(StockDoc.doc_type == doc_type)
            .order_by(StockDoc.id.desc()).first())
    n = (last.id + 1) if last else 1
    while db.query(StockDoc).filter(StockDoc.doc_type == doc_type,
                                    StockDoc.doc_no == f"{prefix}-{n:06d}").first():
        n += 1
    return f"{prefix}-{n:06d}"


# ===== تسلسل الاستجابات =====
def _movement_out(db: Session, mv: GeneralStockMovement) -> GeneralStockMovementOut:
    item = db.query(GeneralStockItem).filter(GeneralStockItem.id == mv.item_id).first()
    wh = db.query(Warehouse).filter(Warehouse.id == mv.warehouse_id).first()
    doc = db.query(StockDoc).filter(StockDoc.id == mv.doc_id).first() if mv.doc_id else None
    return GeneralStockMovementOut(
        id=mv.id, item_id=mv.item_id,
        item_name=item.name if item else None, item_code=item.code if item else None,
        warehouse=wh.name if wh else None, type=mv.type, change=mv.change,
        quantity_after=mv.quantity_after, doc_id=mv.doc_id,
        doc_no=doc.doc_no if doc else None, batch_no=mv.batch_no,
        expiry_date=mv.expiry_date, patient_id=mv.patient_id,
        department_id=mv.department_id, note=mv.note, made_by=mv.made_by,
        created_at=mv.created_at)


def _doc_out(db: Session, doc: StockDoc) -> StockDocOut:
    lines, total_qty, total_val = [], 0, 0.0
    for ln in doc.lines:
        item = db.query(GeneralStockItem).filter(GeneralStockItem.id == ln.item_id).first()
        cost = ln.unit_cost or (item.unit_cost if item else 0) or 0
        lines.append(StockDocLineOut(
            id=ln.id, item_id=ln.item_id,
            item_name=item.name if item else None,
            item_code=item.code if item else None,
            unit=item.unit if item else None,
            quantity=ln.quantity, counted_quantity=ln.counted_quantity,
            unit_cost=cost, batch_no=ln.batch_no, expiry_date=ln.expiry_date,
            note=ln.note))
        q = ln.counted_quantity if ln.counted_quantity is not None else ln.quantity
        total_qty += q or 0
        total_val += (q or 0) * cost
    return StockDocOut(
        id=doc.id, doc_type=doc.doc_type, doc_no=doc.doc_no, status=doc.status,
        from_warehouse=doc.from_warehouse.name if doc.from_warehouse else None,
        to_warehouse=doc.to_warehouse.name if doc.to_warehouse else None,
        vendor_id=doc.vendor_id, vendor_name=doc.vendor.name if doc.vendor else None,
        department_id=doc.department_id, patient_id=doc.patient_id,
        reference=doc.reference, notes=doc.notes, needed_at=doc.needed_at,
        expected_at=doc.expected_at, created_by=doc.created_by,
        approved_by=doc.approved_by, created_at=doc.created_at,
        completed_at=doc.completed_at, total_quantity=total_qty,
        total_value=round(total_val, 2), lines=lines)


# ===== التحقق من المستند =====
def _validate(db: Session, payload: StockDocCreate):
    """يتحقّق من اكتمال بيانات كل نوع قبل الحفظ — أخطاء واضحة بدل غموض."""
    if payload.doc_type not in DOC_TYPES:
        raise HTTPException(400, f"نوع المستند يجب أن يكون من: {', '.join(DOC_TYPES)}")
    for ln in payload.lines:
        _item(db, ln.item_id)
        if payload.doc_type == "stocktake":
            if ln.counted_quantity is None:
                raise HTTPException(400, "الجرد يحتاج عدًّا فعليًا (counted_quantity) لكل صنف")
        elif ln.quantity <= 0:
            raise HTTPException(400, "كمية كل سطر يجب أن تكون أكبر من صفر")
    if payload.department_id and not db.query(Department).filter(
            Department.id == payload.department_id).first():
        raise HTTPException(404, "القسم غير موجود")
    if payload.patient_id and not db.query(Patient).filter(
            Patient.id == payload.patient_id).first():
        raise HTTPException(404, "المريض غير موجود")
    if payload.vendor_id and not db.query(Vendor).filter(
            Vendor.id == payload.vendor_id).first():
        raise HTTPException(404, "المورد غير موجود")

    src = dst = None
    dtype = payload.doc_type
    if dtype == "grn":
        dst = _warehouse(db, payload.to_warehouse_id, "مستودع الاستلام")
    elif dtype == "transfer":
        src = _warehouse(db, payload.from_warehouse_id, "مستودع المصدر")
        dst = _warehouse(db, payload.to_warehouse_id, "مستودع الوجهة")
        if src.id == dst.id:
            raise HTTPException(400, "مستودع المصدر والوجهة لا يمكن أن يكونا واحدًا")
    elif dtype == "issue":
        src = _warehouse(db, payload.from_warehouse_id, "مستودع الصرف")
        if not payload.department_id and not payload.patient_id:
            raise HTTPException(400, "الصرف يحتاج قسمًا أو مريضًا")
    elif dtype == "return":
        dst = _warehouse(db, payload.to_warehouse_id, "مستودع الاسترجاع")
        if not payload.department_id and not payload.patient_id:
            raise HTTPException(400, "المرتجع يحتاج مصدره: قسمًا أو مريضًا")
    elif dtype == "supplier_return":
        src = _warehouse(db, payload.from_warehouse_id, "مستودع المرتجع")
        if not payload.vendor_id:
            raise HTTPException(400, "مرتجع المورد يحتاج اختيار المورد")
    elif dtype == "stocktake":
        src = _warehouse(db, payload.from_warehouse_id, "مستودع الجرد")
    elif dtype == "po":
        if not payload.vendor_id:
            raise HTTPException(400, "أمر الشراء يحتاج اختيار المورد")
    elif dtype == "pr" and payload.source_doc_id:
        if not db.query(StockDoc).filter(StockDoc.id == payload.source_doc_id,
                                         StockDoc.doc_type == "pr").first():
            raise HTTPException(404, "طلب الشراء المصدر غير موجود")
    return src, dst


def _post_doc(db: Session, doc: StockDoc, user: User) -> None:
    """يرحّل حركات المستند على الأرصدة والدفعات ودفتر الحركات."""
    dtype = doc.doc_type
    for ln in doc.lines:
        item = _item(db, ln.item_id)
        cost = ln.unit_cost or item.unit_cost or 0
        if dtype == "grn":
            _add_batch(db, item.id, doc.to_warehouse_id, ln.quantity,
                       ln.batch_no, ln.expiry_date, cost)
            _post(db, item, doc.to_warehouse_id, "grn", ln.quantity, user, doc, ln,
                  note=doc.notes or f"إذن استلام {doc.doc_no}")
        elif dtype == "transfer":
            _post(db, item, doc.from_warehouse_id, "transfer_out", -ln.quantity,
                  user, doc, ln, department_id=doc.department_id,
                  note=doc.notes or f"تحويل {doc.doc_no}")
            _add_batch(db, item.id, doc.to_warehouse_id, ln.quantity,
                       ln.batch_no, ln.expiry_date, cost)
            _post(db, item, doc.to_warehouse_id, "transfer_in", ln.quantity,
                  user, doc, ln, note=f"تحويل وارد {doc.doc_no}")
        elif dtype == "issue":
            _post(db, item, doc.from_warehouse_id, "issue", -ln.quantity, user, doc,
                  ln, patient_id=doc.patient_id, department_id=doc.department_id,
                  note=doc.notes or f"صرف {doc.doc_no}")
        elif dtype == "return":
            _add_batch(db, item.id, doc.to_warehouse_id, ln.quantity,
                       ln.batch_no, ln.expiry_date, cost)
            _post(db, item, doc.to_warehouse_id, "return_in", ln.quantity, user, doc,
                  ln, patient_id=doc.patient_id, department_id=doc.department_id,
                  note=doc.notes or f"مرتجع {doc.doc_no}")
        elif dtype == "supplier_return":
            _post(db, item, doc.from_warehouse_id, "supplier_return", -ln.quantity,
                  user, doc, ln, note=doc.notes or f"مرتجع مورد {doc.doc_no}")
    # بعد الترحيل: انتهاء الصنف = أقرب دفعة، ورصيده = مجموع أرصدته
    for ln in doc.lines:
        item = _item(db, ln.item_id)
        _sync_item_expiry(db, item)
        item.quantity = _item_total(db, item.id)


# ===== المستودعات والفروع =====
@router.get("/warehouses", response_model=List[WarehouseOut],
            summary="قائمة المستودعات مع عدد الأصناف وإجماليها")
def list_warehouses(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _default_warehouse(db)   # أول زيارة ⇒ يظهر «المستودع الرئيسي» بدل قائمة فارغة
    out = []
    for wh in db.query(Warehouse).order_by(Warehouse.id).all():
        stats = (db.query(StockBalance)
                 .filter(StockBalance.warehouse_id == wh.id)
                 .with_entities(func.count(StockBalance.id),
                                func.coalesce(func.sum(StockBalance.quantity), 0))
                 .first())
        out.append(WarehouseOut(
            id=wh.id, name=wh.name, kind=wh.kind, location=wh.location,
            is_default=wh.is_default, is_active=wh.is_active,
            items_count=int(stats[0] or 0), total_quantity=int(stats[1] or 0),
            created_at=wh.created_at))
    return out


@router.post("/warehouses", response_model=WarehouseOut, status_code=201,
             summary="إضافة مستودع (الأول يصبح الافتراضي)")
def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db),
                     user: User = Depends(require_admin)):
    name = payload.name.strip()
    if db.query(Warehouse).filter(Warehouse.name == name).first():
        raise HTTPException(409, "اسم المستودع مستخدم مسبقًا")
    wh = Warehouse(name=name, kind=payload.kind, location=payload.location,
                   is_default=payload.is_default or not db.query(Warehouse).first())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return WarehouseOut(id=wh.id, name=wh.name, kind=wh.kind, location=wh.location,
                        is_default=wh.is_default, is_active=wh.is_active,
                        items_count=0, total_quantity=0, created_at=wh.created_at)


@router.put("/warehouses/{wh_id}", response_model=WarehouseOut,
            summary="تعديل مستودع (والافتراضي واحد فقط)")
def update_warehouse(wh_id: int, payload: WarehouseUpdate, db: Session = Depends(get_db),
                     _: User = Depends(require_admin)):
    wh = db.query(Warehouse).filter(Warehouse.id == wh_id).first()
    if not wh:
        raise HTTPException(404, "المستودع غير موجود")
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        clash = db.query(Warehouse).filter(Warehouse.name == data["name"].strip(),
                                           Warehouse.id != wh_id).first()
        if clash:
            raise HTTPException(409, "اسم المستودع مستخدم مسبقًا")
    if data.get("is_default"):
        for other in db.query(Warehouse).filter(Warehouse.id != wh_id).all():
            other.is_default = False
    for field, value in data.items():
        setattr(wh, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(wh)
    return WarehouseOut(id=wh.id, name=wh.name, kind=wh.kind, location=wh.location,
                        is_default=wh.is_default, is_active=wh.is_active,
                        items_count=0, total_quantity=0, created_at=wh.created_at)


@router.delete("/warehouses/{wh_id}", status_code=204, summary="حذف مستودع فارغ")
def delete_warehouse(wh_id: int, db: Session = Depends(get_db),
                     _: User = Depends(require_admin)):
    wh = db.query(Warehouse).filter(Warehouse.id == wh_id).first()
    if not wh:
        raise HTTPException(404, "المستودع غير موجود")
    used = db.query(StockBalance).filter(
        StockBalance.warehouse_id == wh_id, StockBalance.quantity != 0).first()
    if used:
        raise HTTPException(400, "لا يمكن حذف مستودع فيه أرصدة — صرّفها أو انقلها أولًا")
    if wh.is_default and db.query(Warehouse).count() > 1:
        raise HTTPException(400, "لا يمكن حذف المستودع الافتراضي — عيّن غيره افتراضيًا أولًا")
    db.query(StockBatch).filter(StockBatch.warehouse_id == wh_id,
                                StockBatch.quantity <= 0).delete()
    db.delete(wh)
    db.commit()
    return None


@router.get("/warehouses/{wh_id}/items", summary="أرصدة أصناف مستودع")
def warehouse_items(wh_id: int, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """كل صنف داخل المستودع برصيده وحدود إعادة طلبه."""
    wh = db.query(Warehouse).filter(Warehouse.id == wh_id).first()
    if not wh:
        raise HTTPException(404, "المستودع غير موجود")
    rows = (db.query(StockBalance, GeneralStockItem)
            .filter(StockBalance.warehouse_id == wh_id)
            .join(GeneralStockItem, GeneralStockItem.id == StockBalance.item_id)
            .order_by(GeneralStockItem.name).all())
    return [{
        "item_id": item.id, "code": item.code, "name": item.name, "unit": item.unit,
        "quantity": bal.quantity, "min_quantity": item.min_quantity,
        "reorder_point": item.reorder_point, "max_quantity": item.max_quantity,
        "unit_cost": item.unit_cost, "expiry_date": item.expiry_date,
        "value": round(bal.quantity * (item.unit_cost or 0), 2),
        "below_min": bal.quantity <= (item.min_quantity or 0),
    } for bal, item in rows]


# ===== بطاقة الصنف ودفتر الحركات =====
@router.get("/items/{item_id}/card", summary="بطاقة الصنف: الأرصدة والدفعات والحركات")
def item_card(item_id: int, limit: int = Query(50, ge=1, le=500),
              db: Session = Depends(get_db), _=Depends(get_current_user)):
    """تتبّع مسار الصنف: رصيده في كل مخزن + دفعاته + حركاته الأخيرة."""
    item = _item(db, item_id)
    balances = (db.query(StockBalance, Warehouse)
                .filter(StockBalance.item_id == item_id)
                .join(Warehouse, Warehouse.id == StockBalance.warehouse_id).all())
    moves = (db.query(GeneralStockMovement)
             .filter(GeneralStockMovement.item_id == item_id)
             .order_by(GeneralStockMovement.id.desc()).limit(limit).all())
    batches = (db.query(StockBatch)
               .filter(StockBatch.item_id == item_id, StockBatch.quantity > 0)
               .order_by(StockBatch.expiry_date.is_(None),
                         StockBatch.expiry_date.asc()).all())
    return {
        "item": {
            "id": item.id, "code": item.code, "name": item.name, "unit": item.unit,
            "category": item.category, "quantity": item.quantity,
            "min_quantity": item.min_quantity, "reorder_point": item.reorder_point,
            "max_quantity": item.max_quantity, "unit_cost": item.unit_cost,
            "storage_condition": item.storage_condition,
            "generic_name": item.generic_name, "trade_name": item.trade_name,
            "barcode": item.barcode, "supplier_name": item.supplier_name,
            "expiry_date": item.expiry_date,
            "value": round(item.quantity * (item.unit_cost or 0), 2),
        },
        "balances": [{"warehouse_id": w.id, "warehouse": w.name,
                      "quantity": b.quantity} for b, w in balances],
        "batches": [{"batch_no": b.batch_no, "warehouse_id": b.warehouse_id,
                     "quantity": b.quantity, "expiry_date": b.expiry_date,
                     "unit_cost": b.unit_cost} for b in batches],
        "movements": [_movement_out(db, m).model_dump() for m in moves],
    }


@router.get("/movements", response_model=List[GeneralStockMovementOut],
            summary="دفتر حركات المخزون العام")
def list_movements(item_id: Optional[int] = None, type: Optional[str] = None,
                   warehouse_id: Optional[int] = None,
                   limit: int = Query(100, ge=1, le=500),
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(GeneralStockMovement)
    if item_id:
        q = q.filter(GeneralStockMovement.item_id == item_id)
    if type:
        q = q.filter(GeneralStockMovement.type == type)
    if warehouse_id:
        q = q.filter(GeneralStockMovement.warehouse_id == warehouse_id)
    rows = q.order_by(GeneralStockMovement.id.desc()).limit(limit).all()
    return [_movement_out(db, m) for m in rows]


# ===== المستندات: إذن استلام · تحويل · صرف · مرتجع · جرد · شراء =====
@router.get("/docs", response_model=List[StockDocOut], summary="قائمة مستندات المخزون")
def list_docs(doc_type: Optional[str] = None, status: Optional[str] = None,
              warehouse_id: Optional[int] = None,
              limit: int = Query(50, ge=1, le=300),
              db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(StockDoc)
    if doc_type:
        q = q.filter(StockDoc.doc_type == doc_type)
    if status:
        q = q.filter(StockDoc.status == status)
    if warehouse_id:
        q = q.filter((StockDoc.from_warehouse_id == warehouse_id)
                     | (StockDoc.to_warehouse_id == warehouse_id))
    rows = q.order_by(StockDoc.id.desc()).limit(limit).all()
    return [_doc_out(db, d) for d in rows]


@router.get("/docs/{doc_id}", response_model=StockDocOut, summary="تفاصيل مستند")
def get_doc(doc_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    doc = db.query(StockDoc).filter(StockDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "المستند غير موجود")
    return _doc_out(db, doc)


@router.post("/docs", response_model=StockDocOut, status_code=201,
             summary="إنشاء مستند مخزون (استلام/تحويل/صرف/مرتجع/جرد/شراء)")
def create_doc(payload: StockDocCreate, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    """المستندات التشغيلية تُرحَّل فورًا؛ أما الجرد وطلبات الشراء فمسودّات."""
    src, dst = _validate(db, payload)
    doc = StockDoc(
        doc_type=payload.doc_type, doc_no=_next_doc_no(db, payload.doc_type),
        status="draft" if payload.doc_type in DRAFT_TYPES else "completed",
        from_warehouse_id=src.id if src else None,
        to_warehouse_id=dst.id if dst else None,
        vendor_id=payload.vendor_id, department_id=payload.department_id,
        patient_id=payload.patient_id, source_doc_id=payload.source_doc_id,
        reference=payload.reference, notes=payload.notes,
        needed_at=payload.needed_at, expected_at=payload.expected_at,
        created_by=user.username,
        completed_at=datetime.utcnow() if payload.doc_type in POSTING_TYPES else None)
    db.add(doc)
    db.flush()
    for ln in payload.lines:
        item = _item(db, ln.item_id)
        _seed_legacy_balance(db, item)
        db.add(StockDocLine(
            doc_id=doc.id, item_id=ln.item_id, quantity=ln.quantity,
            counted_quantity=ln.counted_quantity,
            unit_cost=ln.unit_cost if ln.unit_cost is not None else (item.unit_cost or 0),
            batch_no=ln.batch_no, expiry_date=ln.expiry_date, note=ln.note))
    db.flush()
    if doc.status == "completed":
        _post_doc(db, doc, user)
    db.commit()
    db.refresh(doc)
    return _doc_out(db, doc)


@router.post("/docs/{doc_id}/action", response_model=StockDocOut,
             summary="اعتماد/إلغاء/إغلاق مستند")
def doc_action(doc_id: int, payload: StockDocAction, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    """approve لطلبات وأوامر الشراء · cancel للمسودّة · complete لإغلاق الجرد."""
    doc = db.query(StockDoc).filter(StockDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "المستند غير موجود")
    action = payload.action.strip().lower()
    if action not in ("approve", "cancel", "complete"):
        raise HTTPException(400, "الإجراء يجب أن يكون approve أو cancel أو complete")
    if action == "approve":
        if doc.doc_type not in ("pr", "po"):
            raise HTTPException(400, "الاعتماد لطلبات وأوامر الشراء فقط")
        if doc.status != "draft":
            raise HTTPException(400, "لا يمكن اعتماد مستند ليس مسودّة")
        doc.status, doc.approved_by = "approved", user.username
    elif action == "cancel":
        if doc.status in ("completed", "cancelled"):
            raise HTTPException(400, "لا يمكن إلغاء مستند منجز أو ملغى")
        doc.status = "cancelled"
    else:
        # إغلاق الجرد: مقارنة العدّ الفعلي بالرصيد وقيد فرقه كحركة تسوية
        if doc.doc_type != "stocktake":
            raise HTTPException(400, "الإغلاق متاح لجلسات الجرد فقط")
        if doc.status != "draft":
            raise HTTPException(400, "جلسة الجرد أُغلقت من قبل")
        for ln in doc.lines:
            item = _item(db, ln.item_id)
            bal = _balance(db, item.id, doc.from_warehouse_id)
            counted = ln.counted_quantity if ln.counted_quantity is not None else bal.quantity
            ln.quantity, ln.counted_quantity = counted, counted
            delta = counted - bal.quantity
            if delta:
                if delta > 0:
                    _add_batch(db, item.id, doc.from_warehouse_id, delta,
                               ln.batch_no, ln.expiry_date, ln.unit_cost)
                _post(db, item, doc.from_warehouse_id, "adjust", delta, user, doc, ln,
                      note=doc.notes or f"تسوية جرد {doc.doc_no}")
            _sync_item_expiry(db, item)
            item.quantity = _item_total(db, item.id)
        doc.status, doc.approved_by = "completed", user.username
        doc.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return _doc_out(db, doc)


@router.post("/docs/{doc_id}/receive", response_model=StockDocOut, status_code=201,
             summary="استلام أمر شراء: يولّد إذن استلام ويورّد الكميات")
def receive_po(doc_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    po = db.query(StockDoc).filter(StockDoc.id == doc_id, StockDoc.doc_type == "po").first()
    if not po:
        raise HTTPException(404, "أمر الشراء غير موجود")
    if po.status == "completed":
        raise HTTPException(400, "هذا الأمر مستلَم مسبقًا")
    if po.status != "approved":
        raise HTTPException(400, "اعتمد أمر الشراء أولًا")
    wh = _default_warehouse(db)
    grn = StockDoc(doc_type="grn", doc_no=_next_doc_no(db, "grn"), status="completed",
                   to_warehouse_id=wh.id, vendor_id=po.vendor_id,
                   reference=po.reference, notes=po.notes, source_doc_id=po.id,
                   created_by=user.username, completed_at=datetime.utcnow())
    db.add(grn)
    db.flush()
    for ln in po.lines:
        item = _item(db, ln.item_id)
        _seed_legacy_balance(db, item)
        db.add(StockDocLine(doc_id=grn.id, item_id=ln.item_id, quantity=ln.quantity,
                            unit_cost=ln.unit_cost, batch_no=ln.batch_no,
                            expiry_date=ln.expiry_date, note=ln.note))
    db.flush()
    _post_doc(db, grn, user)
    po.status, po.completed_at = "completed", datetime.utcnow()
    db.commit()
    db.refresh(grn)
    return _doc_out(db, grn)


# ===== التقارير =====
def _line_cost(db: Session, mv: GeneralStockMovement) -> float:
    """تكلفة الحركة: تكلفة الدفعة إن سُجّلت، وإلا تكلفة الوحدة المرجّعة للصنف."""
    if mv.doc_id:
        ln = (db.query(StockDocLine)
              .filter(StockDocLine.doc_id == mv.doc_id,
                      StockDocLine.item_id == mv.item_id).first())
        if ln and ln.unit_cost:
            return ln.unit_cost
    item = db.query(GeneralStockItem).filter(GeneralStockItem.id == mv.item_id).first()
    return (item.unit_cost or 0) if item else 0.0


def _any_wh(db: Session, item_id: int) -> int:
    """مستودع واحد للصنف (لطبقات FIFO) — أول رصيد أو المستودع الافتراضي."""
    row = (db.query(StockBalance)
           .filter(StockBalance.item_id == item_id, StockBalance.quantity > 0)
           .order_by(StockBalance.warehouse_id).first())
    return row.warehouse_id if row else _default_warehouse(db).id


@router.get("/reports/reorder", summary="مستويات إعادة الطلب: ما يحتاج توريدًا")
def reorder_report(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """الأصناف عند حد الأمان أو دونه مع الكمية المقترحة للتوريد."""
    rows = (db.query(GeneralStockItem)
            .filter(GeneralStockItem.is_active.is_(True))
            .order_by(GeneralStockItem.name).all())
    out = []
    for it in rows:
        limit = it.min_quantity or 0
        if it.quantity > limit:
            continue
        target = it.reorder_point or it.max_quantity or (limit * 2)
        out.append({
            "item_id": it.id, "code": it.code, "name": it.name, "unit": it.unit,
            "quantity": it.quantity, "min_quantity": limit,
            "reorder_point": it.reorder_point, "max_quantity": it.max_quantity,
            "suggested_quantity": max(target - it.quantity, 0),
            "supplier_name": it.supplier_name, "unit_cost": it.unit_cost,
        })
    return out


@router.get("/reports/expiry", response_model=List[ExpiryAlertRow],
            summary="تنبيهات انتهاء الصلاحية على مستوى الدفعات")
def expiry_report(days: int = Query(90, ge=0, le=365), warehouse_id: Optional[int] = None,
                  db: Session = Depends(get_db), _=Depends(get_current_user)):
    """كل دفعة تنتهي خلال نافذة الأيام، مرتّبة بالأقرب انتهاءً (FEFO)."""
    now = datetime.utcnow()
    limit_date = now + timedelta(days=days)
    q = (db.query(StockBatch, GeneralStockItem, Warehouse)
         .filter(StockBatch.quantity > 0, StockBatch.expiry_date.isnot(None),
                 StockBatch.expiry_date <= limit_date)
         .join(GeneralStockItem, GeneralStockItem.id == StockBatch.item_id)
         .join(Warehouse, Warehouse.id == StockBatch.warehouse_id))
    if warehouse_id:
        q = q.filter(StockBatch.warehouse_id == warehouse_id)
    out = []
    for batch, item, wh in q.order_by(StockBatch.expiry_date.asc()).all():
        out.append(ExpiryAlertRow(
            item_id=item.id, item_name=item.name, code=item.code, warehouse=wh.name,
            quantity=batch.quantity, batch_no=batch.batch_no,
            expiry_date=batch.expiry_date, days_left=(batch.expiry_date - now).days,
            value=round(batch.quantity * (batch.unit_cost or 0), 2)))
    return out


@router.get("/reports/valuation", response_model=List[ValuationRow],
            summary="قيمة المخزون بالتكلفة المتوسطة وبطريقة FIFO")
def valuation_report(warehouse_id: Optional[int] = None, db: Session = Depends(get_db),
                     _: User = Depends(get_current_user)):
    """المتوسط = تكلفة مرجّحة بالاستلام، وFIFO = طبقات الدفعات المتبقية."""
    out = []
    for item in db.query(GeneralStockItem).filter(
            GeneralStockItem.is_active.is_(True)).order_by(GeneralStockItem.name).all():
        bq = db.query(StockBalance).filter(StockBalance.item_id == item.id)
        if warehouse_id:
            bq = bq.filter(StockBalance.warehouse_id == warehouse_id)
        qty = bq.with_entities(func.coalesce(func.sum(StockBalance.quantity), 0)).scalar() or 0
        if qty <= 0:
            continue
        recv = (db.query(GeneralStockMovement)
                .filter(GeneralStockMovement.item_id == item.id,
                        GeneralStockMovement.change > 0,
                        GeneralStockMovement.type.in_(("grn", "return_in")))
                .all())
        units = sum(m.change for m in recv) or 0
        avg = (round(sum(m.change * _line_cost(db, m) for m in recv) / units, 2)
               if units else (item.unit_cost or 0))
        left, fifo_val = qty, 0.0
        for batch in _fefo_batches(db, item.id, warehouse_id or _any_wh(db, item.id)):
            if left <= 0:
                break
            take = min(batch.quantity, left)
            fifo_val += take * (batch.unit_cost or avg)
            left -= take
        if left > 0:
            fifo_val += left * avg
        out.append(ValuationRow(
            item_id=item.id, item_name=item.name, code=item.code, quantity=qty,
            average_cost=avg, fifo_cost=round(fifo_val / qty, 2) if qty else 0.0,
            total_average=round(qty * avg, 2), total_fifo=round(fifo_val, 2)))
    return out


@router.get("/reports/slow-moving", response_model=List[SlowMovingRow],
            summary="الأصناف الراكدة والأكثر حركة")
def slow_moving_report(days: int = Query(90, ge=1, le=730),
                       db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """راكد = رصيده موجب ولم يُصرف منذ «days» يومًا؛ والترتيب للراكد ثم الأقل حركة."""
    now = datetime.utcnow()
    out = []
    for item in db.query(GeneralStockItem).filter(
            GeneralStockItem.is_active.is_(True)).order_by(GeneralStockItem.name).all():
        qty = _item_total(db, item.id)
        issued = (db.query(GeneralStockMovement)
                  .filter(GeneralStockMovement.item_id == item.id,
                          GeneralStockMovement.type.in_(("issue", "transfer_out",
                                                         "supplier_return")),
                          GeneralStockMovement.change < 0).all())
        received = (db.query(GeneralStockMovement)
                    .filter(GeneralStockMovement.item_id == item.id,
                            GeneralStockMovement.change > 0).all())
        last_issue = max((m.created_at for m in issued), default=None)
        days_since = (now - last_issue).days if last_issue else None
        out.append(SlowMovingRow(
            item_id=item.id, item_name=item.name, code=item.code, quantity=qty,
            issued_qty=abs(sum(m.change for m in issued)),
            received_qty=sum(m.change for m in received),
            last_issue_at=last_issue, days_since_issue=days_since,
            value=round(qty * (item.unit_cost or 0), 2),
            is_slow=bool(qty > 0 and (days_since is None or days_since >= days))))
    out.sort(key=lambda r: (not r.is_slow, -(r.issued_qty or 0)))
    return out


@router.get("/reports/summary", summary="ملخّص إدارة المخازن")
def ops_summary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """أرقام سريعة أعلى شاشة المخزون: المستودعات والمستندات والتنبيهات."""
    docs = (db.query(StockDoc.doc_type, StockDoc.status)
            .with_entities(StockDoc.doc_type, StockDoc.status).all())
    by_type = {}
    for dtype, status in docs:
        entry = by_type.setdefault(dtype, {"total": 0, "draft": 0, "completed": 0})
        entry["total"] += 1
        if status in entry:
            entry[status] += 1
    now = datetime.utcnow()
    soon = (db.query(StockBatch)
            .filter(StockBatch.quantity > 0, StockBatch.expiry_date.isnot(None),
                    StockBatch.expiry_date <= now + timedelta(days=90))
            .count())
    value = (db.query(StockBalance, GeneralStockItem)
             .join(GeneralStockItem, GeneralStockItem.id == StockBalance.item_id)
             .with_entities(func.coalesce(func.sum(
                 StockBalance.quantity * GeneralStockItem.unit_cost), 0.0)).scalar() or 0.0)
    return {
        "warehouses": db.query(Warehouse).count(),
        "items": db.query(GeneralStockItem).filter(
            GeneralStockItem.is_active.is_(True)).count(),
        "docs": by_type,
        "expiring_within_90": soon,
        "total_value": round(float(value), 2),
    }
