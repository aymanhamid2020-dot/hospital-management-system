"""مسارات CRUD للمحاور السريرية والتشغيلية والدعمية والجودة والموارد."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_user_role, require_role, hash_password
from app.database import get_db
from app.models import (
    Admission, Bed, BedStatus, BloodUnit, Budget, CarePlan, Department, Doctor,
    FixedAsset, MaintenanceOrder, NursingTask, Patient, PatientPortalAccount,
    SafetyEvent, ServiceRequest, SterilizationCycle, Surgery, User,
)

router = APIRouter(prefix="/clinical", tags=["المحاور المتقدمة"])

RESOURCES = {
    "service-requests": (ServiceRequest, {"pending", "in_progress", "completed", "cancelled"}, "completed_at"),
    "nursing-tasks": (NursingTask, {"pending", "in_progress", "completed", "cancelled"}, "completed_at"),
    "surgeries": (Surgery, {"scheduled", "in_progress", "completed", "cancelled"}, "completed_at"),
    "admissions": (Admission, {"admitted", "discharged", "transferred"}, "discharge_date"),
    "blood-bank": (BloodUnit, {"available", "reserved", "issued", "quarantined", "discarded"}, None),
    "maintenance": (MaintenanceOrder, {"open", "in_progress", "completed", "cancelled"}, "completed_at"),
    "sterilization": (SterilizationCycle, {"running", "passed", "failed"}, "completed_at"),
    "safety-events": (SafetyEvent, {"open", "investigating", "resolved", "closed"}, "resolved_at"),
    "budgets": (Budget, set(), None),
    "assets": (FixedAsset, {"active", "maintenance", "retired"}, None),
    "patient-portal-accounts": (PatientPortalAccount, set(), None),
}


RESOURCE_SCHEMAS = {
    "service-requests": "ServiceRequestCreate", "nursing-tasks": "NursingTaskCreate",
    "surgeries": "SurgeryCreate", "admissions": "AdmissionCreate",
    "blood-bank": "BloodUnitCreate", "maintenance": "MaintenanceCreate",
    "sterilization": "SterilizationCreate", "safety-events": "SafetyEventCreate",
    "budgets": "BudgetCreate", "assets": "FixedAssetCreate",
    "patient-portal-accounts": "PatientPortalCreate",
}


def _resource(path: str):
    if path not in RESOURCES:
        raise HTTPException(404, "المحور غير موجود")
    return RESOURCES[path]


@router.get("/overview")
def overview(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """مؤشرات حية لعدد الحالات المفتوحة في المحاور الجديدة."""
    def count(model, *states):
        return db.query(model).filter(model.status.in_(states)).count()
    return {
        "service_pending": count(ServiceRequest, "pending", "in_progress"),
        "care_plans_active": count(CarePlan, "active"),
        "nursing_pending": count(NursingTask, "pending", "in_progress"),
        "surgeries_active": count(Surgery, "scheduled", "in_progress"),
        "admitted": count(Admission, "admitted"),
        "blood_available": count(BloodUnit, "available", "reserved"),
        "maintenance_open": count(MaintenanceOrder, "open", "in_progress"),
        "sterilization_running": count(SterilizationCycle, "running"),
        "safety_open": count(SafetyEvent, "open", "investigating"),
        "budget_total": sum((row.allocated_amount or 0) for row in db.query(Budget).all()),
    }


@router.get("/{path}")
def list_items(
    path: str,
    patient_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    service_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model, _, _ = _resource(path)
    if path in ("budgets", "assets", "patient-portal-accounts") and get_user_role(current_user) != "admin":
        raise HTTPException(403, "هذا المحور متاح للمدير فقط")
    query = db.query(model)
    if patient_id is not None and hasattr(model, "patient_id"):
        query = query.filter(model.patient_id == patient_id)
    if status and hasattr(model, "status"):
        query = query.filter(model.status == status)
    if service_type and hasattr(model, "service_type"):
        query = query.filter(model.service_type == service_type)
    rows = query.order_by(model.id.desc()).limit(limit).all()
    if path == "patient-portal-accounts":
        return [{"id": r.id, "patient_id": r.patient_id, "username": r.username,
                 "is_active": r.is_active, "last_login_at": r.last_login_at,
                 "created_at": r.created_at} for r in rows]
    return rows


@router.post("/{path}/status/{item_id}")
def set_status(
    path: str, item_id: int, payload: dict,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    model, allowed, time_field = _resource(path)
    if path in ("budgets", "assets", "patient-portal-accounts") and get_user_role(current_user) != "admin":
        raise HTTPException(403, "هذا المحور متاح للمدير فقط")
    obj = db.query(model).filter(model.id == item_id).first()
    if not obj:
        raise HTTPException(404, "السجل غير موجود")
    status = str(payload.get("status", ""))
    if not allowed:
        raise HTTPException(405, "هذا المحور لا يستخدم دورة حالات")
    if status not in allowed:
        raise HTTPException(422, f"الحالة غير صحيحة؛ المسموح: {', '.join(sorted(allowed))}")
    if isinstance(obj, Admission) and obj.status == "admitted" and obj.bed_id:
        bed = db.query(Bed).filter(Bed.id == obj.bed_id).first()
        if bed:
            bed.status = BedStatus.AVAILABLE
            bed.patient_id = None
    obj.status = status
    if time_field and status in ("completed", "discharged", "resolved", "closed"):
        setattr(obj, time_field, datetime.now(timezone.utc).replace(tzinfo=None))
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{path}/{item_id}")
def update_item(
    path: str, item_id: int, payload: dict,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    model, _, _ = _resource(path)
    if path in ("budgets", "assets", "patient-portal-accounts") and get_user_role(current_user) != "admin":
        raise HTTPException(403, "هذه المحور يتطلب صلاحية المدير")
    obj = db.query(model).filter(model.id == item_id).first()
    if not obj:
        raise HTTPException(404, "السجل غير موجود")
    allowed = {c.name for c in model.__table__.columns} - {
        "id", "created_at", "created_by", "reported_by", "hashed_password", "username", "patient_id"}
    for key, value in payload.items():
        if key in allowed:
            setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return obj



@router.post("/{path}")
def create_item(path: str, payload: dict,
                current_user: User = Depends(require_role("admin", "doctor")),
                db: Session = Depends(get_db)):
    """إنشاء سجل مع التحقق من الروابط وقواعد الحالات."""
    from app.clinical_schemas import (
        AdmissionCreate, BloodUnitCreate, BudgetCreate, FixedAssetCreate,
        MaintenanceCreate, NursingTaskCreate, PatientPortalCreate, SafetyEventCreate,
        ServiceRequestCreate, SterilizationCreate, SurgeryCreate,
    )
    if path not in RESOURCES:
        raise HTTPException(404, "المحور غير موجود")
    if path in ("budgets", "assets", "patient-portal-accounts") and get_user_role(current_user) != "admin":
        raise HTTPException(403, "هذا المحور متاح للمدير فقط")
    schema_map = {
        "service-requests": ServiceRequestCreate, "nursing-tasks": NursingTaskCreate,
        "surgeries": SurgeryCreate, "admissions": AdmissionCreate,
        "blood-bank": BloodUnitCreate, "maintenance": MaintenanceCreate,
        "sterilization": SterilizationCreate, "safety-events": SafetyEventCreate,
        "budgets": BudgetCreate, "assets": FixedAssetCreate,
        "patient-portal-accounts": PatientPortalCreate,
    }
    try:
        parsed = schema_map[path].model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors(include_url=False, include_context=False))
    if getattr(parsed, "patient_id", None):
        _patient(db, parsed.patient_id)
    if isinstance(parsed, NursingTaskCreate) and parsed.department_id and not db.query(Department).filter(Department.id == parsed.department_id).first():
        raise HTTPException(404, "القسم غير موجود")
    if isinstance(parsed, SurgeryCreate) and parsed.surgeon_id and not db.query(Doctor).filter(Doctor.id == parsed.surgeon_id).first():
        raise HTTPException(404, "الجراح غير موجود")
    if isinstance(parsed, AdmissionCreate):
        bed = db.query(Bed).filter(Bed.id == parsed.bed_id).first()
        if not bed:
            raise HTTPException(404, "السرير غير موجود")
        if str(getattr(bed.status, "value", bed.status)) != BedStatus.AVAILABLE.value:
            raise HTTPException(409, "السرير غير متاح")
    if isinstance(parsed, PatientPortalCreate):
        if db.query(PatientPortalAccount).filter(
                (PatientPortalAccount.patient_id == parsed.patient_id) |
                (PatientPortalAccount.username == parsed.username)).first():
            raise HTTPException(409, "اسم المستخدم أو المريض مرتبط بحساب موجود")
    data = parsed.model_dump()
    if isinstance(parsed, PatientPortalCreate):
        data.pop("password")
        data["hashed_password"] = hash_password(parsed.password)
    if isinstance(parsed, (ServiceRequestCreate, NursingTaskCreate, SurgeryCreate,
                           AdmissionCreate, MaintenanceCreate, SterilizationCreate)):
        data["created_by"] = current_user.username
    if isinstance(parsed, SafetyEventCreate):
        data["reported_by"] = current_user.username
    item = RESOURCES[path][0](**data)
    if isinstance(item, Admission):
        db.query(Bed).filter(Bed.id == item.bed_id).first().status = BedStatus.OCCUPIED
    db.add(item)
    db.commit()
    db.refresh(item)
    if isinstance(item, PatientPortalAccount):
        return {"id": item.id, "patient_id": item.patient_id, "username": item.username,
                "is_active": item.is_active, "created_at": item.created_at}
    return item


def _patient(db: Session, patient_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(404, "المريض غير موجود")
    return patient
