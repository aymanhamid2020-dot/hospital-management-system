"""كتالوج الصلاحيات ومحرك الصلاحيات (RBAC).

التصميم:
- الصلاحيات مفصولة إلى **قدرات** بمفتاح `module.action` (مثل `patients.edit`)
  بدل فحص «مدير/غير مدير» الثنائي.
- الكتالوج معرَّف هنا في الكود ويُزرع في جدول `permissions` عند الإقلاع،
  لكن **ربط الأدوار** بالصلاحيات يعيش في قاعدة البيانات ⇒ أي دور مخصّص
  أو أي صلاحية جديدة تُدار من الواجهة بلا إعادة نشر.
- لكل مستخدم استثناءات فردية (`UserPermission`) وقيمة `deny` تغلب `allow`.
- دور `admin` (is_super) يتجاوز كل شيء عمدًا حتى لا يُقفل المدير على نفسه.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Permission, Role, RolePermission, User, UserPermission

# ===== الكتالوج =====
# (key, module, name_ar, description, is_sensitive, default_roles)
PERMISSION_CATALOG: list[tuple] = [
    # --- المستخدمون والصلاحيات ---
    ("users.view", "المستخدمون والصلاحيات", "عرض المستخدمين", "قائمة المستخدمين وأدوارهم", False,
     ["admin", "hr"]),
    ("users.manage", "المستخدمون والصلاحيات", "إدارة المستخدمين",
     "إنشاء/تعطيل/تغيير كلمة مرور مستخدم", True, ["admin"]),
    ("roles.manage", "المستخدمون والصلاحيات", "إدارة الأدوار والصلاحيات",
     "إنشاء أدوار وربط الصلاحيات وتحديد الاستثناءات", True, ["admin"]),
    # --- المرضى ---
    ("patients.view", "المرضى", "عرض المرضى", "قائمة المرضى وملفاتهم", False,
     ["admin", "doctor", "receptionist", "nurse", "accountant"]),
    ("patients.edit", "المرضى", "تعديل بيانات المرضى", "إضافة وتعديل بيانات المريض", False,
     ["admin", "doctor", "receptionist", "nurse"]),
    ("patients.delete", "المرضى", "حذف المرضى", "حذف سجل المريض نهائيًا", True, ["admin"]),
    ("patients.merge", "المرضى", "دمج الملفات المكرّرة", "دمج ملفّي مريض في سجل واحد", True,
     ["admin"]),
    # --- المواعيد ---
    ("appointments.view", "المواعيد", "عرض المواعيد", "جدول المواعيد والوصول", False,
     ["admin", "doctor", "receptionist"]),
    ("appointments.manage", "المواعيد", "إدارة المواعيد", "حجز وتعديل وإلغاء المواعيد", False,
     ["admin", "doctor", "receptionist"]),
    # --- العيادات والأقسام ---
    ("clinics.view", "العيادات والأقسام", "عرض العيادات", "سجل العيادات وخدماتها ودوامها", False,
     ["admin", "doctor", "receptionist", "hr"]),
    ("clinics.manage", "العيادات والأقسام", "إدارة العيادات",
     "إنشاء العيادات وخدماتها وجداول دوامها وربطها بالأقسام", True, ["admin"]),
    ("departments.manage", "العيادات والأقسام", "إدارة الأقسام",
     "هيكل الأقسام وغرفها وكادرها وكتالوج خدماتها", True, ["admin"]),
    # --- السجلات الطبية ---
    ("records.view", "السجلات الطبية", "عرض السجلات الطبية",
     "التاريخ المرضي والزيارات والوصفات وخطة العلاج", False,
     ["admin", "doctor", "nurse"]),
    ("records.edit", "السجلات الطبية", "كتابة السجلات الطبية",
     "إضافة التشخيصات والملاحظات والوصفات", False, ["admin", "doctor"]),
    ("records.delete", "السجلات الطبية", "حذف السجلات الطبية", "حذف إدخالات السجل", True,
     ["admin"]),
    # --- الصيدلية ---
    ("pharmacy.view", "الصيدلية", "عرض الصيدلية", "المخزون والصرف والوصفات", False,
     ["admin", "doctor", "pharmacist"]),
    ("pharmacy.manage", "الصيدلية", "إدارة الصيدلية",
     "إضافة الأدوية والصرف والمرتجعات", False, ["admin", "pharmacist"]),
    ("pharmacy.price", "الصيدلية", "تعديل أسعار الأدوية", "تعديل سعر بيع الدواء", True,
     ["admin"]),
    # --- المختبر والأشعة ---
    ("lab.view", "المختبر والأشعة", "عرض المختبر والأشعة", "الطلبات والنتائج والتقارير", False,
     ["admin", "doctor", "lab"]),
    ("lab.manage", "المختبر والأشعة", "إدارة المختبر والأشعة",
     "تسجيل الطلبات وإدخال النتائج واعتماد التقارير", False, ["admin", "lab"]),
    # --- الفواتير والمبيعات ---
    ("sales.view", "المبيعات", "عرض المبيعات", "الفواتير والصرف والتحصيل", False,
     ["admin", "receptionist", "accountant", "cashier"]),
    ("sales.manage", "المبيعات", "إدارة المبيعات", "إنشاء الفواتير وتحصيل الدفعات", False,
     ["admin", "receptionist", "cashier"]),
    ("sales.discount", "المبيعات", "منح الخصومات", "تطبيق خصم على الفاتورة", True,
     ["admin", "cashier"]),
    ("sales.refund", "المبيعات", "الاسترداد والإشعار الدائن", "إصدار إشعار دائن أو استرداد", True,
     ["admin"]),
    ("sales.cashclose", "المبيعات", "إغلاق وردية الكاشير", "فتح/إغلاق وردية ومطابقة النقد", True,
     ["admin", "cashier"]),
    # --- المحاسبة ---
    ("accounting.view", "المحاسبة", "عرض المحاسبة", "الحسابات والمدينون والدفتر العام", False,
     ["admin", "accountant"]),
    ("accounting.manage", "المحاسبة", "إدارة المحاسبة", "القيود المزدوجة والموردون والأعمار", True,
     ["admin", "accountant"]),
    # --- المخزون العام ---
    ("stock.view", "المخزون العام", "عرض المخزون", "المستودعات وحركات المخزون", False,
     ["admin", "pharmacist", "storekeeper"]),
    ("stock.manage", "المخزون العام", "إدارة المخزون", "التوريد والجرد والتحويلات", False,
     ["admin", "storekeeper"]),
    # --- الموظفون ---
    ("staff.view", "الموظفون", "عرض الموظفين", "ملفات الموظفين وكادر الأقسام", False,
     ["admin", "hr"]),
    ("staff.manage", "الموظفون", "إدارة الموظفين", "إضافة الموظفين وتعديل ملفاتهم", True,
     ["admin", "hr"]),
    ("hr.manage", "الموظفون", "إدارة الموارد البشرية والرواتب", "ملف الموظف والوثائق والرواتب",
     True, ["admin", "hr"]),
    # --- التقارير والتدقيق ---
    ("reports.view", "التقارير", "عرض التقارير", "تقارير مالية وإحصائية", False,
     ["admin", "accountant", "hr"]),
    ("reports.export", "التقارير", "تصدير التقارير", "تصدير PDF/CSV للتقارير", True,
     ["admin", "accountant"]),
    ("audit.view", "التقارير", "سجل التدقيق", "مراجعة سجل العمليات الحسّاسة", True, ["admin"]),
    # --- الإعدادات ---
    ("settings.manage", "الإعدادات", "إدارة إعدادات النظام",
     "النسخ الاحتياطي والإعدادات العامة", True, ["admin"]),
]

# الأدوار الافتراضية: (key, name_ar, description, is_super)
DEFAULT_ROLES: list[tuple] = [
    ("admin", "مدير النظام", "صلاحية كاملة على كل شيء", True),
    ("doctor", "طبيب", "مرضى ومواعيد وسجلات طبية ووصفات", False),
    ("receptionist", "موظف استقبال", "مرضى ومواعيد وفوترة أساسية", False),
    ("nurse", "ممرّض", "مرضى وسجلات طبية ووصفات بلا تشخيص", False),
    ("accountant", "محاسب", "المبيعات والمحاسبة والتقارير", False),
    ("cashier", "كاشير", "نقطة البيع والتحصيل وإغلاق الوردية", False),
    ("pharmacist", "صيدلي", "الصيدلية والمخزون", False),
    ("lab", "فني مختبر/أشعة", "طلبات المختبر وإدخال النتائج", False),
    ("storekeeper", "أمين مخزون", "المستودعات وحركات المخزون", False),
    ("hr", "موارد بشرية", "ملفات الموظفين والرواتب والتقارير", False),
]

# خرائط تعويض لأدوار قديمة بحروف متبقية من نظام التعداد المغلق
# ملاحظة أمنية مهمة: عمود Enum في SQLAlchemy كان يخزّن **اسم** التعداد
# (ADMIN) لا قيمته (admin). فإن لم تُطابَق الأسماء الكبيرة لهبط المدير العام
# إلى موظف استقبال بلا خطأ ظاهر = انخفاض صلاحيات صامت.
_LEGACY_ROLE_MAP = {
    "موظف استقبال": "receptionist",
    "موظف": "receptionist",
    "ADMIN": "admin", "DOCTOR": "doctor", "RECEPTIONIST": "receptionist",
    "CASHIER": "cashier", "ACCOUNTANT": "accountant", "PHARMACIST": "pharmacist",
    "NURSE": "nurse", "HR": "hr", "USER": "receptionist", "EMPLOYEE": "receptionist",
    "STAFF": "receptionist", "MANAGER": "admin",
}

ALL_PERMISSION_KEYS: list[str] = [row[0] for row in PERMISSION_CATALOG]
PERMISSION_MODULES: list[str] = []
for _row in PERMISSION_CATALOG:
    if _row[1] not in PERMISSION_MODULES:
        PERMISSION_MODULES.append(_row[1])


def normalize_role_key(raw) -> str:
    """يحوّل أي قيمة دور قديمة (تعداد أو نص حر) إلى مفتاح دور معروف.

    المطابقة متدرّجة: مطابقة تامة ← خريطة القيم القديمة ← مطابقة حالة-غير
    حاسمة (ADMIN→admin) ← قيمة Least-privilege افتراضية (receptionist).
    """
    value = str(getattr(raw, "value", raw) or "").strip()
    if not value:
        return "receptionist"
    known = {r[0] for r in DEFAULT_ROLES}
    if value in known:
        return value
    if value in _LEGACY_ROLE_MAP:
        return _LEGACY_ROLE_MAP[value]
    lowered = value.lower()
    if lowered in known:
        return lowered
    if lowered in _LEGACY_ROLE_MAP:
        return _LEGACY_ROLE_MAP[lowered]
    if value.replace(" ", "_") in known:
        return value.replace(" ", "_")
    return "receptionist"


def default_permissions_for(role_key: str) -> list[str]:
    """الصلاحيات الافتراضية لدور — نفس القواعد المستخدمة عند الزرع."""
    if role_key == "admin":
        return list(ALL_PERMISSION_KEYS)
    return [row[0] for row in PERMISSION_CATALOG if role_key in row[5]]


def seed_permissions(db: Session) -> int:
    """يزرع/يحدّث الكتالوج في جدول permissions. آمن للتكرار (idempotent)."""
    added = 0
    for key, module, name_ar, desc, sensitive, _roles in PERMISSION_CATALOG:
        row = db.query(Permission).filter(Permission.key == key).first()
        if row is None:
            db.add(Permission(key=key, name_ar=name_ar, module=module,
                              description=desc, is_sensitive=sensitive))
            added += 1
        else:
            if row.name_ar != name_ar or row.module != module:
                row.name_ar, row.module = name_ar, module
            if row.is_sensitive != sensitive:
                row.is_sensitive = sensitive
    return added


def seed_roles(db: Session) -> int:
    """يزرع الأدوار الافتراضية وربطها بصلاحياتها. لا يمسّ الأدوار المخصّصة."""
    created = 0
    perms = {p.key: p for p in db.query(Permission).all()}
    for key, name_ar, desc, is_super in DEFAULT_ROLES:
        role = db.query(Role).filter(Role.key == key).first()
        if role is None:
            role = Role(key=key, name_ar=name_ar, description=desc,
                        is_system=True, is_super=is_super)
            db.add(role)
            db.flush()
            created += 1
        for pkey in default_permissions_for(key):
            perm = perms.get(pkey)
            if perm is None:
                continue
            if not db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id).first():
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    return created


def seed_rbac(db: Session) -> tuple:
    """الزرع الكامل: الصلاحيات ثم الأدوار. يُستدعى عند الإقلاع."""
    added = seed_permissions(db)
    db.flush()
    created = seed_roles(db)
    db.flush()
    return added, created


# ===== محرك الفحص =====
def db_role_fallback(key) -> Role:
    """كائن دور افتراضي للعرض فقط (لا يُحفظ) إن لم يكن الدور موجودًا."""
    norm = normalize_role_key(key)
    meta = next((r for r in DEFAULT_ROLES if r[0] == norm), None)
    return Role(key=norm, name_ar=meta[1] if meta else norm,
                description=meta[2] if meta else None,
                is_system=True, is_super=bool(meta and meta[3]))


def effective_permissions(db: Session, user: User) -> set:
    """الصلاحيات الفعلية = صلاحيات الدور + الاستثناءات الفردية (deny يغلب)."""
    role = getattr(user, "role_row", None) or db_role_fallback(user.role)
    if role.is_super:
        return set(ALL_PERMISSION_KEYS)
    granted = {rp.permission.key for rp in role.permissions
               if rp.permission is not None}
    for override in user.permission_overrides:
        if override.permission is None:
            continue
        if override.effect == "deny":
            granted.discard(override.permission.key)
        else:
            granted.add(override.permission.key)
    return granted


def user_permissions(db: Session, user: User) -> list:
    return sorted(effective_permissions(db, user))


def has_perm(db: Session, user: User, key: str) -> bool:
    return key in effective_permissions(db, user)


def has_any_perm(db: Session, user: User, keys) -> bool:
    perms = effective_permissions(db, user)
    return any(k in perms for k in keys)


def require_perm(*keys: str):
    """Dependency factory: يتطلّب **أي واحدة** من الصلاحيات المذكورة.

    مثال: `require_perm("sales.manage")` أو `require_perm("lab.view", "lab.manage")`.
    """
    def checker(current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> User:
        if not has_any_perm(db, current_user, keys):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="لا تملك الصلاحية المطلوبة: " + " أو ".join(keys),
            )
        return current_user
    return checker


def require_perm_all(*keys: str):
    """Dependency factory: يتطلّب **كل** الصلاحيات المذكورة معًا."""
    def checker(current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> User:
        perms = effective_permissions(db, current_user)
        missing = [k for k in keys if k not in perms]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="صلاحيات ناقصة: " + "، ".join(missing),
            )
        return current_user
    return checker


# استيراد متأخر مقصود لتفادي الدورة مع app.auth
from app.auth import get_current_user  # noqa: E402
