"""أدوات المصادقة: تشفير كلمات المرور وإنشاء/التحقق من توكنات JWT."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_user_role(user: User) -> str:
    """إرجاع قيمة الدور كنص قياسي."""
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def require_role(*roles: str):
    """Dependency factory: يسمح بأدوار محددة فقط (مثال: require_role("admin", "doctor"))."""
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if get_user_role(current_user) not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ليس لديك صلاحية لتنفيذ هذه العملية",
            )
        return current_user
    return checker

#_PBKDF2 parameters
_PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """تشفير كلمة المرور باستخدام PBKDF2-HMAC-SHA256 مع salt عشوائي."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """التحقق من كلمة المرور مقابل القيمة المشفّرة."""
    try:
        _, iterations, salt_hex, dk_hex = hashed.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(dk, expected)


def create_access_token(user: User) -> str:
    """إنشاء توكن JWT لمستخدم."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """فك تشفير التوكن، يرمي استثناء عند عدم الصلاحية."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: يُرجع المستخدم الحالي من التوكن أو يرمي 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="يجب تسجيل الدخول للوصول لهذا المورد",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توكن غير صالح أو منتهي الصلاحية",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="المستخدم غير موجود أو غير نشط",
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: يسمح فقط للمديرين (admin)."""
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذه العملية تتطلب صلاحية المدير",
        )
    return current_user


def generate_password(length: int = 12) -> str:
    """توليد كلمة مرور عشوائية (للأغراض الأخرى)."""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$"
    return "".join(secrets.choice(alphabet) for _ in range(length))
