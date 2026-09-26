"""بوابة المريض: إدارة حسابات المريض (للمدير) + دخول وتوكن منفصل عن حسابات الموظفين.

الحساب يربط سجل مريض واحدًا فقط، وكلمة المرور مُجزَّأة (hash) فلا تُقرأ من
أي استعلام قائمة. إنشاء الحساب وإعادة تعيين كلمة المرور متاحان للمدير
فقط، فلا يستطيع المريض التسجيل بنفسه ولا انتحال سجل غيره.
"""
from datetime import datetime, timedelta, timezone
from typing import List

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
    last_login_at: datetime = None
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
