"""واجهة خطط الرعاية القابلة للتنفيذ وربطها بالمرضى والتنويم والطلبات."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.clinical_schemas import (
    CarePlanCreate, CarePlanExecutionCreate, CarePlanItemCreate, CarePlanOut,
)
from app.database import get_db
from app.models import (
    Admission, CarePlan, CarePlanExecution, CarePlanItem, Doctor, Patient,
    ServiceRequest, User,
)

router = APIRouter(prefix="/clinical", tags=["خطط الرعاية"])


def _patient(db: Session, patient_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(404, "المريض غير موجود")
    return patient


def _plan(db: Session, plan_id: int) -> CarePlan:
    plan = db.query(CarePlan).filter(CarePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "خطة الرعاية غير موجودة")
    return plan


def _out(plan: CarePlan) -> CarePlanOut:
    total = len(plan.items)
    completed = sum(item.status == "completed" for item in plan.items)
    result = CarePlanOut.model_validate(plan)
    percentage = round(completed * 100 / total, 1) if total else 0
    return result.model_copy(update={"completion_percentage": percentage})


def _validate_relations(db: Session, payload: CarePlanCreate) -> None:
    _patient(db, payload.patient_id)
    if payload.service_request_id:
        request = db.query(ServiceRequest).filter(
            ServiceRequest.id == payload.service_request_id).first()
        if not request:
            raise HTTPException(404, "طلب الخدمة غير موجود")
        if request.patient_id != payload.patient_id:
            raise HTTPException(422, "طلب الخدمة لا يخص المريض نفسه")
    if payload.admission_id:
        admission = db.query(Admission).filter(Admission.id == payload.admission_id).first()
        if not admission:
            raise HTTPException(404, "التنويم غير موجود")
        if admission.patient_id != payload.patient_id:
            raise HTTPException(422, "التنويم لا يخص المريض نفسه")
    if payload.responsible_doctor_id and not db.query(Doctor).filter(
        Doctor.id == payload.responsible_doctor_id).first():
        raise HTTPException(404, "الطبيب المسؤول غير موجود")


@router.get("/care-plans")
def list_care_plans(
    patient_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CarePlan)
    if patient_id is not None:
        query = query.filter(CarePlan.patient_id == patient_id)
    if status:
        query = query.filter(CarePlan.status == status)
    return [_out(plan) for plan in query.order_by(CarePlan.id.desc()).limit(limit).all()]


@router.post("/care-plans", response_model=CarePlanOut, status_code=201)
def create_care_plan(
    payload: CarePlanCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _validate_relations(db, payload)
    values = payload.model_dump(exclude={"items"})
    plan = CarePlan(**values, created_by=current_user.username)
    plan.items = [CarePlanItem(**item.model_dump()) for item in payload.items]
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _out(plan)


@router.get("/care-plans/{plan_id}", response_model=CarePlanOut)
def get_care_plan(
    plan_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _out(_plan(db, plan_id))


@router.post("/care-plans/{plan_id}/items")
def add_item(
    plan_id: int,
    payload: CarePlanItemCreate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    plan = _plan(db, plan_id)
    if plan.status != "active":
        raise HTTPException(409, "لا يمكن تعديل بنود خطة غير نشطة")
    item = CarePlanItem(plan_id=plan.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.post("/care-plan-items/{item_id}/execute", status_code=201)
def execute_item(
    item_id: int,
    payload: CarePlanExecutionCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(CarePlanItem).filter(CarePlanItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "بند خطة الرعاية غير موجود")
    if item.plan.status != "active":
        raise HTTPException(409, "لا يمكن تنفيذ بنود خطة غير نشطة")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تنفيذ بند مكتمل أو ملغى")
    duplicate = db.query(CarePlanExecution).filter(
        CarePlanExecution.item_id == item.id,
        CarePlanExecution.executed_at == payload.executed_at,
    ).first()
    if duplicate:
        raise HTTPException(409, "تم تسجيل هذا البند في الوقت نفسه مسبقًا")
    execution = CarePlanExecution(
        item_id=item.id,
        executed_at=payload.executed_at,
        performed_by=current_user.username,
        notes=payload.notes,
        outcome=payload.outcome,
    )
    item.status = "completed" if payload.outcome == "completed" else "failed"
    item.completed_at = payload.executed_at if payload.outcome == "completed" else None
    db.add(execution)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "تم تسجيل هذا البند في الوقت نفسه مسبقًا")
    db.refresh(execution)
    return execution


@router.post("/care-plans/{plan_id}/complete", response_model=CarePlanOut)
def complete_plan(
    plan_id: int,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    plan = _plan(db, plan_id)
    if plan.status != "active":
        raise HTTPException(409, "الخطة غير نشطة")
    unfinished = [item.id for item in plan.items if item.status != "completed"]
    if unfinished:
        raise HTTPException(409, f"لا يمكن إكمال الخطة قبل تنفيذ البنود: {unfinished}")
    plan.status = "completed"
    plan.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return _out(plan)


@router.post("/care-plans/{plan_id}/cancel", response_model=CarePlanOut)
def cancel_plan(
    plan_id: int,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    plan = _plan(db, plan_id)
    if plan.status != "active":
        raise HTTPException(409, "الخطة غير نشطة")
    now = datetime.utcnow()
    plan.status = "cancelled"
    plan.cancelled_at = now
    for item in plan.items:
        if item.status not in {"completed", "cancelled"}:
            item.status = "cancelled"
            item.cancelled_at = now
    db.commit()
    db.refresh(plan)
    return _out(plan)
