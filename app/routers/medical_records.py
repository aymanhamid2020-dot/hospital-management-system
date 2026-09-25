from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from fastapi import Query

from app.database import get_db
from app.models import MedicalRecord, Patient, Doctor, User
from app.schemas import MedicalRecordCreate, MedicalRecordUpdate, MedicalRecordInDB
from app.auth import get_current_user, require_admin, get_user_role

router = APIRouter(prefix="/medical-records", tags=["Medical Records"])


def _get_linked_doctor(db: Session, user: User) -> Optional[Doctor]:
    """إيجاد سجل الطبيب المرتبط بحساب المستخدم (عبر البريد الإلكتروني)."""
    return db.query(Doctor).filter(Doctor.email == user.email).first()


@router.get("/", response_model=List[MedicalRecordInDB], summary="عرض السجلات الطبية")
async def list_records(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    doctor_id: Optional[int] = Query(None, description="فلترة حسب الطبيب"),
    search: Optional[str] = Query(None, description="بحث في التشخيص"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """جلب السجلات الطبية — الطبيب يرى سجلات مرضاه فقط"""
    q = db.query(MedicalRecord)

    # صلاحية الطبيب: يرى سجلات مرضاه فقط
    if get_user_role(current_user) == "doctor":
        linked = _get_linked_doctor(db, current_user)
        if linked is None:
            return []
        q = q.filter(MedicalRecord.doctor_id == linked.id)

    if patient_id is not None:
        q = q.filter(MedicalRecord.patient_id == patient_id)
    if doctor_id is not None:
        q = q.filter(MedicalRecord.doctor_id == doctor_id)
    if search:
        q = q.filter(MedicalRecord.diagnosis.contains(search))

    return q.order_by(MedicalRecord.created_at.desc()).all()


@router.get("/{record_id}", response_model=MedicalRecordInDB, summary="عرض سجل محدد")
async def get_record(
    record_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = db.query(MedicalRecord).filter(MedicalRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="لا يوجد سجل بالمعرف المحدد")

    # الطبيب لا يرى سجلات غير مرضاه
    if get_user_role(current_user) == "doctor":
        linked = _get_linked_doctor(db, current_user)
        if linked is None or record.doctor_id != linked.id:
            raise HTTPException(status_code=403, detail="لا تصلحية للوصول لهذا السجل")
    return record


@router.post("/", response_model=MedicalRecordInDB, summary="إنشاء سجل طبي")
async def create_record(
    record: MedicalRecordCreate,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إنشاء سجل طبي — الطبيب يُنسب السجل تلقائيًا لنفسه"""
    # التحقق من وجود المريض
    if not db.query(Patient).filter(Patient.id == record.patient_id).first():
        raise HTTPException(status_code=404, detail="المريض غير موجود")

    doctor_id = record.doctor_id
    role = get_user_role(current_user)

    if role == "doctor":
        # الطبيب ينشئ سجلًا لنفسه إجباريًا
        linked = _get_linked_doctor(db, current_user)
        if linked is None:
            raise HTTPException(
                status_code=403,
                detail="حسابك غير مرتبط بسجل طبيب في النظام",
            )
        doctor_id = linked.id
    elif doctor_id is not None:
        if not db.query(Doctor).filter(Doctor.id == doctor_id).first():
            raise HTTPException(status_code=404, detail="الطبيب غير موجود")

    db_record = MedicalRecord(
        patient_id=record.patient_id,
        doctor_id=doctor_id,
        diagnosis=record.diagnosis,
        chief_complaint=record.chief_complaint,
        prescription=record.prescription,
        notes=record.notes,
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


@router.get("/{record_id}/pdf", summary="تحميل السجل الطبي PDF")
async def download_record_pdf(
    record_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """توليد السجل الطبي كملف PDF عربي"""
    from fastapi.responses import Response
    from app.pdf_utils import record_pdf

    record = db.query(MedicalRecord).filter(MedicalRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="لا يوجد سجل بالمعرف المحدد")

    # الطبيب يحمّل سجلات مرضاه فقط
    if get_user_role(current_user) == "doctor":
        linked = _get_linked_doctor(db, current_user)
        if linked is None or record.doctor_id != linked.id:
            raise HTTPException(status_code=403, detail="لا تصلحية للوصول لهذا السجل")

    doctor_name = record.doctor.full_name if record.doctor else "-"
    pdf_bytes = record_pdf(record, record.patient.full_name, doctor_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="record_{record_id}.pdf"'},
    )


@router.put("/{record_id}", response_model=MedicalRecordInDB, summary="تحديث سجل طبي")
async def update_record(
    record_id: int,
    record: MedicalRecordUpdate,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_record = db.query(MedicalRecord).filter(MedicalRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="لا يوجد سجل بالمعرف المحدد")

    # الطبيب يحدّث سجلات مرضاه فقط، الموظفون العاديون لا يحدّثون
    if get_user_role(current_user) == "doctor":
        linked = _get_linked_doctor(db, current_user)
        if linked is None or db_record.doctor_id != linked.id:
            raise HTTPException(status_code=403, detail="لا تصلحية لتحديث هذا السجل")
    elif get_user_role(current_user) != "admin":
        raise HTTPException(status_code=403, detail="هذه العملية تتطلب صلاحية طبيب أو مدير")

    for field, value in record.model_dump(exclude_unset=True).items():
        setattr(db_record, field, value)
    db.commit()
    db.refresh(db_record)
    return db_record


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف سجل طبي")
async def delete_record(
    record_id: int,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف سجل طبي (للمدير فقط)"""
    db_record = db.query(MedicalRecord).filter(MedicalRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="لا يوجد سجل بالمعرف المحدد")
    db.delete(db_record)
    db.commit()
    return None
