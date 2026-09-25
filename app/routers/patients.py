from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Patient, User, Attachment
from app.schemas import PatientCreate, PatientUpdate, PatientInDB
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("/", response_model=List[PatientInDB], summary="عرض قائمة المرضى")
def list_patients(
    search: Optional[str] = Query(None, description="بحث بالاسم أو رقم الهاتف"),
    blood_type: Optional[str] = Query(None, description="فلترة حسب مجموعة الدم"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """جلب المرضى مع إمكانية البحث والفلترة — متزامن (threadpool) لأجل استجابة أسرع"""
    q = db.query(Patient)
    if search:
        q = q.filter(
            (Patient.full_name.contains(search))
            | (Patient.phone.contains(search))
            | (Patient.national_id.contains(search))
        )
    if blood_type:
        q = q.filter(Patient.blood_type == blood_type)
    return q.order_by(Patient.created_at.desc()).all()


# أسماء الأعمدة المقبولة في ملف الاستيراد (عربي + إنجليزي)
_IMPORT_ALIASES = {
    "full_name": "full_name", "name": "full_name",
    "الاسم": "full_name", "الاسم الكامل": "full_name",
    "date_of_birth": "date_of_birth", "dob": "date_of_birth",
    "تاريخ الميلاد": "date_of_birth", "الميلاد": "date_of_birth",
    "gender": "gender", "النوع": "gender", "الجنس": "gender",
    "phone": "phone", "الهاتف": "phone", "رقم الهاتف": "phone",
    "الجوال": "phone", "جوال": "phone",
    "email": "email", "البريد": "email", "البريد الإلكتروني": "email",
    "address": "address", "العنوان": "address",
    "blood_type": "blood_type", "مجموعة الدم": "blood_type", "الدم": "blood_type",
    "national_id": "national_id", "الهوية": "national_id",
    "الهوية الوطنية": "national_id", "الهوية الاقامة": "national_id", "الإقامة": "national_id",
    "insurer": "insurer", "شركة التأمين": "insurer", "التأمين": "insurer",
    "policy_number": "policy_number", "رقم الوثيقة": "policy_number", "الوثيقة": "policy_number",
}


@router.get("/export.csv", summary="تصدير المرضى إلى CSV (Excel)")
async def export_patients_csv(db = Depends(get_db), _ = Depends(get_current_user)):
    """تصدير كل المرضى إلى CSV بترميز UTF-8 + BOM ليُفتح مباشرة في Excel"""
    import csv as _csv
    import io as _io
    from fastapi.responses import Response

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["الاسم الكامل", "تاريخ الميلاد", "النوع", "الهاتف", "البريد", "العنوان",
                "مجموعة الدم", "الهوية الوطنية", "شركة التأمين", "رقم الوثيقة"])
    for p in db.query(Patient).order_by(Patient.id.asc()).all():
        w.writerow([
            p.full_name,
            p.date_of_birth.strftime("%Y-%m-%d") if p.date_of_birth else "",
            p.gender.value, p.phone or "", p.email or "",
            p.address or "", p.blood_type or "",
            p.national_id or "", p.insurer or "", p.policy_number or "",
        ])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="patients.csv"'},
    )


@router.post("/import", summary="استيراد مرضى من ملف CSV")
async def import_patients_csv(
    file: UploadFile = File(..., description="ملف CSV — ترميز UTF-8 أو cp1256"),
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """استيراد دفعة مرضى — يتجاهل المكرّر (حسب البريد) ويردّ تقرير أخطاء بالسطور"""
    import csv as _csv
    import io as _io
    from datetime import datetime as _dt
    from pydantic import ValidationError

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="حجم الملف يتجاوز 5MB")

    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1256"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(status_code=400, detail="تعذّر قراءة ترميز الملف — استخدم UTF-8")

    try:
        reader = _csv.DictReader(_io.StringIO(text))
        rows = list(reader)
    except _csv.Error as e:
        raise HTTPException(status_code=400, detail=f"ملف CSV غير صالح: {e}")
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="الملف لا يحتوي على صف عناوين")
    if len(rows) > 5000:
        raise HTTPException(status_code=400, detail="عدد الصفوف يتجاوز 5000")

    created = skipped = 0
    errors = []
    seen = set()
    for idx, row in enumerate(rows, start=2):  # السطر 1 = العناوين
        if not any((v or "").strip() for v in row.values()):
            continue
        norm = {}
        for k, v in row.items():
            key = (k or "").strip()
            mapped = _IMPORT_ALIASES.get(key.lower()) or _IMPORT_ALIASES.get(key)
            if mapped and v is not None:
                norm[mapped] = v.strip()
        # تطبيع قيم الجنس
        g = norm.get("gender", "").strip().lower()
        if g in ("ذكر", "male", "m", "ذ"):
            norm["gender"] = "ذكر"
        elif g in ("أنثى", "انثى", "female", "f", "أنثي"):
            norm["gender"] = "أنثى"
        # تطبيع صيغ التواريخ
        dob = norm.get("date_of_birth", "")
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                norm["date_of_birth"] = _dt.strptime(dob, fmt).isoformat()
                break
            except ValueError:
                continue
        try:
            pc = PatientCreate(**norm)
        except ValidationError as e:
            if len(errors) < 50:
                err = e.errors()[0]
                field = ".".join(str(x) for x in err["loc"])
                errors.append({"row": idx, "error": f"{field}: {err['msg']}"})
            continue
        email_key = str(pc.email).lower()
        nat_key = (pc.national_id or "").strip()
        if email_key in seen or db.query(Patient).filter(Patient.email == pc.email).first():
            skipped += 1
            seen.add(email_key)
            continue
        if nat_key and (
            db.query(Patient).filter(Patient.national_id == nat_key).first()
        ):
            skipped += 1
            seen.add(email_key)
            continue
        db.add(Patient(
            full_name=pc.full_name, date_of_birth=pc.date_of_birth,
            gender=pc.gender, phone=pc.phone, email=pc.email,
            address=pc.address, blood_type=pc.blood_type,
            national_id=pc.national_id, insurer=pc.insurer,
            policy_number=pc.policy_number,
        ))
        seen.add(email_key)
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


@router.get("/{patient_id}", response_model=PatientInDB, summary="عرض مريض معين")
async def get_patient(patient_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب مريض بواسطة المعرف"""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد مريض بالمعرف المحدد"
        )
    return patient


@router.get("/{patient_id}/pdf", summary="الملف الشامل للمريض (PDF)")
async def download_patient_file_pdf(
    patient_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """توليد ملف PDF شامل: بيانات + سجلات + مواعيد + فواتير + مرفقات"""
    from fastapi.responses import Response
    from app.pdf_utils import patient_file_pdf
    from app.auth import get_user_role

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="لا يوجد مريض بالمعرف المحدد")

    # الطبيب يقرأ ملفات مرضاه فقط
    role = get_user_role(current_user)
    if role == "doctor":
        allowed = any(
            (r.doctor and r.doctor.email == current_user.email)
            for r in patient.medical_records
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="لا تصلحية لعرض ملف هذا المريض")

    pdf_bytes = patient_file_pdf(
        patient,
        records=list(patient.medical_records),
        appointments=sorted(patient.appointments, key=lambda a: a.appointment_date, reverse=True),
        invoices=list(patient.invoices),
        attachments=list(db.query(Attachment).filter(Attachment.patient_id == patient_id).all()),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="patient_{patient_id}_file.pdf"'},
    )


@router.post("/", response_model=PatientInDB, summary="إضافة مريض جديد")
async def create_patient(patient: PatientCreate, db = Depends(get_db), _ = Depends(get_current_user)):
    """إضافة مريض جديد"""
    # التحقق من عدم تكرار البريد الإلكتروني
    existing_patient = db.query(Patient).filter(Patient.email == patient.email).first()
    if existing_patient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="هذا البريد الإلكتروني مسجل بالفعل"
        )
    # الهوية الوطنية مميزة إن وُجدت
    if patient.national_id:
        nat_taken = db.query(Patient).filter(Patient.national_id == patient.national_id).first()
        if nat_taken:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="هذه الهوية الوطنية مسجلة لpatient آخر"
            )

    db_patient = Patient(
        full_name=patient.full_name,
        date_of_birth=patient.date_of_birth,
        gender=patient.gender,
        phone=patient.phone,
        email=patient.email,
        address=patient.address,
        blood_type=patient.blood_type,
        national_id=patient.national_id,
        insurer=patient.insurer,
        policy_number=patient.policy_number,
    )
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    return db_patient


@router.put("/{patient_id}", response_model=PatientInDB, summary="تحديث بيانات مريض")
async def update_patient(patient_id: int, patient: PatientUpdate, db = Depends(get_db), _ = Depends(get_current_user)):
    """تحديث بيانات مريض"""
    db_patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not db_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد مريض بالمعرف المحدد"
        )
    
    update_data = patient.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_patient, field, value)
    
    db.commit()
    db.refresh(db_patient)
    return db_patient


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف مريض")
async def delete_patient(patient_id: int, db = Depends(get_db), _: User = Depends(require_admin)):
    """حذف مريض (للمدير فقط — يحذف فواتيره ومواعيده وسجلاته تبعًا للـ Cascade)"""
    db_patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not db_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد مريض بالمعرف المحدد"
        )
    
    db.delete(db_patient)
    db.commit()
    return None