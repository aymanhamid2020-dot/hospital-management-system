from fastapi import (
    APIRouter, Depends, HTTPException, status, Query, File, UploadFile, Response,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date
from typing import List, Optional

from app.database import get_db
from app.models import (
    Patient, User, Attachment, Appointment, MedicalRecord, LabOrder,
    Prescription, Invoice, Dispense, VitalSign, InsuranceClaim, ClaimStatus,
    InvoiceStatus,
)
from app.schemas import (
    PatientCreate, PatientUpdate, PatientInDB, PatientProfileUpdate,
    PatientListItem, VitalSignCreate, VitalSignUpdate, VitalSignInDB,
    InsuranceClaimCreate, InsuranceClaimUpdate, InsuranceClaimInDB,
)
from app.auth import get_current_user, require_admin, get_user_role

router = APIRouter(prefix="/patients", tags=["Patients"])


def _age_at(dob, today=None) -> Optional[int]:
    """العمر بالسنوات من تاريخ الميلاد."""
    if not dob:
        return None
    today = today or date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return max(years, 0)


@router.get("/", response_model=List[PatientListItem], summary="عرض قائمة المرضى")
def list_patients(
    search: Optional[str] = Query(None, description="بحث بالاسم/الهاتف/الهوية/البريد"),
    blood_type: Optional[str] = Query(None, description="فلترة حسب مجموعة الدم"),
    alert: Optional[str] = Query(None, description="has = من له حساسية أو تحذير طبي"),
    sort: Optional[str] = Query("created", description="created | name | age"),
    dir: Optional[str] = Query(None, description="asc | desc (افتراضي: created تنازليًا)"),
    limit: int = Query(0, ge=0, le=500, description="0 = بلا حد (الكل)"),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db = Depends(get_db),
    _ = Depends(get_current_user),
):
    """جلب المرضى مع بحث وفلاتر وترقيم — متزامن (threadpool) لأجل استجابة أسرع.

    يبقى الاستجابة **قائمة** (لتوافق الاستهلاك القائم) ويصل العدد الكلي
    في الترويسة `X-Total-Count` لحساب صفحات الواجهة.
    """
    q = db.query(Patient)
    if search:
        # ilike ⇒ بحث غير حسّاس لحالة الأحرف على SQLite وPostgreSQL معًا
        like = f"%{search.strip()}%"
        q = q.filter(
            Patient.full_name.ilike(like)
            | Patient.phone.ilike(like)
            | Patient.national_id.ilike(like)
            | Patient.email.ilike(like)
        )
    if blood_type:
        q = q.filter(Patient.blood_type == blood_type)
    if (alert or "").lower() == "has":
        q = q.filter(
            (Patient.allergies.isnot(None)) & (Patient.allergies != "")
            | (Patient.medical_warnings.isnot(None)) & (Patient.medical_warnings != "")
        )

    total = q.count()

    # الاتجاه: يُقرأ من ?dir إن أُرسل، وإلا الافتراضي الأنسب لكل حقل
    ascending = (dir or "").lower() == "asc"
    descending = (dir or "").lower() == "desc"
    if sort == "name":
        col, dflt_desc = Patient.full_name, False
    elif sort == "age":
        col, dflt_desc = Patient.date_of_birth, False
    else:
        col, dflt_desc = Patient.created_at, True
    if ascending:
        q = q.order_by(col.asc(), Patient.id.asc())
    elif descending:
        q = q.order_by(col.desc(), Patient.id.desc())
    elif dflt_desc:
        q = q.order_by(col.desc(), Patient.id.desc())
    else:
        q = q.order_by(col.asc(), Patient.id.asc())

    rows = q.offset(offset).limit(limit).all() if limit else q.all()
    if response is not None:
        response.headers["X-Total-Count"] = str(total)

    if not rows:
        return []

    # استعلامان مجمّعان لكل الصفحة (لا N+1): آخر/قادم موعد، والمتبقي المالي
    ids = [p.id for p in rows]
    today = date.today()
    last_visit, upcoming, outstanding = {}, {}, {}
    for a in (db.query(Appointment.patient_id, Appointment.appointment_date)
              .filter(Appointment.patient_id.in_(ids)).all()):
        d = a.appointment_date.date() if a.appointment_date else None
        if not d:
            continue
        if d < today:
            if a.patient_id not in last_visit or d > last_visit[a.patient_id]:
                last_visit[a.patient_id] = d
        elif a.patient_id not in upcoming or d < upcoming[a.patient_id]:
            upcoming[a.patient_id] = d

    # استعلامان مجمّعان لكل الصفحة (لا N+1): آخر/قادم موعد، والمتبقي المالي.
    # الإجمالي يُحسب في Python لأن Invoice.total خاصية محسوبة (خصم + ضريبة)،
    # ولا يصلح وضعها داخل SUM على مستوى SQL — فنجلب أعمدة الفاتورة ونحسبها
    # بنفس معادلة النموذج (مجموع صفحة واحدة فقط).
    ids = [p.id for p in rows]
    today = date.today()
    last_visit, upcoming, outstanding = {}, {}, {}
    for a in (db.query(Appointment.patient_id, Appointment.appointment_date)
              .filter(Appointment.patient_id.in_(ids)).all()):
        d = a.appointment_date.date() if a.appointment_date else None
        if not d:
            continue
        if d < today:
            if a.patient_id not in last_visit or d > last_visit[a.patient_id]:
                last_visit[a.patient_id] = d
        elif a.patient_id not in upcoming or d < upcoming[a.patient_id]:
            upcoming[a.patient_id] = d

    for inv in (db.query(Invoice.patient_id, Invoice.amount, Invoice.discount,
                         Invoice.tax_rate, Invoice.paid_amount)
                .filter(Invoice.patient_id.in_(ids)).all()):
        net = round(float(inv.amount or 0) - float(inv.discount or 0), 2)
        total = round(net + round(net * float(inv.tax_rate or 0) / 100.0, 2), 2)
        rest = total - float(inv.paid_amount or 0)
        if rest > 0:
            outstanding[inv.patient_id] = outstanding.get(inv.patient_id, 0.0) + rest

    dsp = (db.query(Dispense.patient_id,
                    func.sum(Dispense.total_price - func.coalesce(Dispense.paid_amount, 0)))
           .filter(Dispense.patient_id.in_(ids), Dispense.returned_at.is_(None))
           .group_by(Dispense.patient_id).all())
    for pid, val in dsp:
        if float(val or 0) > 0:
            outstanding[pid] = outstanding.get(pid, 0.0) + float(val)

    items = []
    for p in rows:
        d = PatientInDB.model_validate(p).model_dump()
        d["age"] = _age_at(p.date_of_birth, today)
        d["has_alerts"] = bool(p.allergies or p.medical_warnings)
        d["last_visit"] = last_visit.get(p.id)
        d["upcoming"] = upcoming.get(p.id)
        d["outstanding"] = round(max(0.0, outstanding.get(p.id, 0.0)), 2)
        items.append(PatientListItem(**d))
    return items


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
    # الملف الشخصي والإداري + التاريخ الطبي (الحقول الجديدة)
    "nationality": "nationality", "الجنسية": "nationality",
    "smoking_status": "smoking_status", "التدخين": "smoking_status",
    "emergency_contact_name": "emergency_contact_name", "جهة الطوارئ": "emergency_contact_name",
    "emergency_contact_phone": "emergency_contact_phone", "هاتف الطوارئ": "emergency_contact_phone",
    "emergency_contact_relation": "emergency_contact_relation",
    "صلة القرابة": "emergency_contact_relation",
    "insurance_grade": "insurance_grade", "درجة التغطية": "insurance_grade",
    "insurance_copay": "insurance_copay", "نسبة التحمل": "insurance_copay",
    "chronic_conditions": "chronic_conditions", "الأمراض المزمنة": "chronic_conditions",
    "past_surgeries": "past_surgeries", "العمليات السابقة": "past_surgeries",
    "family_history": "family_history", "التاريخ العائلي": "family_history",
    "allergies": "allergies", "الحساسية": "allergies",
    "medical_warnings": "medical_warnings", "التحذيرات": "medical_warnings",
}


# أعمدة التصدير: (الترويسة العربية، الحقل في النموذج) — نفس ترتيب الترويسات
# التي يقبلها الاستيراد، فتصدير ثم استيراد الملف لا يفقد أي حقل.
_EXPORT_COLUMNS = [
    ("الاسم الكامل", "full_name"), ("تاريخ الميلاد", "date_of_birth"),
    ("النوع", "gender"), ("الهاتف", "phone"), ("البريد", "email"),
    ("العنوان", "address"), ("مجموعة الدم", "blood_type"),
    ("الهوية الوطنية", "national_id"), ("شركة التأمين", "insurer"),
    ("رقم الوثيقة", "policy_number"),
    ("الجنسية", "nationality"), ("التدخين", "smoking_status"),
    ("جهة الطوارئ", "emergency_contact_name"), ("هاتف الطوارئ", "emergency_contact_phone"),
    ("صلة القرابة", "emergency_contact_relation"),
    ("درجة التغطية", "insurance_grade"), ("نسبة التحمل", "insurance_copay"),
    ("الأمراض المزمنة", "chronic_conditions"), ("العمليات السابقة", "past_surgeries"),
    ("التاريخ العائلي", "family_history"), ("الحساسية", "allergies"),
    ("التحذيرات", "medical_warnings"),
]



@router.get("/export.csv", summary="تصدير المرضى إلى CSV (Excel)")
async def export_patients_csv(db = Depends(get_db), _ = Depends(get_current_user)):
    """تصدير كل المرضى إلى CSV بترميز UTF-8 + BOM ليُفتح مباشرة في Excel"""
    import csv as _csv
    import io as _io
    from fastapi.responses import Response

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow([head for head, _ in _EXPORT_COLUMNS])
    for p in db.query(Patient).order_by(Patient.id.asc()).all():
        row = []
        for _, field in _EXPORT_COLUMNS:
            v = getattr(p, field, None)
            if field == "date_of_birth":
                v = v.strftime("%Y-%m-%d") if v else ""
            elif hasattr(v, "value"):        # حقول Enum (النوع)
                v = v.value
            row.append("" if v is None else v)
        w.writerow(row)
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
        # خلايا CSV الفارغة في الحقول الاختيارية تُهمَل (وإلا رُفض الصف كله)
        for k, v in list(norm.items()):
            if v == "" and k in PatientCreate.model_fields:
                norm[k] = None
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
        # تمرير كل الحقول المعروفة (بما فيها حقول الملف الجديدة) دون تكرارها هنا
        known = PatientCreate.model_fields
        db.add(Patient(**{f: getattr(pc, f) for f in known if f in norm}))
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

    # كل حقول النموذج تُمرَّر كما هي (كانت تُكتب يدويًا ⇒ تُسقط الحقول الجديدة)
    db_patient = Patient(**patient.model_dump())
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    return db_patient


# ══════════ شاشة ملف المريض: الأقسام الستة في نقطة واحدة ══════════


def _get_patient_or_404(db: Session, patient_id: int) -> Patient:
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="لا يوجد مريض بالمعرف المحدد",
        )
    return p


def _can_view_chart(db: Session, patient: Patient, user: User) -> bool:
    """الطبيب يرى ملف مريضه فقط (له سجل)، والمدير/الموظف يريان الكل."""
    if get_user_role(user) != "doctor":
        return True
    return any(r.doctor and r.doctor.email == user.email
               for r in patient.medical_records)


@router.get("/{patient_id}/chart", summary="ملف المريض المجمّع (الأقسام الستة)")
async def patient_chart(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """الأقسام الستة في استدعاء واحد: الملف الشخصي · السجل الطبي · المواعيد ·
    الفحوصات والوصفات · الحسابات والمطالبات · المرفقات."""
    from datetime import date as _date
    from app.schemas import (
        PatientInDB, MedicalRecordInDB, AttachmentInDB, VitalSignInDB,
        InsuranceClaimInDB,
    )

    p = _get_patient_or_404(db, patient_id)
    if not _can_view_chart(db, p, current_user):
        raise HTTPException(status_code=403, detail="لا صلاحية لعرض ملف هذا المريض")

    today = _date.today()
    records = (db.query(MedicalRecord)
               .filter(MedicalRecord.patient_id == patient_id)
               .order_by(MedicalRecord.created_at.desc()).all())
    vitals = (db.query(VitalSign)
              .filter(VitalSign.patient_id == patient_id)
              .order_by(VitalSign.recorded_at.desc()).all())

    appts = (db.query(Appointment)
             .filter(Appointment.patient_id == patient_id)
             .order_by(Appointment.appointment_date.desc()).all())
    past_appts = [a for a in appts
                  if a.appointment_date and a.appointment_date.date() < today]
    upcoming = [a for a in appts
                if a.appointment_date and a.appointment_date.date() >= today]

    labs = (db.query(LabOrder)
            .filter(LabOrder.patient_id == patient_id)
            .order_by(LabOrder.ordered_at.desc()).all())
    prescriptions = (db.query(Prescription)
                     .filter(Prescription.patient_id == patient_id)
                     .order_by(Prescription.created_at.desc()).all())
    dispenses = (db.query(Dispense)
                 .filter(Dispense.patient_id == patient_id,
                         Dispense.returned_at.is_(None))
                 .order_by(Dispense.created_at.desc()).all())
    invoices = (db.query(Invoice)
                .filter(Invoice.patient_id == patient_id)
                .order_by(Invoice.created_at.desc()).all())
    claims = (db.query(InsuranceClaim)
              .filter(InsuranceClaim.patient_id == patient_id)
              .order_by(InsuranceClaim.submitted_at.desc()).all())
    attachments = (db.query(Attachment)
                   .filter(Attachment.patient_id == patient_id)
                   .order_by(Attachment.uploaded_at.desc()).all())

    inv_total = round(sum(float(i.total or 0) for i in invoices), 2)
    inv_paid = round(sum(float(i.paid_amount or 0) for i in invoices), 2)
    sales_total = round(sum(float(s.total_price or 0) for s in dispenses), 2)
    sales_paid = round(sum(float(s.paid_amount or 0) for s in dispenses), 2)

    return {
        "profile": PatientInDB.model_validate(p),
        "records": [MedicalRecordInDB.model_validate(r) for r in records],
        "vitals": [VitalSignInDB.model_validate(v) for v in vitals],
        "appointments": {
            "past": past_appts, "upcoming": upcoming,
            "upcoming_total": len(upcoming),
        },
        "lab_orders": labs,
        "prescriptions": prescriptions,
        "dispenses": dispenses,
        "invoices": invoices,
        "financials": {
            "invoices_total": inv_total, "invoices_paid": inv_paid,
            "sales_total": sales_total, "sales_paid": sales_paid,
            "dues": round(inv_total + sales_total, 2),
            "outstanding": round((inv_total - inv_paid) + (sales_total - sales_paid), 2),
        },
        "claims": [InsuranceClaimInDB.model_validate(c) for c in claims],
        "attachments": [AttachmentInDB.model_validate(a) for a in attachments],
    }


@router.put("/{patient_id}/profile", response_model=PatientInDB,
            summary="تحديث الملف الشخصي والتاريخ الطبي")
async def update_patient_profile(
    patient_id: int,
    profile: PatientProfileUpdate,
    db = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """تحديث بيانات الملف الشخصي/الإداري والتاريخ الطبي والتحذيرات."""
    db_patient = _get_patient_or_404(db, patient_id)
    for field, value in profile.model_dump(exclude_unset=True).items():
        setattr(db_patient, field, value)
    db.commit()
    db.refresh(db_patient)
    return db_patient


# ══════════ العلامات الحيوية ══════════
@router.get("/{patient_id}/vitals", response_model=List[VitalSignInDB],
            summary="سجل العلامات الحيوية للمريض")
async def list_vitals(patient_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    _get_patient_or_404(db, patient_id)
    return (db.query(VitalSign)
            .filter(VitalSign.patient_id == patient_id)
            .order_by(VitalSign.recorded_at.desc()).all())


@router.post("/{patient_id}/vitals", response_model=VitalSignInDB, status_code=201,
             summary="تسجيل علامات حيوية")
async def create_vital(
    patient_id: int,
    vitals: VitalSignCreate,
    db = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """تسجيل قراءة جديدة (ضغط/حرارة/نبض/وزن/طول) لمريض."""
    _get_patient_or_404(db, patient_id)
    if all(getattr(vitals, f) is None for f in
           ("systolic", "diastolic", "temperature", "pulse", "weight", "height")):
        raise HTTPException(status_code=400, detail="أدخل قياسًا واحدًا على الأقل")
    if (vitals.systolic and not vitals.diastolic) or (vitals.diastolic and not vitals.systolic):
        raise HTTPException(status_code=400, detail="أدخل الضغط الانقباضي والانبساطي معًا")

    v = VitalSign(patient_id=patient_id, **vitals.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.put("/{patient_id}/vitals/{vital_id}", response_model=VitalSignInDB,
            summary="تعديل قياس حيوي")
async def update_vital(
    patient_id: int,
    vital_id: int,
    vitals: VitalSignUpdate,
    db = Depends(get_db),
    _: User = Depends(get_current_user),
):
    v = (db.query(VitalSign)
         .filter(VitalSign.id == vital_id, VitalSign.patient_id == patient_id).first())
    if not v:
        raise HTTPException(status_code=404, detail="القياس غير موجود")
    for field, value in vitals.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    db.commit()
    db.refresh(v)
    return v


@router.delete("/{patient_id}/vitals/{vital_id}", status_code=204, summary="حذف قياس")
async def delete_vital(
    patient_id: int,
    vital_id: int,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    v = (db.query(VitalSign)
         .filter(VitalSign.id == vital_id, VitalSign.patient_id == patient_id).first())
    if not v:
        raise HTTPException(status_code=404, detail="القياس غير موجود")
    db.delete(v)
    db.commit()
    return None


# ══════════ مطالبات التأمين ══════════
@router.get("/{patient_id}/claims", response_model=List[InsuranceClaimInDB],
            summary="مطالبات تأمين المريض")
async def list_claims(patient_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    _get_patient_or_404(db, patient_id)
    return (db.query(InsuranceClaim)
            .filter(InsuranceClaim.patient_id == patient_id)
            .order_by(InsuranceClaim.submitted_at.desc()).all())


@router.post("/{patient_id}/claims", response_model=InsuranceClaimInDB, status_code=201,
             summary="تقديم مطالبة تأمين")
async def create_claim(
    patient_id: int,
    claim: InsuranceClaimCreate,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تقديم مطالبة جديدة — شركة التأمين تُورَث من المريض إن لم تُحدد."""
    p = _get_patient_or_404(db, patient_id)
    if db.query(InsuranceClaim).filter(
            InsuranceClaim.patient_id == patient_id,
            InsuranceClaim.claim_number == claim.claim_number).first():
        raise HTTPException(status_code=400, detail="رقم المطالبة مسجّل مسبقًا لهذا المريض")

    if claim.invoice_id is not None:
        inv = (db.query(Invoice)
               .filter(Invoice.id == claim.invoice_id,
                       Invoice.patient_id == patient_id).first())
        if not inv:
            raise HTTPException(status_code=404, detail="الفاتورة غير موجودة لهذا المريض")

    c = InsuranceClaim(
        patient_id=patient_id,
        claim_number=claim.claim_number,
        insurer=claim.insurer or p.insurer,
        amount=claim.amount,
        invoice_id=claim.invoice_id,
        decision_notes=claim.decision_notes,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.put("/{patient_id}/claims/{claim_id}", response_model=InsuranceClaimInDB,
            summary="تحديث/قرار مطالبة (موافقة · رفض · سداد)")
async def decide_claim(
    patient_id: int,
    claim_id: int,
    payload: InsuranceClaimUpdate,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تحديث بيانات المطالبة أو تثبيت قرار شركة التأمين.

    الموافقة تتطلب approved_amount، والرفض يتطلب سببًا مكتوبًا.
    """
    from datetime import datetime
    c = (db.query(InsuranceClaim)
         .filter(InsuranceClaim.id == claim_id,
                 InsuranceClaim.patient_id == patient_id).first())
    if not c:
        raise HTTPException(status_code=404, detail="المطالبة غير موجودة")

    data = payload.model_dump(exclude_unset=True)
    new_status = data.get("status", c.status)

    if new_status == ClaimStatus.APPROVED and \
            data.get("approved_amount", c.approved_amount) is None:
        raise HTTPException(
            status_code=400,
            detail="حدد القيمة الموافق عليها (approved_amount) عند الموافقة")
    if new_status == ClaimStatus.REJECTED and \
            not (data.get("rejection_reason") or c.rejection_reason):
        raise HTTPException(status_code=400, detail="اذكر سبب الرفض")

    for field, value in data.items():
        setattr(c, field, value)
    if new_status in (ClaimStatus.APPROVED, ClaimStatus.REJECTED, ClaimStatus.PAID):
        c.decided_at = datetime.now()
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{patient_id}/claims/{claim_id}", status_code=204,
               summary="حذف مطالبة")
async def delete_claim(
    patient_id: int,
    claim_id: int,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    c = (db.query(InsuranceClaim)
         .filter(InsuranceClaim.id == claim_id,
                 InsuranceClaim.patient_id == patient_id).first())
    if not c:
        raise HTTPException(status_code=404, detail="المطالبة غير موجودة")
    db.delete(c)
    db.commit()
    return None


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