"""تصدير/استيراد CSV للبيانات الأساسية — محرّك واحد يخدم عدّة قوائم.

نفس نمط المرضى (`/patients/export.csv` + `/patients/import`) لكن بمحرّك
موحّد يضيف الأصناف والموردين والأقسام والمستودعات والأدوية، فبدل تكرار
المنطق في كل راوتر: مواصفة لكل مورد (أعمدة + مفتاح تفرّد + مخطّط إنشاء)
وتصدير/قالب/استيراد واحد يقرأ منها.

الاستيراد «دمج» (upsert) لا «إضافة فقط»: الصف الموجود بنفس المفتاح يُحدَّث
والم الجديد يُضاف، مع تقرير مفصّل (مضاف/محدَّث/متجاوَز/أخطاء بالسطر).
"""
import csv as _csv
import io as _io
from datetime import datetime
from typing import Callable, List

from fastapi import (APIRouter, Depends, File, HTTPException, UploadFile)
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Department, GeneralStockItem, Medication, User, Vendor, Warehouse,
)
from app.schemas import (
    DepartmentCreate, GeneralStockItemCreate, MedicationCreate, VendorCreate,
    WarehouseCreate,
)

router = APIRouter(prefix="/exchange", tags=["CSV Exchange"])

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
DATE_FMTS = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y")


# ===== أدوات التحويل =====
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1256"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "تعذّر قراءة ترميز الملف — احفظه UTF-8")


def _date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"تاريخ غير صالح: {value}")


def _number(value, cast, field: str, default=0):
    text = (str(value) if value is not None else "").strip().replace(",", "")
    if not text:
        return default
    try:
        return cast(float(text) if cast is float else int(float(text)))
    except (TypeError, ValueError):
        raise HTTPException(400, f"قيمة غير صالحة للحقل «{field}»: {value}")


def _bool(value, default=True):
    text = (str(value) if value is not None else "").strip().lower()
    if text == "":
        return default
    return text not in ("0", "false", "no", "off", "لا")


def _mapping(headers: List[str], spec: "Spec") -> dict:
    """يربط ترويسة الملف (عربي/إنجليزي) بالحقل الداخلي."""
    out = {}
    for raw in headers:
        key = (raw or "").strip().lstrip("﻿")
        if not key:
            continue
        field = spec.aliases.get(key.lower()) or spec.aliases.get(key)
        if field is None and key in spec.columns:
            field = key
        if field:
            out[key] = field
    return out


def _pick(row: dict, mapping: dict) -> dict:
    """يحوّل صف CSV إلى {حقل داخلي: نص} بلا الخانات الفارغة."""
    return {field: str(row[key]).strip() for key, field in mapping.items()
            if row.get(key) is not None and str(row[key]).strip() != ""}


def _csv_response(headers: List[str], rows: List[list], filename: str) -> Response:
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class Spec:
    """وصف مورد واحد: أعمدته ومفتاح تفرّده وطريقة إنشاء صف منه."""

    def __init__(self, key, label, model, columns, unique, aliases, build,
                 sample, filename):
        self.key = key
        self.label = label
        self.model = model
        self.columns = columns            # [(ترويسة, حقل)]
        self.unique = unique              # حقل التفرّد (الكود/الرقم)
        self.aliases = aliases            # {ترويسة عربية/إنجليزية: حقل}
        self.build = build                # (db, values) -> (row, created)
        self.sample = sample
        self.filename = filename

    @property
    def headers(self) -> List[str]:
        return [head for head, _ in self.columns]


# ===== بناة الصفوف =====
def _build_item(db: Session, v: dict):
    payload = {
        "code": v.get("code", ""), "name": v.get("name", ""),
        "category": v.get("category") or "medical_supplies",
        "unit": v.get("unit") or "قطعة",
        "warehouse": v.get("warehouse") or "main",
        "quantity": _number(v.get("quantity"), int, "الكمية", 0),
        "min_quantity": _number(v.get("min_quantity"), int, "حد الأمان", 0),
        "reorder_point": _number(v.get("reorder_point"), int, "نقطة إعادة الطلب", 0),
        "max_quantity": _number(v.get("max_quantity"), int, "الحد الأقصى", 0),
        "unit_cost": _number(v.get("unit_cost"), float, "تكلفة الوحدة", 0.0),
        "expiry_date": _date(v.get("expiry_date", "")),
        "generic_name": v.get("generic_name") or None,
        "trade_name": v.get("trade_name") or None,
        "barcode": v.get("barcode") or None,
        "storage_condition": v.get("storage_condition") or None,
        "supplier_name": v.get("supplier_name") or None,
        "is_active": _bool(v.get("is_active"), True),
    }
    try:
        item = GeneralStockItemCreate(**payload)
    except ValidationError as e:
        err = e.errors()[0]
        raise ValueError(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
    row = db.query(GeneralStockItem).filter(
        GeneralStockItem.code == item.code).first()
    if row is None:
        return GeneralStockItem(**{f: getattr(item, f)
                                   for f in GeneralStockItemCreate.model_fields}), True
    for field, value in payload.items():        # الدمج لا يمسّ الرصيد ولا الموقع
        if field in ("quantity", "warehouse"):
            continue
        setattr(row, field, value)
    return row, False


def _build_medication(db: Session, v: dict):
    payload = {
        "code": v.get("code", ""), "name": v.get("name", ""),
        "unit": v.get("unit") or "علبة",
        "quantity": _number(v.get("quantity"), int, "الكمية", 0),
        "price": _number(v.get("price"), float, "السعر", 0.0),
        "min_quantity": _number(v.get("min_quantity"), int, "حد التنبيه", 10),
        "expiry_date": _date(v.get("expiry_date", "")),
    }
    try:
        med = MedicationCreate(**payload)
    except ValidationError as e:
        err = e.errors()[0]
        raise ValueError(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
    row = db.query(Medication).filter(Medication.code == med.code).first()
    if row is None:
        return Medication(**{f: getattr(med, f)
                              for f in MedicationCreate.model_fields}), True
    for field, value in payload.items():
        if field != "quantity":                  # الرصيد له دفتر حركاته
            setattr(row, field, value)
    return row, False


def _build_vendor(db: Session, v: dict):
    payload = {
        "code": v.get("code", ""), "name": v.get("name", ""),
        "contact_name": v.get("contact_name") or None,
        "phone": v.get("phone") or None, "email": v.get("email") or None,
        "tax_number": v.get("tax_number") or None,
        "opening_balance": _number(v.get("opening_balance"), float,
                                   "الرصيد الافتتاحي", 0.0),
    }
    try:
        ven = VendorCreate(**payload)
    except ValidationError as e:
        err = e.errors()[0]
        raise ValueError(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
    row = (db.query(Vendor)
           .filter((Vendor.code == ven.code) | (Vendor.name == ven.name)).first())
    if row is None:
        return Vendor(**{f: getattr(ven, f) for f in VendorCreate.model_fields}), True
    for field, value in payload.items():
        if field in ("code", "name", "opening_balance"):
            continue
        setattr(row, field, value)
    return row, False


def _build_department(db: Session, v: dict):
    name = v.get("name", "")
    payload = {"name": name, "description": v.get("description") or None,
               "floor": v.get("floor") or None}
    try:
        dep = DepartmentCreate(**payload)
    except ValidationError as e:
        err = e.errors()[0]
        raise ValueError(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
    row = db.query(Department).filter(Department.name == dep.name).first()
    if row is None:
        return Department(**{f: getattr(dep, f)
                             for f in DepartmentCreate.model_fields}), True
    for field, value in payload.items():
        if field != "name":
            setattr(row, field, value)
    return row, False


def _build_warehouse(db: Session, v: dict):
    name = v.get("name", "")
    payload = {"name": name, "kind": v.get("kind") or "main",
               "location": v.get("location") or None}
    try:
        wh = WarehouseCreate(**payload)
    except ValidationError as e:
        err = e.errors()[0]
        raise ValueError(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
    row = db.query(Warehouse).filter(Warehouse.name == wh.name).first()
    if row is None:
        is_first = not db.query(Warehouse).first()
        return Warehouse(name=wh.name, kind=wh.kind, location=wh.location,
                         is_default=is_first), True
    row.kind, row.location = wh.kind, wh.location
    return row, False


# ===== المواصفات =====
SPECS = {
    "items": Spec(
        "items", "أصناف المخزون العام", GeneralStockItem,
        [("الكود", "code"), ("اسم الصنف", "name"), ("التصنيف", "category"),
         ("الوحدة", "unit"), ("الكمية", "quantity"), ("حد الأمان", "min_quantity"),
         ("نقطة إعادة الطلب", "reorder_point"), ("الحد الأقصى", "max_quantity"),
         ("تكلفة الوحدة", "unit_cost"), ("الاسم العلمي", "generic_name"),
         ("الاسم التجاري", "trade_name"), ("الباركود", "barcode"),
         ("شروط التخزين", "storage_condition"), ("المورد", "supplier_name"),
         ("تاريخ الانتهاء", "expiry_date"), ("نشط", "is_active")],
        "code",
        {"code": "code", "الكود": "code", "رمز الصنف": "code", "كود الصنف": "code",
         "name": "name", "الاسم": "name", "اسم الصنف": "name", "اسم المادة": "name",
         "category": "category", "الفئة": "category", "التصنيف": "category",
         "unit": "unit", "الوحدة": "unit",
         "quantity": "quantity", "الكمية": "quantity", "الرصيد": "quantity",
         "min_quantity": "min_quantity", "حد الأمان": "min_quantity",
         "الحد الأدنى": "min_quantity",
         "reorder_point": "reorder_point", "نقطة إعادة الطلب": "reorder_point",
         "max_quantity": "max_quantity", "الحد الأقصى": "max_quantity",
         "unit_cost": "unit_cost", "تكلفة الوحدة": "unit_cost", "السعر": "unit_cost",
         "generic_name": "generic_name", "الاسم العلمي": "generic_name",
         "trade_name": "trade_name", "الاسم التجاري": "trade_name",
         "barcode": "barcode", "الباركود": "barcode",
         "storage_condition": "storage_condition", "شروط التخزين": "storage_condition",
         "supplier_name": "supplier_name", "المورد": "supplier_name",
         "expiry_date": "expiry_date", "تاريخ الانتهاء": "expiry_date",
         "الانتهاء": "expiry_date",
         "is_active": "is_active", "نشط": "is_active"},
        _build_item,
        {"code": "GS-001", "name": "قفازات فحص", "category": "medical_supplies",
         "unit": "علبة", "quantity": "100", "min_quantity": "20",
         "reorder_point": "60", "max_quantity": "200", "unit_cost": "18.5",
         "storage_condition": "دراجة عادية", "expiry_date": "2027-12-31"},
        "stock_items.csv"),

    "medications": Spec(
        "medications", "الأدوية", Medication,
        [("الكود", "code"), ("الاسم", "name"), ("الوحدة", "unit"),
         ("الكمية", "quantity"), ("السعر", "price"), ("حد التنبيه", "min_quantity"),
         ("تاريخ الانتهاء", "expiry_date")],
        "code",
        {"code": "code", "الكود": "code", "الباركود": "code",
         "name": "name", "الاسم": "name", "اسم الدواء": "name",
         "unit": "unit", "الوحدة": "unit",
         "quantity": "quantity", "الكمية": "quantity",
         "price": "price", "السعر": "price", "سعر البيع": "price",
         "min_quantity": "min_quantity", "حد التنبيه": "min_quantity",
         "الحد الأدنى": "min_quantity",
         "expiry_date": "expiry_date", "تاريخ الانتهاء": "expiry_date",
         "الانتهاء": "expiry_date"},
        _build_medication,
        {"code": "MED-001", "name": "بنادول", "unit": "علبة",
         "quantity": "50", "price": "12.5", "min_quantity": "10",
         "expiry_date": "2028-01-31"},
        "medications.csv"),

    "vendors": Spec(
        "vendors", "الموردون", Vendor,
        [("الرمز", "code"), ("الاسم", "name"), ("جهة الاتصال", "contact_name"),
         ("الهاتف", "phone"), ("البريد", "email"), ("الرقم الضريبي", "tax_number"),
         ("الرصيد الافتتاحي", "opening_balance"), ("نشط", "is_active")],
        "code",
        {"code": "code", "الرمز": "code", "كود المورد": "code",
         "name": "name", "الاسم": "name", "اسم المورد": "name",
         "contact_name": "contact_name", "جهة الاتصال": "contact_name",
         "phone": "phone", "الهاتف": "phone", "الجوال": "phone",
         "email": "email", "البريد": "email", "البريد الإلكتروني": "email",
         "tax_number": "tax_number", "الرقم الضريبي": "tax_number",
         "opening_balance": "opening_balance", "الرصيد الافتتاحي": "opening_balance",
         "is_active": "is_active", "نشط": "is_active"},
        _build_vendor,
        {"code": "V-001", "name": "شركة الإمداد الطبي", "contact_name": "أ. خالد",
         "phone": "0500000000", "email": "sales@example.com", "tax_number": "3000123"},
        "vendors.csv"),

    "departments": Spec(
        "departments", "الأقسام", Department,
        [("اسم القسم", "name"), ("الوصف", "description"), ("الدور", "floor")],
        "name",
        {"name": "name", "الاسم": "name", "اسم القسم": "name", "القسم": "name",
         "description": "description", "الوصف": "description",
         "floor": "floor", "الدور": "floor", "الطابق": "floor"},
        _build_department,
        {"name": "قسم العيادات", "description": "وصف القسم", "floor": "الأرضي"},
        "departments.csv"),

    "warehouses": Spec(
        "warehouses", "المستودعات", Warehouse,
        [("الاسم", "name"), ("النوع", "kind"), ("الموقع", "location"),
         ("نشط", "is_active")],
        "name",
        {"name": "name", "الاسم": "name", "اسم المستودع": "name",
         "kind": "kind", "النوع": "kind", "نوع المستودع": "kind",
         "location": "location", "الموقع": "location",
         "is_active": "is_active", "نشط": "is_active"},
        _build_warehouse,
        {"name": "مخزن الطوارئ", "kind": "emergency", "location": "الدور الأول"},
        "warehouses.csv"),
}


# ===== المسارات =====
@router.get("/resources", summary="قائمة الموارد المتاحة للتصدير/الاستيراد")
def list_resources(_: User = Depends(get_current_user)):
    """تغذّي الواجهة الأزرار، فتبقى القائمة في مكان واحد لا مكرّرًا في الشاشات."""
    return [{"key": key, "label": spec.label, "filename": spec.filename,
             "headers": spec.headers, "unique": spec.unique}
            for key, spec in SPECS.items()]


def _spec(key: str) -> Spec:
    spec = SPECS.get(key)
    if not spec:
        raise HTTPException(404, f"مورد غير مدعوم: {key} "
                                 f"(المتاح: {', '.join(SPECS)})")
    return spec


def _cell(spec: Spec, row, field: str):
    val = getattr(row, field, None)
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return getattr(val, "value", val)


@router.get("/{resource}/export.csv", summary="تصدير قائمة إلى CSV (Excel)")
def export_csv(resource: str, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    """تصدير كامل القائمة بترميز UTF-8 + BOM ليُفتح عربيًا في Excel مباشرة."""
    spec = _spec(resource)
    rows = []
    for row in db.query(spec.model).order_by(spec.model.id.asc()).all():
        rows.append([_cell(spec, row, field) for _, field in spec.columns])
    return _csv_response(spec.headers, rows, spec.filename)


@router.get("/{resource}/template.csv", summary="قالب الاستيراد (ترويسة + صف مثال)")
def template_csv(resource: str, _: User = Depends(get_current_user)):
    """قالب جاهز يُملأ ثم يُستورد — يضمن تطابق العناوين فيفهم الملف كل الأعمدة."""
    spec = _spec(resource)
    sample = [spec.sample.get(field, "") for _, field in spec.columns]
    return _csv_response(spec.headers, [sample],
                         f"template_{spec.filename}")


@router.post("/{resource}/import", summary="استيراد/دمج من ملف CSV (المدير)")
async def import_csv(
    resource: str,
    file: UploadFile = File(..., description="ملف CSV — UTF-8 أو cp1256"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """دمج دفعة صفوف: الموجود بنفس المفتاح يُحدَّث والجديد يُضاف.

    كل صف يُعزل عن غيره: خطأ صف لا يوقف الدفعة، وكتابته في تقرير الأخطاء
    برقم السطر (السطر 1 = العناوين).
    """
    spec = _spec(resource)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "الملف فارغ")
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, "حجم الملف يتجاوز 5MB")
    text = _decode(raw)
    try:
        reader = _csv.DictReader(_io.StringIO(text))
        rows = list(reader)
        headers = reader.fieldnames or []
    except _csv.Error as e:
        raise HTTPException(400, f"ملف CSV غير صالح: {e}")
    if not headers:
        raise HTTPException(400, "الملف لا يحتوي على صف عناوين")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"عدد الصفوف يتجاوز {MAX_ROWS}")

    mapping = _mapping(headers, spec)
    if not mapping:
        raise HTTPException(400, "لا يوجد عمود معروف — نزّل القالب من زر «📄 قالب»")
    key_field = spec.unique
    if not any(field == key_field for field in mapping.values()):
        raise HTTPException(400, f"الملف ينقصه عمود المفتاح «{key_field}»")

    created = updated = skipped = 0
    errors: List[dict] = []
    for idx, row in enumerate(rows, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue
        values = _pick(row, mapping)
        if not values.get(key_field):
            skipped += 1
            if len(errors) < 50:
                errors.append({"row": idx, "error": f"«{key_field}» فارغ — تخطّي"})
            continue
        try:
            row, is_new = spec.build(db, values)
        except ValueError as e:                 # خطأ في صف واحد: لا يوقف الدفعة
            skipped += 1
            if len(errors) < 50:
                errors.append({"row": idx, "error": str(e)})
            continue
        except HTTPException as e:
            skipped += 1
            if len(errors) < 50:
                errors.append({"row": idx, "error": e.detail})
            continue
        if is_new:
            db.add(row)                        # الجديد فقط يُضاف (الموجود يُعدَّل)
        created += 1 if is_new else 0
        updated += 0 if is_new else 1
    db.commit()
    return {"resource": resource, "label": spec.label, "created": created,
            "updated": updated, "skipped": skipped, "errors": errors}
