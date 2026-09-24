"""مخططات المحاور التشغيلية الجديدة: تمريض، عمليات، وحدات، دعم، جودة وموارد."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ServiceRequestCreate(StrictModel):
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
