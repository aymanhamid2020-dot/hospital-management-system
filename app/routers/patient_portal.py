"""بوابة المريض: إدارة حسابات المريض (للمدير) + دخول وتوكن منفصل عن حسابات الموظفين.

الحساب يربط سجل مريض واحدًا فقط، وكلمة المرور مُجزَّأة (hash) فلا تُقرأ من
أي استعلام قائمة. إنشاء الحساب وإعادة تعيين كلمة المرور متاحان للمدير
فقط، فلا يستطيع المريض التسجيل بنفسه ولا انتحال سجل غيره.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (bearer_scheme, decode_token, hash_password,
                      require_admin, verify_password)
from app.clinical_schemas import PatientAppointmentCreate, PatientPortalLogin
from app.config import ALGORITHM, SECRET_KEY
from app.database import get_db
from app.models import (
    Admission, Appointment, Doctor, Invoice, LabOrder, Patient,
    PatientPortalAccount, Prescription, ServiceRequest, User,
)

router = APIRouter(prefix="/patient-portal", tags=["بوابة المريض"])


class PortalAccountCreate(BaseModel):
    """إنشاء حساب بوابة لمريض موجود (المدير فقط)."""
    patient_id: int = Field(..., gt=0, description="معرّف المريض من سجل المرضى")
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=8, max_length=128,
                          description="8 أحرف فأكثر")


class PortalPasswordReset(BaseModel):
    """إعادة تعيين كلمة مرور حساب بوابة (المدير فقط)."""
    password: str = Field(..., min_length=8, max_length=128)


class PortalAccountOut(BaseModel):
    """عرض الحساب بلا كلمة المرور."""
    id: int
    patient_id: int
    patient_name: str
    username: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


def _out(account: PatientPortalAccount, db: Session) -> dict:
    patient = db.query(Patient).filter(Patient.id == account.patient_id).first()
    return {
        "id": account.id, "patient_id": account.patient_id,
        "patient_name": patient.full_name if patient else "—",
        "username": account.username, "is_active": account.is_active,
        "last_login_at": account.last_login_at,
        "created_at": account.created_at,
    }


def _token(account: PatientPortalAccount) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(account.id), "patient_id": account.patient_id,
        "scope": "patient_portal", "iat": now,
        "exp": now + timedelta(hours=8),
    }, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/accounts", response_model=PortalAccountOut, status_code=201,
             summary="إنشاء حساب بوابة لمريض (مدير فقط)")
async def create_portal_account(
    payload: PortalAccountCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """إنشاء حساب بوابة لمريض موجود — المدير فقط."""
    if not db.query(Patient).filter(Patient.id == payload.patient_id).first():
        raise HTTPException(404, "المريض غير موجود")
    existing = db.query(PatientPortalAccount).filter(
        PatientPortalAccount.username == payload.username).first()
    if existing:
        raise HTTPException(400, "اسم المستخدم مستخدم مسبقًا")
    patient_same = db.query(PatientPortalAccount).filter(
        PatientPortalAccount.patient_id == payload.patient_id).first()
    if patient_same:
        raise HTTPException(400, "يوجد حساب بوابة لهذا المريض مسبقًا")
    account = PatientPortalAccount(
        patient_id=payload.patient_id,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        is_active=True,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _out(account, db)


@router.get("/accounts", response_model=List[PortalAccountOut],
            summary="قائمة حسابات البوابة (مدير فقط)")
async def list_portal_accounts(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """قائمة جميع حسابات البوابة (مدير فقط)."""
    accounts = db.query(PatientPortalAccount).order_by(PatientPortalAccount.id.desc()).all()
    return [_out(a, db) for a in accounts]


@router.get("/accounts/{account_id}", response_model=PortalAccountOut,
            summary="عرض حساب بوابة (مدير فقط)")
async def get_portal_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """عرض تفاصيل حساب بوابة (مدير فقط)."""
    account = db.query(PatientPortalAccount).filter(PatientPortalAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "الحساب غير موجود")
    return _out(account, db)


@router.put("/accounts/{account_id}", response_model=PortalAccountOut,
            summary="تحديث حساب بوابة (مدير فقط)")
async def update_portal_account(
    account_id: int,
    payload: PortalPasswordReset,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """إعادة تعيين كلمة مرور حساب بوابة (مدير فقط)."""
    account = db.query(PatientPortalAccount).filter(PatientPortalAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "الحساب غير موجود")
    account.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(account)
    return _out(account, db)


@router.delete("/accounts/{account_id}", status_code=204,
               summary="حذف حساب بوابة (مدير فقط)")
async def delete_portal_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف حساب بوابة (مدير فقط) — حذف نهائي."""
    account = db.query(PatientPortalAccount).filter(PatientPortalAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "الحساب غير موجود")
    db.delete(account)
    db.commit()
    return None


def _account(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
             db: Session = Depends(get_db)) -> PatientPortalAccount:
    if not credentials:
        raise HTTPException(401, "تسجيل دخول بوابة المريض مطلوب")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("scope") != "patient_portal":
            raise ValueError("wrong scope")
        account = db.query(PatientPortalAccount).filter(
            PatientPortalAccount.id == int(payload["sub"])).first()
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(401, "جلسة بوابة المريض غير صالحة أو منتهية")
    if not account or not account.is_active:
        raise HTTPException(401, "حساب بوابة المريض غير نشط")
    return account


@router.get("/accounts", response_model=List[PortalAccountOut],
            summary="حسابات بوابة المريض (مدير فقط)")
def list_accounts(db: Session = Depends(get_db),
                  _: User = Depends(require_admin)):
    """كل حسابات البوابة مع اسم المريض — بلا كلمة المرور."""
    rows = (db.query(PatientPortalAccount)
            .order_by(PatientPortalAccount.id.desc()).all())
    return [_out(a, db) for a in rows]


@router.post("/accounts", response_model=PortalAccountOut, status_code=201,
             summary="إنشاء حساب بوابة لمريض (مدير فقط)")
def create_account(payload: PortalAccountCreate, db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    """ينشئ حسابًا لسجل مريض واحد — الحساب لا يُنشأ ذاتيًا."""
    if not db.query(Patient).filter(Patient.id == payload.patient_id).first():
        raise HTTPException(404, "المريض غير موجود — أنشئ سجل المريض أولًا")
    if db.query(PatientPortalAccount).filter(
            PatientPortalAccount.patient_id == payload.patient_id).first():
        raise HTTPException(400, "للهذا المريض حساب بوابة مسبقًا")
    if db.query(PatientPortalAccount).filter(
            PatientPortalAccount.username == payload.username).first():
        raise HTTPException(400, "اسم المستخدم مستخدم لحساب آخر")

    account = PatientPortalAccount(
        patient_id=payload.patient_id, username=payload.username,
        hashed_password=hash_password(payload.password), is_active=True)
    db.add(account)
    db.commit()
    db.refresh(account)
    return _out(account, db)


@router.put("/accounts/{account_id}/password", response_model=PortalAccountOut,
            summary="إعادة تعيين كلمة مرور الحساب (مدير فقط)")
def reset_password(account_id: int, payload: PortalPasswordReset,
                   db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    """استبدال كلمة المرور — الطريق الوحيد بعد نسيان المريض لها."""
    account = db.query(PatientPortalAccount).filter(
        PatientPortalAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "حساب البوابة غير موجود")
    account.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(account)
    return _out(account, db)


@router.patch("/accounts/{account_id}", response_model=PortalAccountOut,
              summary="تنشيط/تعطيل حساب البوابة (مدير فقط)")
def toggle_account(account_id: int, payload: dict, db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    """تعطيل الحساب يمنع الدخول فورًا."""
    account = db.query(PatientPortalAccount).filter(
        PatientPortalAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "حساب البوابة غير موجود")
    if "is_active" in payload:
        account.is_active = bool(payload["is_active"])
    db.commit()
    db.refresh(account)
    return _out(account, db)


@router.delete("/accounts/{account_id}", status_code=204,
               summary="حذف حساب البوابة (مدير فقط)")
def delete_account(account_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_admin)):
    """الحذف يمحو الوصول للبوابة فقط ولا يمسّ سجل المريض الطبي."""
    account = db.query(PatientPortalAccount).filter(
        PatientPortalAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "حساب البوابة غير موجود")
    db.delete(account)
    db.commit()
    return None


@router.post("/login")
def login(payload: PatientPortalLogin, db: Session = Depends(get_db)):
    account = db.query(PatientPortalAccount).filter(
        PatientPortalAccount.username == payload.username).first()
    if not account or not account.is_active or not verify_password(payload.password, account.hashed_password):
        raise HTTPException(401, "اسم المستخدم أو كلمة المرور غير صحيحة")
    patient = db.query(Patient).filter(Patient.id == account.patient_id).first()
    if not patient:
        raise HTTPException(404, "سجل المريض غير موجود")
    account.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {
        "access_token": _token(account), "token_type": "bearer",
        "patient": {"id": patient.id, "full_name": patient.full_name,
                    "phone": patient.phone, "national_id": patient.national_id},
    }


@router.get("/me")
def me(account: PatientPortalAccount = Depends(_account), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == account.patient_id).first()
    return {
        "patient": patient,
        "appointments": db.query(Appointment).filter(Appointment.patient_id == account.patient_id).order_by(Appointment.appointment_date.desc()).limit(20).all(),
        "lab_orders": db.query(LabOrder).filter(LabOrder.patient_id == account.patient_id).order_by(LabOrder.id.desc()).limit(20).all(),
        "invoices": db.query(Invoice).filter(Invoice.patient_id == account.patient_id).order_by(Invoice.id.desc()).limit(20).all(),
        "prescriptions": db.query(Prescription).filter(Prescription.patient_id == account.patient_id).order_by(Prescription.id.desc()).limit(20).all(),
        "service_requests": db.query(ServiceRequest).filter(ServiceRequest.patient_id == account.patient_id).order_by(ServiceRequest.id.desc()).limit(20).all(),
        "admissions": db.query(Admission).filter(Admission.patient_id == account.patient_id).order_by(Admission.id.desc()).limit(20).all(),
    }


@router.post("/appointments", status_code=201)
def request_appointment(
    payload: PatientAppointmentCreate,
    account: PatientPortalAccount = Depends(_account),
    db: Session = Depends(get_db),
):
    """المريض يحجز لموعده فقط؛ لا يختار نيابة عن مريض آخر."""
    if not db.query(Doctor).filter(Doctor.id == payload.doctor_id).first():
        raise HTTPException(404, "الطبيب غير موجود")
    appointment = Appointment(
        patient_id=account.patient_id, doctor_id=payload.doctor_id,
        appointment_date=payload.appointment_date, reason=payload.reason,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment
