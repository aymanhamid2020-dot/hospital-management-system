"""واجهة إدارة الأدوار والصلاحيات (RBAC).

نموذج الصلاحيات: **كتالوج** صلاحيات مفصولة + **أدوار** قابلة للإنشاء
+ ربط أدوار بصلاحيات + **استثناءات** فردية على مستوى المستخدم.

حماية الكتابة: `roles.manage` (أو دور المدير العام). القراءة متاحة لكل
مستخدم مسجّل حتى تبني الواجهة قائمتها.
"""
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import (
    Permission, Role, RolePermission, User, UserPermission,
)
from app.permissions import (
    ALL_PERMISSION_KEYS, PERMISSION_MODULES, effective_permissions, has_perm,
    normalize_role_key,
)

router = APIRouter(prefix="/permissions", tags=["Roles & Permissions"])

_SLUG_RE = re.compile(r"[^\w؀-ۿ]+", re.UNICODE)


def _slugify(text: str) -> str:
    """يحوّل اسم الدور إلى مفتاح صالح: يحافظ على العربية (مقروء) وينظّف الرموز."""
    base = _SLUG_RE.sub("_", str(text or "").strip()).strip("_")
    return base or "role"


# ===== مخططات الإدخال/الإخراج =====
class RoleIn(BaseModel):
    key: Optional[str] = Field(None, max_length=40, description="يُولَّد من الاسم إن تُرك فارغًا")
    name_ar: str = Field(..., min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=255)
    permissions: List[str] = Field(default_factory=list)
    copy_from: Optional[str] = Field(None, max_length=40,
                                     description="انسخ صلاحيات دور موجود بدل التحديد اليدوي")


class RoleUpdate(BaseModel):
    name_ar: Optional[str] = Field(None, min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class RolePermissionsIn(BaseModel):
    permissions: List[str] = Field(default_factory=list,
                                   description="مفاتيح الصلاحيات المعطاة للدور")


class UserOverrideIn(BaseModel):
    permission: str = Field(..., max_length=60)
    effect: str = Field("deny", description="allow | deny")
    note: Optional[str] = Field(None, max_length=200)


class RoleOut(BaseModel):
    id: int
    key: str
    name_ar: str
    description: Optional[str] = None
    is_system: bool
    is_super: bool
    is_active: bool
    permissions: List[str] = []
    users_count: int = 0
    can_delete: bool = True


class PermissionOut(BaseModel):
    key: str
    name_ar: str
    module: str
    description: Optional[str] = None
    is_sensitive: bool


class UserAccessOut(BaseModel):
    """صلاحيات مستخدم: من الدور + الاستثناءات + الفعلي."""
    user_id: int
    username: str
    full_name: str
    role: str
    role_name: Optional[str] = None
    role_permissions: List[str] = []
    overrides: List[Dict] = []
    effective: List[str] = []


# ===== أدوات =====
def _role_out(db: Session, role: Role) -> RoleOut:
    perms = sorted({rp.permission.key for rp in role.permissions
                    if rp.permission is not None})
    return RoleOut(
        id=role.id, key=role.key, name_ar=role.name_ar, description=role.description,
        is_system=role.is_system, is_super=role.is_super, is_active=role.is_active,
        permissions=perms, users_count=len(role.users),
        can_delete=not role.is_system and not role.users)


def _perm_or_404(db: Session, key: str) -> Permission:
    row = db.query(Permission).filter(Permission.key == key).first()
    if not row:
        raise HTTPException(404, f"الصلاحية غير موجودة: {key}")
    return row


def _role_or_404(db: Session, role_id: int) -> Role:
    row = db.query(Role).filter(Role.id == role_id).first()
    if not row:
        raise HTTPException(404, "الدور غير موجود")
    return row


def _set_role_permissions(db: Session, role: Role, keys: List[str]) -> List[str]:
    """يستبدل صلاحيات الدور بمجموعة المفاتيح المعطاة (تحقق من وجودها أولًا)."""
    unique = list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))
    for key in unique:
        _perm_or_404(db, key)          # يتحقق قبل أي تعديل (ذرّية)
    if role.is_super:
        # دور المدير العام يتجاوز كل شيء، فربطه بصلاحية لا معنى له
        return sorted({rp.permission.key for rp in role.permissions
                       if rp.permission is not None})
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    perms = {p.key: p for p in db.query(Permission).all()}
    for key in unique:
        db.add(RolePermission(role_id=role.id, permission_id=perms[key].id))
    db.flush()
    db.refresh(role)
    return sorted(set(unique))


# ===== كتالوج الصلاحيات =====
@router.get("/catalog", response_model=List[PermissionOut],
            summary="كتالوج الصلاحيات مجمّعًا حسب الوحدة")
def catalog(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """كل القدرات المتاحة في النظام — تبني منها الواجهة مصفوفة الأدوار."""
    rows = db.query(Permission).order_by(Permission.module, Permission.key).all()
    return [PermissionOut(key=r.key, name_ar=r.name_ar, module=r.module,
                          description=r.description, is_sensitive=r.is_sensitive)
            for r in rows]


@router.get("/modules", response_model=List[str], summary="وحدات الصلاحيات")
def modules(_: User = Depends(get_current_user)):
    return list(PERMISSION_MODULES)


# ===== الأدوار =====
@router.get("/roles", response_model=List[RoleOut], summary="قائمة الأدوار")
def list_roles(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Role).order_by(Role.is_super.desc(), Role.id).all()
    return [_role_out(db, r) for r in rows]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED,
             summary="إنشاء دور مخصّص")
def create_role(payload: RoleIn, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    """دور جديد قابل للتخصيص — يظهر في قائمة أدوار المستخدمين فورًا."""
    key = (payload.key or _slugify(payload.name_ar))[:40]
    if db.query(Role).filter(Role.key == key).first():
        # مفتاح مكرر: نلحق رقمًا بدل رفض الطلب (تجربة أفضل للمستخدم)
        n = 2
        while db.query(Role).filter(Role.key == f"{key}{n}").first():
            n += 1
        key = f"{key}{n}"[:40]
    role = Role(key=key, name_ar=payload.name_ar, description=payload.description,
                is_system=False, is_super=False, is_active=True)
    db.add(role)
    db.flush()
    if payload.copy_from:
        src = db.query(Role).filter(Role.key == payload.copy_from).first()
        if not src:
            raise HTTPException(404, f"الدور المصدر غير موجود: {payload.copy_from}")
        _set_role_permissions(db, role, [rp.permission.key for rp in src.permissions
                                         if rp.permission is not None])
    elif payload.permissions:
        _set_role_permissions(db, role, payload.permissions)
    db.commit()
    db.refresh(role)
    return _role_out(db, role)


@router.get("/roles/{role_id}", response_model=RoleOut, summary="تفاصيل دور")
def get_role(role_id: int, db: Session = Depends(get_db),
             _: User = Depends(get_current_user)):
    return _role_out(db, _role_or_404(db, role_id))


@router.put("/roles/{role_id}", response_model=RoleOut, summary="تعديل دور")
def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    role = _role_or_404(db, role_id)
    if role.is_super and payload.is_active is False:
        raise HTTPException(400, "لا يمكن تعطيل دور المدير العام")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    db.commit()
    db.refresh(role)
    return _role_out(db, role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف دور مخصّص")
def delete_role(role_id: int, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    role = _role_or_404(db, role_id)
    if role.is_system:
        raise HTTPException(400, "أدوار النظام لا تُحذف — يمكن تعطيلها بدلًا من ذلك")
    in_use = db.query(User).filter(User.role == role.key).count()
    if in_use:
        raise HTTPException(
            400, f"الدور مرتبط بـ {in_use} مستخدم — انقلهم لدور آخر أولًا")
    db.delete(role)
    db.commit()
    return None


@router.put("/roles/{role_id}/permissions", response_model=RoleOut,
            summary="ضبط صلاحيات دور (استبدال كامل)")
def set_role_permissions(role_id: int, payload: RolePermissionsIn,
                         db: Session = Depends(get_db),
                         _: User = Depends(require_admin)):
    role = _role_or_404(db, role_id)
    _set_role_permissions(db, role, payload.permissions)
    db.commit()
    db.refresh(role)
    return _role_out(db, role)


@router.post("/roles/{role_id}/copy", response_model=RoleOut,
             status_code=status.HTTP_201_CREATED, summary="نسخ دور")
def copy_role(role_id: int, payload: RoleIn, db: Session = Depends(get_db),
              _: User = Depends(require_admin)):
    """إنشاء دور جديد بنفس صلاحيات دور موجود — أسرع طريقة لتخصيص دور قريب."""
    src = _role_or_404(db, role_id)
    key = (payload.key or f"{src.key}_copy")[:40]
    if db.query(Role).filter(Role.key == key).first():
        n = 2
        while db.query(Role).filter(Role.key == f"{key}{n}").first():
            n += 1
        key = f"{key}{n}"[:40]
    role = Role(key=key, name_ar=payload.name_ar or f"{src.name_ar} (نسخة)",
                description=payload.description, is_system=False, is_super=False)
    db.add(role)
    db.flush()
    _set_role_permissions(db, role, [rp.permission.key for rp in src.permissions
                                     if rp.permission is not None])
    db.commit()
    db.refresh(role)
    return _role_out(db, role)


# ===== المصفوفة (الأدوار × الصلاحيات) =====
@router.get("/matrix", summary="مصفوفة الأدوار والصلاحيات")
def matrix(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """مصفوفة واحدة للواجهة: كل دور بصلاحياته ومستخدموه."""
    roles = db.query(Role).order_by(Role.is_super.desc(), Role.id).all()
    return {
        "modules": list(PERMISSION_MODULES),
        "permissions": [
            {"key": p.key, "name_ar": p.name_ar, "module": p.module,
             "is_sensitive": p.is_sensitive}
            for p in db.query(Permission).order_by(Permission.module,
                                                    Permission.key).all()],
        "roles": [_role_out(db, r).model_dump() for r in roles],
    }


# ===== استثناءات المستخدمين =====
@router.get("/users/{user_id}/access", response_model=UserAccessOut,
            summary="صلاحيات مستخدم: الدور + الاستثناءات + الفعلي")
def user_access(user_id: int, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    role = user.role_row
    role_perms = sorted({rp.permission.key for rp in role.permissions
                         if rp.permission is not None}) if role else []
    overrides = [{"permission": o.permission.key if o.permission else None,
                  "effect": o.effect, "note": o.note}
                 for o in user.permission_overrides]
    return UserAccessOut(
        user_id=user.id, username=user.username, full_name=user.full_name,
        role=user.role, role_name=role.name_ar if role else None,
        role_permissions=role_perms, overrides=overrides,
        effective=sorted(effective_permissions(db, user)))


@router.put("/users/{user_id}/access", response_model=UserAccessOut,
            summary="ضبط استثناءات مستخدم (استبدال كامل)")
def set_user_overrides(user_id: int, payload: List[UserOverrideIn],
                       db: Session = Depends(get_db),
                       _: User = Depends(require_admin)):
    """استبدل استثناءات المستخدم. `deny` يمنع صلاحية يمنحها الدور،
    و`allow` يمنح صلاحية لا يمنحها دوره — مثال: سماح محاسب بالاسترداد."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    prepared = []
    for item in payload:
        if item.effect not in ("allow", "deny"):
            raise HTTPException(400, "effect يجب أن يكون allow أو deny")
        perm = _perm_or_404(db, item.permission)
        prepared.append((perm, item.effect, item.note))
    db.query(UserPermission).filter(UserPermission.user_id == user.id).delete()
    db.flush()
    for perm, effect, note in prepared:
        db.add(UserPermission(user_id=user.id, permission_id=perm.id,
                              effect=effect, note=note))
    db.commit()
    db.refresh(user)
    return user_access(user_id, db, _)


@router.delete("/users/{user_id}/access/{permission_key}", status_code=204,
               summary="حذف استثناء واحد")
def delete_user_override(user_id: int, permission_key: str, db: Session = Depends(get_db),
                         _: User = Depends(require_admin)):
    row = (db.query(UserPermission)
           .join(Permission, UserPermission.permission_id == Permission.id)
           .filter(UserPermission.user_id == user_id,
                   Permission.key == permission_key).first())
    if not row:
        raise HTTPException(404, "الاستثناء غير موجود")
    db.delete(row)
    db.commit()
    return None


# ===== أدوات مساعدة للواجهة =====
@router.get("/check", summary="فحص صلاحية واحدة (للتشخيص)")
def check(key: str, db: Session = Depends(get_db),
          current: User = Depends(get_current_user)):
    """هل يملك المستخدم الحالي صلاحية محددة؟ — يفيد زر «لماذا لا أرى؟»."""
    return {"key": key, "granted": has_perm(db, current, key),
            "role": current.role, "total": len(effective_permissions(db, current))}


@router.get("/my", summary="صلاحياتي")
def my_permissions(db: Session = Depends(get_db),
                   current: User = Depends(get_current_user)):
    perms = sorted(effective_permissions(db, current))
    return {"role": current.role, "role_name": (current.role_row.name_ar
                                                if current.role_row else current.role),
            "permissions": perms, "count": len(perms),
            "is_super": bool(current.role_row and current.role_row.is_super)}
