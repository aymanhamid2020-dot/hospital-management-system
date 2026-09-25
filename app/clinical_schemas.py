"""مخططات المحاور التشغيلية الجديدة: تمريض، عمليات، وحدات، دعم، جودة وموارد."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ServiceRequestCreate(StrictModel):
    service_type: Literal["care_sets", "dental", "physiotherapy", "emergency", "home_health", "wellness", "nutrition", "housekeeping"]
    service_type: Literal["care_sets", "dental", "physiotherapy", "emergency", "home_health", "wellness", "nutrition"]
    patient_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=160)
    details: Optional[str] = Field(None, max_length=1000)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    scheduled_at: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=100)


class ServiceRequestUpdate(StrictModel):
    title: Optional[str] = Field(None, min_length=2, max_length=160)
    details: Optional[str] = Field(None, max_length=1000)
    priority: Optional[Literal["low", "normal", "high", "critical"]] = None
    status: Optional[Literal["pending", "in_progress", "completed", "cancelled"]] = None
    scheduled_at: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=100)
    result: Optional[str] = Field(None, max_length=1000)


class NursingTaskCreate(StrictModel):
    patient_id: int = Field(gt=0)
    department_id: Optional[int] = Field(default=None, gt=0)
    title: str = Field(min_length=2, max_length=160)
    instructions: Optional[str] = Field(None, max_length=1000)
    shift: Literal["day", "evening", "night"] = "day"
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    assigned_to: Optional[str] = Field(None, max_length=100)
    due_at: Optional[datetime] = None


class SurgeryCreate(StrictModel):
    patient_id: int = Field(gt=0)
    surgeon_id: Optional[int] = Field(default=None, gt=0)
    procedure_name: str = Field(min_length=2, max_length=160)
    theater: Optional[str] = Field(None, max_length=80)
    priority: Literal["emergency", "urgent", "elective"] = "elective"
    scheduled_at: Optional[datetime] = None
    pre_op_notes: Optional[str] = Field(None, max_length=1000)


class AdmissionCreate(StrictModel):
    patient_id: int = Field(gt=0)
    bed_id: Optional[int] = Field(default=None, gt=0)
    department_id: Optional[int] = Field(default=None, gt=0)
    admission_date: datetime
    diagnosis: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def require_bed(self):
        if self.bed_id is None:
            raise ValueError("يجب تحديد سرير والتنويم")
        return self


class BloodUnitCreate(StrictModel):
    unit_number: str = Field(min_length=2, max_length=60)
    donor_name: str = Field(min_length=2, max_length=120)
    blood_group: str = Field(min_length=2, max_length=10)
    component: Literal["whole_blood", "platelets", "plasma", "red_cells"] = "whole_blood"
    quantity_ml: int = Field(default=450, ge=1, le=10000)
    expiry_date: datetime
    notes: Optional[str] = Field(None, max_length=500)


class MaintenanceCreate(StrictModel):
    asset_name: str = Field(min_length=2, max_length=160)
    serial_number: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=100)
    issue: str = Field(min_length=2, max_length=1000)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    scheduled_at: Optional[datetime] = None
    cost: float = Field(default=0, ge=0)


class SterilizationCreate(StrictModel):
    machine_name: str = Field(min_length=2, max_length=120)
    cycle_type: Literal["autoclave", "chemical", "low_temperature"] = "autoclave"
    load_description: str = Field(min_length=2, max_length=500)
    started_at: datetime
    operator_name: Optional[str] = Field(None, max_length=100)


class SafetyEventCreate(StrictModel):
    category: Literal["incident", "infection", "medication", "fall", "equipment", "other"] = "incident"
    severity: Literal["low", "medium", "high", "critical"] = "low"
    title: str = Field(min_length=2, max_length=160)
    description: Optional[str] = Field(None, max_length=2000)
    location: Optional[str] = Field(None, max_length=120)
    patient_id: Optional[int] = Field(default=None, gt=0)
    occurred_at: Optional[datetime] = None


class BudgetCreate(StrictModel):
    fiscal_year: int = Field(ge=2000, le=2200)
    department: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=120)
    allocated_amount: float = Field(ge=0)
    spent_amount: float = Field(default=0, ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class FixedAssetCreate(StrictModel):
    asset_code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=120)
    department: Optional[str] = Field(None, max_length=120)
    purchase_date: Optional[datetime] = None
    purchase_cost: float = Field(ge=0)
    salvage_value: float = Field(default=0, ge=0)
    useful_life_years: int = Field(default=5, ge=1, le=100)
    location: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=500)


class StatusUpdate(StrictModel):
    status: str = Field(min_length=2, max_length=30)


class OperationalInDB(StrictModel):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PatientPortalCreate(StrictModel):
    patient_id: int = Field(gt=0)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class PatientPortalLogin(StrictModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class PatientAppointmentCreate(StrictModel):
    doctor_id: int = Field(gt=0)
    appointment_date: datetime
    reason: str = Field(min_length=2, max_length=300)


# ===== خطط الرعاية =====
class CarePlanItemInCreate(StrictModel):
    category: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=200)
    instructions: Optional[str] = Field(None, max_length=1000)
    scheduled_at: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=100)
    verification_method: Optional[str] = Field(None, max_length=100)

class CarePlanCreate(StrictModel):
    patient_id: int = Field(gt=0)
    service_request_id: Optional[int] = Field(None, gt=0)
    admission_id: Optional[int] = Field(None, gt=0)
    responsible_doctor_id: Optional[int] = Field(None, gt=0)
    title: str = Field(min_length=2, max_length=200)
    goals: str = Field(min_length=2, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)
    coordinator: Optional[str] = Field(None, max_length=120)
    started_at: datetime
    items: list[CarePlanItemInCreate] = Field(default_factory=list)

class CarePlanItemCreate(StrictModel):
    category: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=200)
    instructions: Optional[str] = Field(None, max_length=1000)
    scheduled_at: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=100)
    verification_method: Optional[str] = Field(None, max_length=100)

class CarePlanExecutionCreate(StrictModel):
    executed_at: datetime
    outcome: Literal["completed", "failed"] = "completed"
    notes: Optional[str] = Field(None, max_length=1000)

class CarePlanItemOut(StrictModel):
    id: int
    plan_id: int
    category: str
    title: str
    instructions: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    verification_method: Optional[str] = None
    status: str
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CarePlanOut(StrictModel):
    id: int
    patient_id: int
    service_request_id: Optional[int] = None
    admission_id: Optional[int] = None
    responsible_doctor_id: Optional[int] = None
    title: str
    goals: str
    notes: Optional[str] = None
    coordinator: Optional[str] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_by: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    items: list[CarePlanItemOut] = Field(default_factory=list)
    completion_percentage: float = 0.0
    model_config = ConfigDict(from_attributes=True)

# ===== طب الأسنان =====
class DentalChartUpsert(StrictModel):
    allergies: Optional[str] = Field(None, max_length=500)
    medical_conditions: Optional[str] = Field(None, max_length=500)
    last_exam_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=1000)

class DentalChartOut(StrictModel):
    id: int
    patient_id: int
    allergies: Optional[str] = None
    medical_conditions: Optional[str] = None
    last_exam_at: Optional[datetime] = None
    notes: Optional[str] = None
    updated_by: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class DentalTreatmentPlanCreate(StrictModel):
    patient_id: int = Field(gt=0)
    dentist_id: Optional[int] = Field(None, gt=0)
    service_request_id: Optional[int] = Field(None, gt=0)
    title: str = Field(min_length=2, max_length=200)
    chief_complaint: str = Field(min_length=2, max_length=1000)
    diagnosis: Optional[str] = Field(None, max_length=1000)
    notes: Optional[str] = Field(None, max_length=1000)
    started_at: datetime

class DentalProcedureCreate(StrictModel):
    dentist_id: Optional[int] = Field(None, gt=0)
    tooth_number: Optional[int] = Field(None, ge=1, le=52)
    surfaces: Optional[str] = Field(None, max_length=50)
    procedure_type: str = Field(min_length=2, max_length=100)
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=1000)
    material: Optional[str] = Field(None, max_length=100)
    cost: float = Field(default=0.0, ge=0)

class DentalProcedureExecute(StrictModel):
    performed_at: datetime
    outcome: Literal["completed", "failed"] = "completed"
    notes: Optional[str] = Field(None, max_length=1000)
    material: Optional[str] = Field(None, max_length=100)
    cost: float = Field(default=0.0, ge=0)
    follow_up_at: Optional[datetime] = None

class DentalProcedureOut(StrictModel):
    id: int
    plan_id: int
    dentist_id: Optional[int] = None
    tooth_number: Optional[int] = None
    surfaces: Optional[str] = None
    procedure_type: str
    status: str
    scheduled_at: Optional[datetime] = None
    performed_at: Optional[datetime] = None
    notes: Optional[str] = None
    material: Optional[str] = None
    cost: float = 0.0
    follow_up_at: Optional[datetime] = None
    created_by: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class DentalTreatmentPlanOut(StrictModel):
    id: int
    patient_id: int
    dentist_id: Optional[int] = None
    service_request_id: Optional[int] = None
    title: str
    chief_complaint: str
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_by: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    procedures: list[DentalProcedureOut] = Field(default_factory=list)
    completion_percentage: float = 0.0
    total_cost: float = 0.0
    model_config = ConfigDict(from_attributes=True)


# ===== الوحدات التشغيلية المكملة (Service Units) =====

# 1. العلاج الطبيعي
class PhysiotherapyCaseCreate(StrictModel):
    patient_id: int = Field(gt=0)
    therapist_id: Optional[int] = Field(None, gt=0)
    title: str = Field(min_length=2, max_length=160)
    assessment: Optional[str] = Field(None, max_length=2000)
    plan: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)

class PhysiotherapyCaseUpdate(StrictModel):
    therapist_id: Optional[int] = Field(None, gt=0)
    title: Optional[str] = Field(None, min_length=2, max_length=160)
    assessment: Optional[str] = Field(None, max_length=2000)
    plan: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)

class PhysiotherapyCaseOut(StrictModel):
    id: int
    patient_id: int
    therapist_id: Optional[int] = None
    title: str
    assessment: Optional[str] = None
    plan: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# 2. التغذية السريرية
class NutritionCaseCreate(StrictModel):
    patient_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=160)
    dietary_plan: Optional[str] = Field(None, max_length=2000)
    meal_plan: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)

class NutritionCaseUpdate(StrictModel):
    title: Optional[str] = Field(None, min_length=2, max_length=160)
    dietary_plan: Optional[str] = Field(None, max_length=2000)
    meal_plan: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)

class NutritionCaseOut(StrictModel):
    id: int
    patient_id: int
    title: str
    dietary_plan: Optional[str] = None
    meal_plan: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    suspended_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# 3. الطوارئ
class EmergencyCaseCreate(StrictModel):
    patient_id: int = Field(gt=0)
    complaint: str = Field(min_length=2, max_length=1000)
    triage_level: Literal["resuscitation", "emergent", "urgent", "less_urgent", "non_urgent", "standard"] = "standard"
    arrival_at: datetime
    disposition: Optional[str] = Field(None, max_length=160)
    notes: Optional[str] = Field(None, max_length=2000)

class EmergencyCaseUpdate(StrictModel):
    complaint: Optional[str] = Field(None, min_length=2, max_length=1000)
    triage_level: Optional[Literal["resuscitation", "emergent", "urgent", "less_urgent", "non_urgent", "standard"]] = None
    arrival_at: Optional[datetime] = None
    disposition: Optional[str] = Field(None, max_length=160)
    notes: Optional[str] = Field(None, max_length=2000)

class EmergencyCaseOut(StrictModel):
    id: int
    patient_id: int
    complaint: str
    triage_level: str
    arrival_at: datetime
    disposition: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: str
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)



# 4. الرعاية الصحية المنزلية
class HomeHealthCaseCreate(StrictModel):
    patient_id: int = Field(gt=0)
    coordinator: Optional[str] = Field(None, max_length=120)
    care_plan: Optional[str] = Field(None, max_length=2000)
    next_visit_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=2000)

class HomeHealthCaseUpdate(StrictModel):
    coordinator: Optional[str] = Field(None, max_length=120)
    care_plan: Optional[str] = Field(None, max_length=2000)
    next_visit_at: Optional[datetime] = None
    visits_completed: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)

class HomeHealthCaseOut(StrictModel):
    id: int
    patient_id: int
    coordinator: Optional[str] = None
    care_plan: Optional[str] = None
    next_visit_at: Optional[datetime] = None
    visits_completed: int = 0
    notes: Optional[str] = None
    status: str
    created_by: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# 5. برامج العافية ونمط الحياة
class WellnessProgramCreate(StrictModel):
    patient_id: int = Field(gt=0)
    program_name: str = Field(min_length=2, max_length=160)
    goal: str = Field(min_length=2, max_length=1000)
    baseline_metrics: Optional[str] = Field(None, max_length=2000)
    progress_notes: Optional[str] = Field(None, max_length=2000)
    next_review_at: Optional[datetime] = None

class WellnessProgramUpdate(StrictModel):
    program_name: Optional[str] = Field(None, min_length=2, max_length=160)
    goal: Optional[str] = Field(None, min_length=2, max_length=1000)
    baseline_metrics: Optional[str] = Field(None, max_length=2000)
    progress_notes: Optional[str] = Field(None, max_length=2000)
    next_review_at: Optional[datetime] = None

class WellnessProgramOut(StrictModel):
    id: int
    patient_id: int
    program_name: str
    goal: str
    baseline_metrics: Optional[str] = None
    progress_notes: Optional[str] = None
    next_review_at: Optional[datetime] = None
    status: str
    created_by: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# 6. النظافة والتدبير المنزلي
class HousekeepingTaskCreate(StrictModel):
    room_number: str = Field(min_length=1, max_length=50)
    task_type: str = Field(default="cleaning", min_length=2, max_length=50)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    assigned_to: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)

class HousekeepingTaskUpdate(StrictModel):
    room_number: Optional[str] = Field(None, min_length=1, max_length=50)
    task_type: Optional[str] = Field(None, min_length=2, max_length=50)
    priority: Optional[Literal["low", "normal", "high", "critical"]] = None
    assigned_to: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)

class HousekeepingTaskOut(StrictModel):
    id: int
    room_number: str
    task_type: str
    priority: str
    assigned_to: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)