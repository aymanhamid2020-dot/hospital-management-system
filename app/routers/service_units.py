"""مسارات الوحدات التشغيلية والخدمات المكملة:
1. العلاج الطبيعي (Physiotherapy)
2. التغذية السريرية (Nutrition)
3. الطوارئ (Emergency)
4. الرعاية الصحية المنزلية (Home Health)
5. برامج العافية (Wellness)
6. النظافة الفندقية والتدبير المنزلي (Housekeeping)
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.clinical_schemas import (
    EmergencyCaseCreate, EmergencyCaseOut, EmergencyCaseUpdate,
    HomeHealthCaseCreate, HomeHealthCaseOut, HomeHealthCaseUpdate,
    HousekeepingTaskCreate, HousekeepingTaskOut, HousekeepingTaskUpdate,
    NutritionCaseCreate, NutritionCaseOut, NutritionCaseUpdate,
    PhysiotherapyCaseCreate, PhysiotherapyCaseOut, PhysiotherapyCaseUpdate,
    StatusUpdate, WellnessProgramCreate, WellnessProgramOut, WellnessProgramUpdate,
)
from app.database import get_db
from app.models import (
    Doctor, EmergencyCase, HomeHealthCase, HousekeepingTask, NutritionCase,
    Patient, PhysiotherapyCase, User, WellnessProgram,
)

router = APIRouter(prefix="/service-units", tags=["الوحدات التشغيلية المكملة"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_patient(db: Session, patient_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="المريض غير موجود")
    return patient


def _get_doctor(db: Session, doctor_id: Optional[int]) -> Optional[Doctor]:
    if doctor_id is None:
        return None
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="الطبيب غير موجود")
    return doctor


# =====================================================================
# 1. العلاج الطبيعي (Physiotherapy)
# =====================================================================

@router.get("/physiotherapy", response_model=List[PhysiotherapyCaseOut])
def list_physiotherapy_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    therapist_id: Optional[int] = Query(None, gt=0),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PhysiotherapyCase)
    if patient_id:
        query = query.filter(PhysiotherapyCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(PhysiotherapyCase.status == status_filter)
    if therapist_id:
        query = query.filter(PhysiotherapyCase.therapist_id == therapist_id)
    return query.order_by(PhysiotherapyCase.id.desc()).limit(limit).all()


@router.post("/physiotherapy", response_model=PhysiotherapyCaseOut, status_code=status.HTTP_201_CREATED)
def create_physiotherapy_case(
    payload: PhysiotherapyCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    _get_doctor(db, payload.therapist_id)

    item = PhysiotherapyCase(
        **payload.model_dump(),
        status="assessed",
        created_by=current_user.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/physiotherapy/{case_id}", response_model=PhysiotherapyCaseOut)
def get_physiotherapy_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(PhysiotherapyCase).filter(PhysiotherapyCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة العلاج الطبيعي غير موجودة")
    return item


@router.put("/physiotherapy/{case_id}", response_model=PhysiotherapyCaseOut)
def update_physiotherapy_case(
    case_id: int,
    payload: PhysiotherapyCaseUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(PhysiotherapyCase).filter(PhysiotherapyCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة العلاج الطبيعي غير موجودة")
    if item.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail="لا يمكن تعديل حالة مكتملة أو ملغاة")

    update_data = payload.model_dump(exclude_unset=True)
    if "therapist_id" in update_data:
        _get_doctor(db, update_data["therapist_id"])

    for key, value in update_data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/physiotherapy/{case_id}/status", response_model=PhysiotherapyCaseOut)
def change_physiotherapy_status(
    case_id: int,
    payload: StatusUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(PhysiotherapyCase).filter(PhysiotherapyCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة العلاج الطبيعي غير موجودة")

    allowed = {"assessed", "in_treatment", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(status_code=422, detail=f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")

    if item.status in ("completed", "cancelled") and payload.status != item.status:
        raise HTTPException(status_code=409, detail="لا يمكن تغيير حالة منتهية")

    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "cancelled" and item.cancelled_at is None:
        item.cancelled_at = _utc_now()

    db.commit()
    db.refresh(item)
    return item



# =====================================================================
# 2. التغذية السريرية (Nutrition)
# =====================================================================

@router.get("/nutrition", response_model=List[NutritionCaseOut])
def list_nutrition_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(NutritionCase)
    if patient_id:
        query = query.filter(NutritionCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(NutritionCase.status == status_filter)
    return query.order_by(NutritionCase.id.desc()).limit(limit).all()


@router.post("/nutrition", response_model=NutritionCaseOut, status_code=status.HTTP_201_CREATED)
def create_nutrition_case(
    payload: NutritionCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = NutritionCase(
        **payload.model_dump(),
        status="assessed",
        created_by=current_user.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/nutrition/{case_id}", response_model=NutritionCaseOut)
def get_nutrition_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(NutritionCase).filter(NutritionCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة التغذية غير موجودة")
    return item


@router.put("/nutrition/{case_id}", response_model=NutritionCaseOut)
def update_nutrition_case(
    case_id: int,
    payload: NutritionCaseUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(NutritionCase).filter(NutritionCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة التغذية غير موجودة")
    if item.status in ("completed", "suspended"):
        raise HTTPException(status_code=409, detail="لا يمكن تعديل حالة مغلقة أو معلقة")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/nutrition/{case_id}/status", response_model=NutritionCaseOut)
def change_nutrition_status(
    case_id: int,
    payload: StatusUpdate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(NutritionCase).filter(NutritionCase.id == case_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="حالة التغذية غير موجودة")

    allowed = {"assessed", "active", "completed", "suspended"}
    if payload.status not in allowed:
        raise HTTPException(status_code=422, detail=f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")

    if item.status in ("completed", "suspended") and payload.status != item.status:
        raise HTTPException(status_code=409, detail="لا يمكن تغيير حالة منتهية أو معلقة")

    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "suspended" and item.suspended_at is None:
        item.suspended_at = _utc_now()

    db.commit()
    db.refresh(item)
    return item



# =====================================================================
# 3. الطوارئ (Emergency)
# =====================================================================

@router.get("/emergency", response_model=List[EmergencyCaseOut])
def list_emergency_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    triage_level: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(EmergencyCase)
    if patient_id is not None:
        query = query.filter(EmergencyCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(EmergencyCase.status == status_filter)
    if triage_level:
        query = query.filter(EmergencyCase.triage_level == triage_level)
    return query.order_by(EmergencyCase.arrival_at.desc()).limit(limit).all()


@router.post("/emergency", response_model=EmergencyCaseOut, status_code=status.HTTP_201_CREATED)
def create_emergency_case(
    payload: EmergencyCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = EmergencyCase(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/emergency/{case_id}", response_model=EmergencyCaseOut)
def get_emergency_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    return item


@router.put("/emergency/{case_id}", response_model=EmergencyCaseOut)
def update_emergency_case(
    case_id: int,
    payload: EmergencyCaseUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    if item.status in {"discharged", "closed"}:
        raise HTTPException(409, "لا يمكن تعديل حالة طوارئ منتهية")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/emergency/{case_id}/status", response_model=EmergencyCaseOut)
def change_emergency_status(
    case_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(EmergencyCase).filter(EmergencyCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الطوارئ غير موجودة")
    allowed = {"arrived", "triaged", "under_treatment", "discharged", "closed"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"discharged", "closed"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة طوارئ منتهية")
    item.status = payload.status
    if payload.status in {"discharged", "closed"} and item.closed_at is None:
        item.closed_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item




# =====================================================================
# 4. الرعاية الصحية المنزلية (Home Health)
# =====================================================================

@router.get("/home-health", response_model=List[HomeHealthCaseOut])
def list_home_health_cases(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(HomeHealthCase)
    if patient_id is not None:
        query = query.filter(HomeHealthCase.patient_id == patient_id)
    if status_filter:
        query = query.filter(HomeHealthCase.status == status_filter)
    return query.order_by(HomeHealthCase.id.desc()).limit(limit).all()


@router.post("/home-health", response_model=HomeHealthCaseOut, status_code=status.HTTP_201_CREATED)
def create_home_health_case(
    payload: HomeHealthCaseCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = HomeHealthCase(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/home-health/{case_id}", response_model=HomeHealthCaseOut)
def get_home_health_case(
    case_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(HomeHealthCase).filter(HomeHealthCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الرعاية المنزلية غير موجودة")
    return item


@router.put("/home-health/{case_id}", response_model=HomeHealthCaseOut)
def update_home_health_case(
    case_id: int,
    payload: HomeHealthCaseUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(HomeHealthCase).filter(HomeHealthCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الرعاية المنزلية غير موجودة")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تعديل حالة رعاية منزلية منتهية")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/home-health/{case_id}/status", response_model=HomeHealthCaseOut)
def change_home_health_status(
    case_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(HomeHealthCase).filter(HomeHealthCase.id == case_id).first()
    if not item:
        raise HTTPException(404, "حالة الرعاية المنزلية غير موجودة")
    allowed = {"referred", "scheduled", "active", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"completed", "cancelled"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة رعاية منزلية منتهية")
    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "cancelled" and item.cancelled_at is None:
        item.cancelled_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item


# =====================================================================
# 5. برامج العافية ونمط الحياة (Wellness)
# =====================================================================

@router.get("/wellness", response_model=List[WellnessProgramOut])
def list_wellness_programs(
    patient_id: Optional[int] = Query(None, gt=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(WellnessProgram)
    if patient_id is not None:
        query = query.filter(WellnessProgram.patient_id == patient_id)
    if status_filter:
        query = query.filter(WellnessProgram.status == status_filter)
    return query.order_by(WellnessProgram.id.desc()).limit(limit).all()


@router.post("/wellness", response_model=WellnessProgramOut, status_code=status.HTTP_201_CREATED)
def create_wellness_program(
    payload: WellnessProgramCreate,
    current_user: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    _get_patient(db, payload.patient_id)
    item = WellnessProgram(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/wellness/{program_id}", response_model=WellnessProgramOut)
def get_wellness_program(
    program_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(WellnessProgram).filter(WellnessProgram.id == program_id).first()
    if not item:
        raise HTTPException(404, "برنامج العافية غير موجود")
    return item


@router.put("/wellness/{program_id}", response_model=WellnessProgramOut)
def update_wellness_program(
    program_id: int,
    payload: WellnessProgramUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(WellnessProgram).filter(WellnessProgram.id == program_id).first()
    if not item:
        raise HTTPException(404, "برنامج العافية غير موجود")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تعديل برنامج عافية منتهٍ")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/wellness/{program_id}/status", response_model=WellnessProgramOut)
def change_wellness_status(
    program_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor")),
    db: Session = Depends(get_db),
):
    item = db.query(WellnessProgram).filter(WellnessProgram.id == program_id).first()
    if not item:
        raise HTTPException(404, "برنامج العافية غير موجود")
    allowed = {"planned", "active", "paused", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"completed", "cancelled"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة برنامج عافية منتهٍ")
    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item



# =====================================================================
# 6. النظافة والتدبير المنزلي (Housekeeping)
# =====================================================================

@router.get("/housekeeping", response_model=List[HousekeepingTaskOut])
def list_housekeeping_tasks(
    room_number: Optional[str] = Query(None, min_length=1, max_length=50),
    status_filter: Optional[str] = Query(None, alias="status"),
    assigned_to: Optional[str] = Query(None, max_length=100),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(HousekeepingTask)
    if room_number:
        query = query.filter(HousekeepingTask.room_number == room_number)
    if status_filter:
        query = query.filter(HousekeepingTask.status == status_filter)
    if assigned_to:
        query = query.filter(HousekeepingTask.assigned_to == assigned_to)
    return query.order_by(HousekeepingTask.id.desc()).limit(limit).all()


@router.post("/housekeeping", response_model=HousekeepingTaskOut, status_code=status.HTTP_201_CREATED)
def create_housekeeping_task(
    payload: HousekeepingTaskCreate,
    current_user: User = Depends(require_role("admin", "doctor", "موظف استقبال")),
    db: Session = Depends(get_db),
):
    item = HousekeepingTask(**payload.model_dump(), created_by=current_user.username)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/housekeeping/{task_id}", response_model=HousekeepingTaskOut)
def get_housekeeping_task(
    task_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(HousekeepingTask).filter(HousekeepingTask.id == task_id).first()
    if not item:
        raise HTTPException(404, "مهمة النظافة غير موجودة")
    return item


@router.put("/housekeeping/{task_id}", response_model=HousekeepingTaskOut)
def update_housekeeping_task(
    task_id: int,
    payload: HousekeepingTaskUpdate,
    _: User = Depends(require_role("admin", "doctor", "موظف استقبال")),
    db: Session = Depends(get_db),
):
    item = db.query(HousekeepingTask).filter(HousekeepingTask.id == task_id).first()
    if not item:
        raise HTTPException(404, "مهمة النظافة غير موجودة")
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "لا يمكن تعديل مهمة نظافة منتهية")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/housekeeping/{task_id}/status", response_model=HousekeepingTaskOut)
def change_housekeeping_status(
    task_id: int,
    payload: StatusUpdate,
    _: User = Depends(require_role("admin", "doctor", "موظف استقبال")),
    db: Session = Depends(get_db),
):
    item = db.query(HousekeepingTask).filter(HousekeepingTask.id == task_id).first()
    if not item:
        raise HTTPException(404, "مهمة النظافة غير موجودة")
    allowed = {"pending", "in_progress", "completed", "cancelled"}
    if payload.status not in allowed:
        raise HTTPException(422, f"حالة غير مقبولة؛ المسموح: {sorted(allowed)}")
    if item.status in {"completed", "cancelled"} and payload.status != item.status:
        raise HTTPException(409, "لا يمكن تغيير حالة مهمة نظافة منتهية")
    item.status = payload.status
    if payload.status == "completed" and item.completed_at is None:
        item.completed_at = _utc_now()
    elif payload.status == "cancelled" and item.cancelled_at is None:
        item.cancelled_at = _utc_now()
    db.commit()
    db.refresh(item)
    return item

