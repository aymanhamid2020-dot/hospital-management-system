import os
import time as _time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.schemas import (
    UserCreate, UserLogin, UserInDB, Token, PasswordChange, UserRoleChange,
)
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_user_role, require_admin,
)
from app.permissions import _LEGACY_ROLE_MAP, user_permissions

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ===== حماية الدخول: قفل مؤقت بعد محاولات فاشلة (في الذاكرة لكل عملية) =====
_failed_logins: dict[str, list[float]] = {}


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def validate_password_strength(password: str) -> None:
    """قوة كلمة المرور: ≥8 أحرف + حرف + رقم — يرفع 400 برسالة عربية."""
    import re as _re
    if len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="كلمة المرور قصيرة — يجب أن تكون 8 أحرف على الأقل")
    if not _re.search(r"[^\W\d_]", password, _re.UNICODE):
        raise HTTPException(
            status_code=400,
            detail="كلمة المرور يجب أن تحتوي على حرف واحد على الأقل")
    if not _re.search(r"\d", password):
        raise HTTPException(
            status_code=400,
            detail="كلمة المرور يجب أن تحتوي على رقم واحد على الأقل")


def _check_login_lockout(key: str) -> None:
    """يرفع 429 إن تجاوزت محاولات الدخول الفاشلة الحد خلال نافذة القفل.

    LOGIN_MAX_ATTEMPTS (افتراضي 5) وLOGIN_LOCKOUT_MINUTES (افتراضي 15 —
    القيمة 0 تُعطل القفل). تُقرأ البيئة عند كل استدعاء لتُضبط وقت التشغيل.
    """
    max_attempts = int(_env_num("LOGIN_MAX_ATTEMPTS", 5))
    window = _env_num("LOGIN_LOCKOUT_MINUTES", 15) * 60
    now = _time.time()
    attempts = [t for t in _failed_logins.get(key, []) if now - t < window]
    _failed_logins[key] = attempts
    if window > 0 and len(attempts) >= max_attempts:
        remaining = int(attempts[0] + window - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"تجاوزت محاولات الدخول الفاشلة ({max_attempts}) — "
                   f"أعد المحاولة بعد {remaining} ثانية",
        )


# ===== حماية على مستوى الـIP: منع تدوير أسماء المستخدمين =====
_ip_failed_logins: dict[str, list[float]] = {}


def _check_ip_login_limit(ip: str) -> None:
    """يرفع 429 إن تجاوزت محاولات الدخول الفاشلة من نفس الـIP الحد.

    AUTH_IP_FAIL_MAX (افتراضي 30) وAUTH_IP_WINDOW_MINUTES (افتراضي 15 —
    القيمة 0 تُعطل الحماية). تُقرأ البيئة عند كل استدعاء مثل قفل المستخدم.
    """
    max_fails = int(_env_num("AUTH_IP_FAIL_MAX", 30))
    window = _env_num("AUTH_IP_WINDOW_MINUTES", 15) * 60
    if max_fails <= 0 or window <= 0:
        return
    now = _time.time()
    fails = [t for t in _ip_failed_logins.get(ip, []) if now - t < window]
    _ip_failed_logins[ip] = fails
    if len(fails) >= max_fails:
        raise HTTPException(
            status_code=429,
            detail=f"تجاوزت محاولات الدخول الفاشلة من هذا العنوان ({max_fails}) — "
                   f"أعد المحاولة لاحقًا",
        )


def record_ip_login_failure(ip: str) -> None:
    """تسجيل محاولة دخول فاشلة في السجل الخاص بالـIP."""
    if int(_env_num("AUTH_IP_FAIL_MAX", 30)) <= 0:
        return
    _ip_failed_logins.setdefault(ip, []).append(_time.time())


def _user_out(db, user: User) -> UserInDB:
    """يحوّل المستخدم إلى مخطط الاستجابة مع صلاحياته الفعلية."""
    data = UserInDB.model_validate(user)
    data.role = get_user_role(user)
    data.permissions = user_permissions(db, user)
    data.role_name = (user.role_row.name_ar if user.role_row else user.role)
    return data


def _resolve_role(db, raw) -> str:
    """يترجم قيمة الدور إلى مفتاح موجود فعلًا — **بصرامة**.

    طلب قيمة صريح يجب أن يقابل دورًا وإلا خطأ صريح: الصمت هنا خطر،
    لأن منظّم النظام قد يظن أنه أسند دور «محاسب» بينما سجّل «موظف استقبال».
    المرونة (افتراضي أقل صلاحية) محجوزة لمسار الهجرة فقط في
    `permissions.normalize_role_key`، لا لطلبات المستخدم.
    """
    value = str(getattr(raw, "value", raw) or "").strip()
    if not value:
        value = "receptionist"
    row = (db.query(Role)
           .filter((Role.key == value) | (Role.name_ar == value)).first())
    if row:
        return row.key
    # قيم نظام التعداد القديم (ADMIN…) تُقبل صراحةً ولا تُconsidered صامتة
    legacy = _LEGACY_ROLE_MAP.get(value) or _LEGACY_ROLE_MAP.get(value.lower())
    if legacy:
        row = db.query(Role).filter(Role.key == legacy).first()
        if row:
            return row.key
    available = [r.key for r in db.query(Role).order_by(Role.id).all()]
    raise HTTPException(
        status_code=400,
        detail=f"الدور غير موجود: «{value}». الأدوار المتاحة: " + "، ".join(available))


@router.post("/register", response_model=UserInDB, summary="تسجيل مستخدم جديد")
async def register(user: UserCreate, db = Depends(get_db)):
    """تسجيل مستخدم جديد (الدور الافتراضي: موظف استقبال)"""
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="اسم المستخدم موجود بالفعل")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="البريد الإلكتروني مسجل بالفعل")
    validate_password_strength(user.password)
    role_key = _resolve_role(db, user.role)
    if role_key == "admin":
        # لا يُمنح دور المدير بالتسجيل العام — حماية من تصعيد الصلاحيات
        role_key = "receptionist"

    db_user = User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=role_key,
        hashed_password=hash_password(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return _user_out(db, db_user)


@router.post("/login", response_model=Token, summary="تسجيل الدخول")
async def login(credentials: UserLogin, request: Request, db = Depends(get_db)):
    """تسجيل الدخول والحصول على توكن JWT — مع قفل مؤقت بعد المحاولات الفاشلة"""
    client_ip = request.client.host if request.client else "?"
    lock_key = f"{credentials.username.lower()}|{client_ip}"
    _check_login_lockout(lock_key)
    _check_ip_login_limit(client_ip)

    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        _failed_logins.setdefault(lock_key, []).append(_time.time())
        record_ip_login_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="الحساب غير نشط")
    _failed_logins.pop(lock_key, None)

    token = create_access_token(user)
    # الصلاحيات تُعيد مع الدخول مباشرةً: لا نداء إضافي بعد تسجيل الدخول
    return Token(access_token=token, user=_user_out(db, user))


@router.get("/me", response_model=UserInDB, summary="المستخدم الحالي وصلاحياته")
async def get_me(current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """بيانات المستخدم المسجّل دخوله + صلاحياته الفعلية (تحكم الواجهة بها)."""
    return _user_out(db, current_user)


# ===== إدارة المستخدمين =====
@router.get("/users", response_model=list[UserInDB], summary="قائمة المستخدمين")
async def list_users(
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    rows = db.query(User).order_by(User.id).all()
    return [_user_out(db, u) for u in rows]


@router.put("/users/{user_id}/toggle", response_model=UserInDB,
            summary="تفعيل/تعطيل مستخدم")
async def toggle_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    """تفعيل أو تعطيل حساب مستخدم"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="لا يمكنك تعطيل حسابك")
    if user.is_active and get_user_role(user) == "admin":
        _guard_last_admin(db, user, "تعطيل")
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


def _guard_last_admin(db, target: User, action: str) -> None:
    """يمنع إزالة آخر مدير نشط (إبطال دوره أو تعطيله) حتى لا يُقفل النظام."""
    others = (db.query(User)
              .filter(User.id != target.id, User.is_active.is_(True)).all())
    if not any(get_user_role(u) == "admin" for u in others):
        raise HTTPException(status_code=400,
                            detail=f"لا يمكن {action} آخر مدير نشط في النظام")


@router.put("/users/{user_id}/role", response_model=UserInDB, summary="تغيير دور مستخدم")
async def change_user_role(
    user_id: int,
    payload: UserRoleChange,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    """تغيير دور مستخدم — بحماية آخر مدير نشط ومنع التصعيد الذاتي."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    if target.id == current.id:
        raise HTTPException(status_code=400, detail="لا يمكنك تغيير دور حسابك")
    old_role = get_user_role(target)
    new_role = _resolve_role(db, payload.role)
    if old_role == "admin" and new_role != "admin":
        _guard_last_admin(db, target, "سحب صلاحية")
    target.role = new_role
    db.commit()
    db.refresh(target)
    return _user_out(db, target)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف مستخدم")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
):
    """حذف حساب نهائيًا — يرفض الذات ويحمي آخر مدير نشط.

    آمن بالمراجع: `user_permissions` تُحذف بـ`cascade="all, delete-orphan"`
    في الطبقة العلوية، و`Doctor.user_id` و`AuditLog.user_id` بـ`SET NULL`
    على مستوى القاعدة (`PRAGMA foreign_keys=ON`) — فلا صف يتيم ولا خطأ 500.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="لا يمكنك حذف حسابك")
    if user.is_active and get_user_role(user) == "admin":
        _guard_last_admin(db, user, "حذف")
    db.delete(user)
    db.commit()
    return None


# ===== تغيير كلمة المرور الذاتي =====
@router.post("/change-password", summary="تغيير كلمة المرور")
async def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """تغيير كلمة مرور الحساب الحالي (أي مستخدم مسجّل دخوله)"""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="كلمة المرور الحالية غير صحيحة")
    validate_password_strength(payload.new_password)
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"message": "تم تغيير كلمة المرور بنجاح"}
