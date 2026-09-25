import os
import uuid
import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Staff, StaffDocument, User
from app.schemas import StaffCreate, StaffUpdate, StaffInDB, StaffDocumentInDB
from app.auth import get_current_user, require_admin, get_user_role

router = APIRouter(prefix="/staff", tags=["Staff"])
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
MAX_SIZE = 10 * 1024 * 1024
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".doc", ".docx", ".txt"}
DOC_TYPES = {"id", "contract", "cv", "certificate", "other"}


def _hr_json(value) -> str:
    if not isinstance(value, str):
        return json.dumps(value or {}, ensure_ascii=False)
    try:
        json.loads(value or "{}")
        return value or "{}"
    except (TypeError, ValueError):
        return "{}"


def _staff_out(row: Staff) -> dict:
    """يرسل ملف الموارد البشرية ككائن JSON، وليس كسلسلة تخزين."""
    data = StaffInDB(
        id=row.id, full_name=row.full_name, position=row.position, phone=row.phone,
        email=row.email, hire_date=row.hire_date, salary=row.salary,
        hr_profile=json.loads(_hr_json(row.hr_profile)), documents=row.documents,
        created_at=row.created_at, updated_at=row.updated_at,
    ).model_dump()
    return data


def _basic_staff_out(row: Staff) -> dict:
    """نسخة محدودة لا تتضمن بيانات الموارد البشرية أو مستندات الهوية."""
    data = _staff_out(row)
    data["hr_profile"] = {}
    data["documents"] = []
    return data


@router.get("/", response_model=List[StaffInDB], summary="عرض قائمة الموظفين")
async def list_staff(db = Depends(get_db), current_user: User = Depends(get_current_user)):
    """جلب الموظفين؛ ملف الموارد البشرية والمرفقات للمردير فقط."""
    staff = db.query(Staff).all()
    if get_user_role(current_user) == "admin":
        return [_staff_out(x) for x in staff]
    return [_basic_staff_out(x) for x in staff]


@router.get("/{staff_id}", response_model=StaffInDB, summary="عرض موظف معين")
async def get_staff(staff_id: int, db = Depends(get_db), current_user: User = Depends(get_current_user)):
    """جلب موظف؛ يعرض المدير فقط ملف الموارد البشرية والمرفقات."""
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موظف بالمعرف المحدد"
        )
    return _staff_out(staff) if get_user_role(current_user) == "admin" else _basic_staff_out(staff)


@router.post("/", response_model=StaffInDB, summary="إضافة موظف جديد")
async def create_staff(staff: StaffCreate, db = Depends(get_db), _ = Depends(get_current_user)):
    """إضافة موظف جديد"""
    # التحقق من عدم تكرار البريد الإلكتروني
    existing_staff = db.query(Staff).filter(Staff.email == staff.email).first()
    if existing_staff:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا البريد الإلكتروني مسجل بالفعل"
        )
    
    db_staff = Staff(
        full_name=staff.full_name,
        position=staff.position,
        phone=staff.phone,
        email=staff.email,
        hire_date=staff.hire_date,
        salary=staff.salary,
        hr_profile=json.dumps(staff.hr_profile or {}, ensure_ascii=False),
    )
    db.add(db_staff)
    db.commit()
    db.refresh(db_staff)
    return _staff_out(db_staff)


@router.put("/{staff_id}", response_model=StaffInDB, summary="تحديث بيانات موظف")
async def update_staff(staff_id: int, staff: StaffUpdate, db = Depends(get_db), _ = Depends(get_current_user)):
    """تحديث بيانات موظف"""
    db_staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not db_staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موظف بالمعرف المحدد"
        )
    
    update_data = staff.model_dump(exclude_unset=True)
    profile = update_data.pop("hr_profile", None)
    for field, value in update_data.items():
        setattr(db_staff, field, value)
    if profile is not None:
        db_staff.hr_profile = json.dumps(profile, ensure_ascii=False)
    
    db.commit()
    db.refresh(db_staff)
    return _staff_out(db_staff)


@router.delete("/{staff_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف موظف")
async def delete_staff(staff_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف موظف (للمدير فقط)"""
    db_staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not db_staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد موظف بالمعرف المحدد"
        )
    
    db.delete(db_staff)
    db.commit()
    return None


@router.post("/{staff_id}/documents", response_model=StaffDocumentInDB, status_code=201,
             summary="رفع مستند موظف")
async def upload_staff_document(
    staff_id: int,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db=Depends(get_db),
    _: User=Depends(require_admin),
):
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(404, "الموظف غير موجود")
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, "نوع المستند غير صالح")
    original = file.filename or "document"
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "نوع الملف غير مسموح")
    content = await file.read()
    if not content:
        raise HTTPException(400, "الملف فارغ")
    if len(content) > MAX_SIZE:
        raise HTTPException(413, "حجم الملف يتجاوز 10 ميجابايت")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as f:
        f.write(content)
    row = StaffDocument(staff_id=staff.id, doc_type=doc_type, original_name=original,
                        stored_name=stored, content_type=file.content_type or "application/octet-stream",
                        size_bytes=len(content))
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.get("/documents/{document_id}/file", summary="تنزيل مستند موظف")
async def download_staff_document(document_id: int, db=Depends(get_db), _: User=Depends(require_admin)):
    row = db.query(StaffDocument).filter(StaffDocument.id == document_id).first()
    if not row:
        raise HTTPException(404, "المستند غير موجود")
    path = os.path.join(UPLOAD_DIR, row.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(404, "ملف المستند مفقود")
    return FileResponse(path, media_type=row.content_type, filename=row.original_name)


@router.delete("/documents/{document_id}", status_code=204, summary="حذف مستند موظف")
async def delete_staff_document(document_id: int, db=Depends(get_db), _: User=Depends(require_admin)):
    row = db.query(StaffDocument).filter(StaffDocument.id == document_id).first()
    if not row:
        raise HTTPException(404, "المستند غير موجود")
    path = os.path.join(UPLOAD_DIR, row.stored_name)
    if os.path.isfile(path):
        try: os.remove(path)
        except OSError: pass
    db.delete(row); db.commit()
    return None