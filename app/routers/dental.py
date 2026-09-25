"""واجهة طب الأسنان: مخطط المريض، خطط العلاج، والإجراءات."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.clinical_schemas import (
    DentalChartOut, DentalChartUpsert, DentalProcedureCreate, DentalProcedureExecute,
    DentalProcedureOut, DentalTreatmentPlanCreate, DentalTreatmentPlanOut,
)
from app.database import get_db
from app.models import (
    DentalChart, DentalProcedure, DentalTreatmentPlan, Doctor, Patient,
    ServiceRequest, User,
)

router = APIRouter(prefix="/dental", tags=["طب الأسنان"])


def _patient(db: Session, patient_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(404, "المريض غير موجود")
    return patient


def _doctor(db: Session, doctor_id: int | None) -> None:
    if doctor_id and not db.query(Doctor).filter(Doctor.id == doctor_id).first():
        raise HTTPException(404, "الطبيب غير موجود")


def _plan(db: Session, plan_id: int) -> DentalTreatmentPlan:
    plan = db.query(DentalTreatmentPlan).filter(DentalTreatmentPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "خطة العلاج غير موجودة")
    return plan


def _plan_out(plan: DentalTreatmentPlan) -> DentalTreatmentPlanOut:
    total = len(plan.procedures)
    completed = sum(row.status == "completed" for row in plan.procedures)
    result = DentalTreatmentPlanOut.model_validate(plan)
    return result.model_copy(update={
        "completion_percentage": round(completed * 100 / total, 1) if total else 0,
        "total_cost": round(sum(row.cost or 0 for row in plan.procedures), 2),
    })


@router.get("/charts/{patient_id}", response_model=DentalChartOut)
def get_chart(
    patient_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _patient(db, patient_id)
    chart = db.query(DentalChart).filter(DentalChart.patient_id == patient_id).first()
    if not chart:
        raise HTTPException(404, "مخطط الأسنان غير موجود")
    return chart


@router.put("/charts/{patient_id}", response_model=DentalChartOut)
def upsert_chart(
    patient_id: int,
    payload: DentalChartUpsert,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _patient(db, patient_id)
    chart = db.query(DentalChart).filter(DentalChart.patient_id == patient_id).first()
    if not chart:
        chart = DentalChart(patient_id=patient_id, updated_by=current_user.username)
        db.add(chart)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(chart, key, value)
    chart.updated_by = current_user.username
    db.commit()
    db.refresh(chart)
    return chart



@router.get("/plans")
def list_plans(
    patient_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(DentalTreatmentPlan)
    if patient_id is not None:
        query = query.filter(DentalTreatmentPlan.patient_id == patient_id)
    if status:
        query = query.filter(DentalTreatmentPlan.status == status)
    return [_plan_out(plan) for plan in query.order_by(DentalTreatmentPlan.id.desc()).limit(limit).all()]


@router.post("/plans", response_model=DentalTreatmentPlanOut, status_code=201)
def create_plan(
    payload: DentalTreatmentPlanCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _patient(db, payload.patient_id)
    _doctor(db, payload.dentist_id)
    if payload.service_request_id:
        request = db.query(ServiceRequest).filter(ServiceRequest.id == payload.service_request_id).first()
        if not request:
            raise HTTPException(404, "طلب الخدمة غير موجود")
        if request.service_type != "dental" or request.patient_id != payload.patient_id:
            raise HTTPException(422, "يجب ربط الخطة بطلب أسنان يخص المريض نفسه")
    plan = DentalTreatmentPlan(**payload.model_dump(), created_by=current_user.username)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _plan_out(plan)


@router.get("/plans/{plan_id}", response_model=DentalTreatmentPlanOut)
def get_plan(
    plan_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _plan_out(_plan(db, plan_id))


@router.post("/plans/{plan_id}/procedures", response_model=DentalProcedureOut, status_code=201)
def add_procedure(
    plan_id: int,
    payload: DentalProcedureCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    plan = _plan(db, plan_id)
    if plan.status != "active":
        raise HTTPException(409, "لا يمكن إضافة إجراء إلى خطة غير نشطة")
    _doctor(db, payload.dentist_id or plan.dentist_id)
    dentist_id = payload.dentist_id or plan.dentist_id
    procedure = DentalProcedure(
        plan_id=plan.id, dentist_id=dentist_id, created_by=current_user.username,
        **payload.model_dump(exclude={"dentist_id"}),
    )
    db.add(procedure)
    db.commit()
    db.refresh(procedure)
    return procedure

@router.post("/procedures/{procedure_id}/execute", response_model=DentalProcedureOut)
def execute_procedure(
    procedure_id: int,
    payload: DentalProcedureExecute,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    procedure = db.query(DentalProcedure).filter(DentalProcedure.id == procedure_id).first()
    if not procedure:
        raise HTTPException(404, "الإجراء السنخر غير موجود")
    if procedure.plan.status != "active":
        raise HTTPException(409, "لا يمكن تنفيذ إجراء على خطة غير نشطة")
    if procedure.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تنفيذ إجراء مكتمل أو ملغى")
    if procedure.performed_at is not None and procedure.performed_at == payload.performed_at:
        raise HTTPException(409, "سبق تنفيذ هذا الإجراء في الجلسة نفسها")
    duplicate = db.query(DentalProcedure).filter(
        DentalProcedure.plan_id == procedure.plan_id,
        DentalProcedure.tooth_number == procedure.tooth_number,
        DentalProcedure.procedure_type == procedure.procedure_type,
        DentalProcedure.performed_at == payload.performed_at,
        DentalProcedure.id != procedure.id,
    ).first()
    if duplicate:
        raise HTTPException(409, "الإجراء نفسه مسجل للسن في الجلسة نفسها")
    procedure.performed_at = payload.performed_at
    procedure.status = "completed" if payload.outcome == "completed" else "failed"
    procedure.notes = payload.notes
    procedure.material = payload.material
    procedure.cost = round(payload.cost, 2)
    procedure.follow_up_at = payload.follow_up_at
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "الإجراء نفسه مسجل للسن في الجلسة نفسها")
    db.refresh(procedure)
    return procedure


@router.post("/plans/{plan_id}/complete", response_model=DentalTreatmentPlanOut)
def complete_plan(
    plan_id: int,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    plan = _plan(db, plan_id)
    if plan.status != "active":
        raise HTTPException(409, "الخطة غير نشطة")
    if not plan.procedures:
        raise HTTPException(409, "لا يمكن إكمال خطة دون إجراءات")
    unfinished = [row.id for row in plan.procedures if row.status != "completed"]
    if unfinished:
        raise HTTPException(409, f"لا يمكن إكمال الخطة قبل إنهاء الإجراءات: {unfinished}")
    plan.status = "completed"
    plan.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return _plan_out(plan)


@router.post("/plans/{plan_id}/cancel", response_model=DentalTreatmentPlanOut)
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
    for row in plan.procedures:
        if row.status != "completed":
            row.status = "cancelled"
    db.commit()
    db.refresh(plan)
    return _plan_out(plan)


