import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Attachment, Patient, MedicalRecord, User
from app.schemas import AttachmentInDB
from app.auth import get_current_user, require_admin, get_user_role

router = APIRouter(prefix="/attachments", tags=["Attachments"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
MAX_SIZE = 10 * 1024 * 1024  # 10 ميجابايت
ALLOWED_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",          # صور
    ".pdf",                                              # مستندات
    ".txt", ".csv", ".doc", ".docx",                     # نصوص
    ".dcm",                                               # أشعة DICOM
}


def _ensure_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/", response_model=List[AttachmentInDB], summary="قائمة المرفقات")
async def list_attachments(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    record_id: Optional[int] = Query(None, description="فلترة حسب السجل الطبي"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    q = db.query(Attachment)
    if patient_id is not None:
        q = q.filter(Attachment.patient_id == patient_id)
    if record_id is not None:
        q = q.filter(Attachment.record_id == record_id)
    return q.order_by(Attachment.uploaded_at.desc()).all()


@router.post("/", response_model=AttachmentInDB, summary="رفع مرفق")
async def upload_attachment(
    patient_id: int = Form(..., description="معرّف المريض"),
    record_id: Optional[int] = Form(None, description="السجل الطبي المرتبط"),
    file: UploadFile = File(..., description="الملف (حد أقصى 10MB)"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """رفع ملف طبي (تحليل، أشعة، تقرير) مرتبط بمريض"""
    # التحقق من المريض
    if not db.query(Patient).filter(Patient.id == patient_id).first():
        raise HTTPException(status_code=404, detail="المريض غير موجود")
    if record_id is not None:
        if not db.query(MedicalRecord).filter(MedicalRecord.id == record_id).first():
            raise HTTPException(status_code=404, detail="السجل الطبي غير موجود")

    # التحقق من الامتداد
    original = file.filename or "file"
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"نوع الملف غير مسموح. الامتدادات المسموحة: {', '.join(sorted(ALLOWED_EXT))}",
        )

    # قراءة المحتوى مع التحقق من الحجم
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="حجم الملف يتجاوز 10 ميجابايت")

    _ensure_dir()
    stored = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as f:
        f.write(content)

    att = Attachment(
        patient_id=patient_id,
        record_id=record_id,
        original_name=original,
        stored_name=stored,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


@router.get("/{att_id}/file", summary="تنزيل مرفق")
async def download_attachment(
    att_id: int,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """تنزيل ملف المرفق الأصلي"""
    att = db.query(Attachment).filter(Attachment.id == att_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="المرفق غير موجود")
    path = os.path.join(UPLOAD_DIR, att.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="ملف المرفق مفقود من التخزين")
    return FileResponse(
        path,
        media_type=att.content_type,
        filename=att.original_name,
    )


@router.get("/{att_id}/preview", summary="معاينة مرفق")
async def preview_attachment(
    att_id: int,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """عرض المرفق داخل المتصفح (للفورمات القابلة للعرض)"""
    att = db.query(Attachment).filter(Attachment.id == att_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="المرفق غير موجود")
    path = os.path.join(UPLOAD_DIR, att.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="ملف المرفق مفقود من التخزين")
    return FileResponse(path, media_type=att.content_type, content_disposition_type="inline")


@router.delete("/{att_id}", status_code=204, summary="حذف مرفق")
async def delete_attachment(
    att_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """حذف مرفق (المدير أو طبيب السجل)"""
    att = db.query(Attachment).filter(Attachment.id == att_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="المرفق غير موجود")

    role = get_user_role(current_user)
    if role == "admin":
        pass  # المدير يحذف دائمًا
    elif role == "doctor":
        if att.record is None or att.record.doctor is None or att.record.doctor.email != current_user.email:
            raise HTTPException(status_code=403, detail="لا تصلحية لحذف هذا المرفق")
    else:
        raise HTTPException(status_code=403, detail="هذه العملية تتطلب صلاحية المدير أو الطبيب")

    # حذف الملف الفيزيائي
    path = os.path.join(UPLOAD_DIR, att.stored_name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    db.delete(att)
    db.commit()
    return None
