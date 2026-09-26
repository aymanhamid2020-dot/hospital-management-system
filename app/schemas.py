from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime, time

from app.models import (
    Gender, UserRole, AppointmentStatus, InvoiceStatus, BedStatus,
    TestType, LabStatus, PayrollStatus, ClaimStatus,
)


# ===== Helpers =====
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ===== المستخدمون / المصادقة =====
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, description="اسم المستخدم")
    email: EmailStr = Field(..., description="البريد الإلكتروني")
    full_name: str = Field(..., description="الاسم الكامل")
    role: UserRole = Field(UserRole.RECEPTIONIST, description="الدور/الصلاحية")


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, description="كلمة المرور")


class UserLogin(BaseModel):
    username: str
    password: str


class UserInDB(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserRoleChange(BaseModel):
    role: UserRole = Field(..., description="الدور الجديد للمستخدم")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInDB


# ===== الأقسام =====
class DepartmentBase(BaseModel):
    name: str = Field(..., description="اسم القسم")
    description: Optional[str] = Field(None, description="الوصف")
    floor: Optional[str] = Field(None, description="الدور")


class DepartmentCreate(DepartmentBase):
    """حقول مركز الأقسام تُقبل عند الإنشاء: الأب والنوع ورأس القسم والتكلفة."""
    parent_id: Optional[int] = Field(None, gt=0, description="القسم الأب (وحدة فرعية)")
    dept_type: str = Field("clinical", description="clinical|diagnostic|administrative|supportive")
    head_doctor_id: Optional[int] = Field(None, gt=0)
    is_active: bool = True
    monthly_operating_cost: float = Field(0, ge=0)


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    floor: Optional[str] = None
    # حقول مركز الأقسام (تُعدَّل أيضًا عبر /department-hub/{id}/structure)
    parent_id: Optional[int] = Field(None, gt=0)
    dept_type: Optional[str] = None
    head_doctor_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None
    monthly_operating_cost: Optional[float] = Field(None, ge=0)


class BedInDB(ORMModel):
    id: int
    bed_number: str
    status: BedStatus
    patient_id: Optional[int] = None
    room_id: Optional[int] = None


class DepartmentInDB(ORMModel):
    id: int
    name: str
    description: Optional[str] = None
    floor: Optional[str] = None
    created_at: datetime
    beds: List[BedInDB] = []
    # مركز الأقسام: الهيكل والكادر
    parent_id: Optional[int] = None
    dept_type: str = "clinical"
    head_doctor_id: Optional[int] = None
    is_active: bool = True
    monthly_operating_cost: float = 0.0


# ===== مركز الأقسام: الغرف والخدمات والجداول والكادر =====
class DepartmentRoomCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    room_number: Optional[str] = None
    category: str = Field("shared", description="royal|private|shared|icu|er|operating")
    capacity: int = Field(1, ge=1, le=200)


class DepartmentRoomOut(ORMModel):
    id: int
    department_id: int
    name: str
    room_number: Optional[str] = None
    category: str
    capacity: int
    is_active: bool
    beds_count: int = 0
    beds_occupied: int = 0
    upcoming_bookings: int = 0

    model_config = ConfigDict(from_attributes=True)


class DepartmentRoomBookingIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    purpose: Optional[str] = Field(None, max_length=200)
    patient_id: Optional[int] = Field(None, gt=0)


class DepartmentRoomBookingOut(ORMModel):
    id: int
    room_id: int
    room_name: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    purpose: Optional[str] = None
    patient_id: Optional[int] = None
    created_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DepartmentServiceIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    code: Optional[str] = Field(None, max_length=40)
    price: float = Field(0, ge=0)
    doctor_share_pct: float = Field(0, ge=0, le=100)
    insurance_pct: float = Field(0, ge=0, le=100)
    procedure_note: Optional[str] = None


class DepartmentServiceOut(ORMModel):
    id: int
    department_id: int
    code: Optional[str] = None
    name: str
    price: float
    doctor_share_pct: float
    insurance_pct: float
    procedure_note: Optional[str] = None
    is_active: bool
    doctor_amount: float = 0.0
    insurance_amount: float = 0.0
    patient_amount: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class DepartmentScheduleIn(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=الأحد … 6=السبت")
    session: str = Field("morning", description="morning|evening")
    open_time: str = Field("08:00", max_length=5)
    close_time: str = Field("14:00", max_length=5)
    room_name: Optional[str] = Field(None, max_length=80)


class DepartmentScheduleOut(ORMModel):
    id: int
    department_id: int
    day_of_week: int
    session: str
    open_time: str
    close_time: str
    room_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DepartmentStaffIn(BaseModel):
    staff_id: int = Field(..., gt=0)
    role_in_dept: str = Field("ممرض", max_length=60)
    is_head: bool = False


class DepartmentStaffOut(ORMModel):
    id: int
    department_id: int
    staff_id: int
    staff_name: Optional[str] = None
    position: Optional[str] = None
    role_in_dept: str
    is_head: bool

    model_config = ConfigDict(from_attributes=True)


class DepartmentHodIn(BaseModel):
    """تعيين رئيس القسم (طبيب) — أو إلغاؤه بـ null."""
    head_doctor_id: Optional[int] = Field(None, gt=0)


class DepartmentUpdateExtra(BaseModel):
    """حقول مركز الأقسام المضافة على حقول القسم الأساسية."""
    parent_id: Optional[int] = Field(None, gt=0)
    dept_type: Optional[str] = None
    head_doctor_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None
    monthly_operating_cost: Optional[float] = Field(None, ge=0)



# ===== الأسرّة =====
class BedBase(BaseModel):
    bed_number: str = Field(..., description="رقم السرير")
    department_id: int = Field(..., description="معرّف القسم")
    status: BedStatus = Field(BedStatus.AVAILABLE, description="حالة السرير")
    patient_id: Optional[int] = Field(None, description="المريض المشغّل للسرير")


class BedCreate(BedBase):
    pass


class BedUpdate(BaseModel):
    bed_number: Optional[str] = None
    status: Optional[BedStatus] = None
    patient_id: Optional[int] = None


class BedFullInDB(ORMModel):
    id: int
    bed_number: str
    department_id: int
    status: BedStatus
    patient_id: Optional[int] = None
    created_at: datetime


# ===== المرضى =====
class PatientBase(BaseModel):
    full_name: str = Field(..., description="اسم المريض الكامل")
    date_of_birth: datetime = Field(..., description="تاريخ الميلاد")
    gender: Gender = Field(..., description="النوع")
    phone: str = Field(..., description="رقم الهاتف")
    email: EmailStr = Field(..., description="البريد الإلكتروني")
    address: Optional[str] = Field(None, description="العنوان")
    blood_type: Optional[str] = Field(None, description="مجموعة الدم")
    national_id: Optional[str] = Field(None, description="الهوية الوطنية/الإقامة")
    insurer: Optional[str] = Field(None, description="شركة التأمين")
    policy_number: Optional[str] = Field(None, description="رقم وثيقة التأمين")
    # الملف الشخصي والإداري
    nationality: Optional[str] = Field(None, description="الجنسية")
    smoking_status: Optional[str] = Field(None, description="حالة التدخين")
    emergency_contact_name: Optional[str] = Field(None, description="اسم جهة الطوارئ")
    emergency_contact_phone: Optional[str] = Field(None, description="هاتف الطوارئ")
    emergency_contact_relation: Optional[str] = Field(None, description="صلة القرابة")
    insurance_grade: Optional[str] = Field(None, description="درجة التغطية")
    insurance_copay: Optional[float] = Field(None, ge=0, le=100, description="نسبة التحمل Co-pay %")
    # التاريخ الطبي والحساسية
    chronic_conditions: Optional[str] = Field(None, description="الأمراض المزمنة")
    past_surgeries: Optional[str] = Field(None, description="العمليات السابقة")
    family_history: Optional[str] = Field(None, description="التاريخ العائلي المرضي")
    allergies: Optional[str] = Field(None, description="الحساسية")
    medical_warnings: Optional[str] = Field(None, description="تحذيرات طبية مهمة")


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    blood_type: Optional[str] = None
    national_id: Optional[str] = None
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    nationality: Optional[str] = None
    smoking_status: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    insurance_grade: Optional[str] = None
    insurance_copay: Optional[float] = Field(None, ge=0, le=100)
    chronic_conditions: Optional[str] = None
    past_surgeries: Optional[str] = None
    family_history: Optional[str] = None
    allergies: Optional[str] = None
    medical_warnings: Optional[str] = None


class PatientProfileUpdate(PatientUpdate):
    """تحديث الملف الشخصي والتاريخ الطبي — نفس حقول PatientUpdate.

    (تُستخدم في PUT /patients/{id}/profile داخل شاشة الملف)
    """


class PatientInDB(PatientBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PatientListItem(PatientInDB):
    """صف في قائمة المرضى — PatientInDB + حقول محسوبة للقائمة.

    الحقول المحسوبة تُملأ في الراوتر باستعلامين مجمّعين (لا استعلام لكل مريض).
    """
    age: Optional[int] = Field(None, description="العمر بالسنوات")
    has_alerts: bool = Field(False, description="له حساسية أو تحذير طبي")
    last_visit: Optional[datetime] = Field(None, description="آخر زيارة")
    upcoming: Optional[datetime] = Field(None, description="أقرب موعد قادم")
    outstanding: float = Field(0.0, description="المتبقي المالي (فواتير + صرف)")

    model_config = ConfigDict(from_attributes=True)


# ===== العلامات الحيوية =====
class VitalSignBase(BaseModel):
    systolic: Optional[int] = Field(None, ge=0, le=300, description="الضغط الانقباضي")
    diastolic: Optional[int] = Field(None, ge=0, le=200, description="الضغط الانبساطي")
    temperature: Optional[float] = Field(None, ge=30, le=45, description="الحرارة °C")
    pulse: Optional[int] = Field(None, ge=0, le=250, description="النبض")
    weight: Optional[float] = Field(None, gt=0, le=500, description="الوزن كجم")
    height: Optional[float] = Field(None, gt=0, le=300, description="الطول سم")
    notes: Optional[str] = Field(None, max_length=500)
    recorded_by: Optional[str] = Field(None, max_length=120)


class VitalSignCreate(VitalSignBase):
    pass


class VitalSignUpdate(BaseModel):
    systolic: Optional[int] = Field(None, ge=0, le=300)
    diastolic: Optional[int] = Field(None, ge=0, le=200)
    temperature: Optional[float] = Field(None, ge=30, le=45)
    pulse: Optional[int] = Field(None, ge=0, le=250)
    weight: Optional[float] = Field(None, gt=0, le=500)
    height: Optional[float] = Field(None, gt=0, le=300)
    notes: Optional[str] = Field(None, max_length=500)
    recorded_by: Optional[str] = Field(None, max_length=120)


class VitalSignInDB(VitalSignBase):
    id: int
    patient_id: int
    bmi: Optional[float] = None
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===== مطالبات التأمين =====
class InsuranceClaimCreate(BaseModel):
    invoice_id: Optional[int] = None
    claim_number: str = Field(..., min_length=2, max_length=60, description="رقم المطالبة")
    insurer: Optional[str] = Field(None, max_length=120)
    amount: float = Field(..., ge=0, description="قيمة المطالبة")
    decision_notes: Optional[str] = Field(None, max_length=500)


class InsuranceClaimUpdate(BaseModel):
    """تحديث/قرار المطالبة — الحالة تتطلب approved_amount عند الموافقة."""
    claim_number: Optional[str] = Field(None, min_length=2, max_length=60)
    insurer: Optional[str] = Field(None, max_length=120)
    amount: Optional[float] = Field(None, ge=0)
    approved_amount: Optional[float] = Field(None, ge=0)
    status: Optional[ClaimStatus] = None
    decision_notes: Optional[str] = Field(None, max_length=500)
    rejection_reason: Optional[str] = Field(None, max_length=500)


class InsuranceClaimInDB(BaseModel):
    id: int
    patient_id: int
    invoice_id: Optional[int] = None
    claim_number: str
    insurer: Optional[str] = None
    amount: float
    approved_amount: Optional[float] = None
    status: ClaimStatus
    decision_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    submitted_at: datetime
    decided_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ===== الأطباء =====
class DoctorBase(BaseModel):
    full_name: str = Field(..., description="اسم الطبيب الكامل")
    specialty: str = Field(..., description="التخصص الطبي")
    license_number: str = Field(..., description="رقم التراخيص")
    phone: str = Field(..., description="رقم الهاتف")
    email: EmailStr = Field(..., description="البريد الإلكتروني")
    address: Optional[str] = Field(None, description="العنوان")
    is_available: bool = Field(True, description="هل الطبيب متاح")
    department_id: Optional[int] = Field(None, description="القسم التابع له")


class DoctorCreate(DoctorBase):
    sub_specialty: Optional[str] = Field(None, description="التخصص الدقيق")
    academic_rank: Optional[Literal["استشاري", "أخصائي", "طبيب مقيم"]] = Field(
        None, description="الدرجة العلمية")
    branch: Optional[str] = Field(None, description="الفرع/العيادة")
    user_id: Optional[int] = Field(None, description="حساب المستخدم المرتبط")
    consultation_minutes: int = Field(15, ge=5, le=180, description="مدة الزيرة (دقائق)")
    consultation_fee: float = Field(0, ge=0, description="سعر الكشفية")
    followup_fee: float = Field(0, ge=0, description="سعر الإعادة")


class DoctorUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    address: Optional[str] = None
    is_available: Optional[bool] = None
    department_id: Optional[int] = None
    sub_specialty: Optional[str] = None
    academic_rank: Optional[Literal["استشاري", "أخصائي", "طبيب مقيم"]] = None
    branch: Optional[str] = None
    user_id: Optional[int] = None
    consultation_minutes: Optional[int] = Field(None, ge=5, le=180)
    consultation_fee: Optional[float] = Field(None, ge=0)
    followup_fee: Optional[float] = Field(None, ge=0)


class DoctorAvailability(BaseModel):
    is_available: bool = Field(..., description="هل الطبيب متاح للحجز")


class DepartmentBrief(ORMModel):
    id: int
    name: str


class DoctorInDB(DoctorBase):
    id: int
    created_at: datetime
    updated_at: datetime
    department: Optional[DepartmentBrief] = None
    # الملف المهني وأوقات الكشف — تظهر في القائمة والتفاصيل
    sub_specialty: Optional[str] = None
    academic_rank: Optional[str] = None
    branch: Optional[str] = None
    user_id: Optional[int] = None
    signature_path: Optional[str] = None
    stamp_path: Optional[str] = None
    consultation_minutes: int = 15
    consultation_fee: float = 0
    followup_fee: float = 0

    model_config = ConfigDict(from_attributes=True)


class DoctorSummaryStats(BaseModel):
    """إحصاءات مرتبطة بطبيب واحد — تظهر في تفاصيل الطبيب."""
    appointments: int = Field(0, description="عدد مواعيده")
    records: int = Field(0, description="عدد سجلاته الطبية")
    patients: int = Field(0, description="عدد مرضاه الفريد")


class DoctorWithStats(DoctorInDB):
    stats: DoctorSummaryStats


class DepartmentCount(BaseModel):
    id: Optional[int] = None
    name: str
    count: int


class DoctorsStats(BaseModel):
    """إحصاءات قسم الأطباء للوحة والواجهة."""
    total: int
    available: int
    unavailable: int
    specialties: int
    without_department: int
    appointments: int
    departments: List[DepartmentCount]


class DoctorPerformance(BaseModel):
    """تقرير أداء الطبيب لشهر محدّد — للمراجعة الدورية."""
    month: str = Field(..., description="الشهر المُعتمد بصيغة YYYY-MM")
    doctor_id: int
    total: int
    completed: int
    cancelled: int
    pending: int
    confirmed: int
    completion_rate: float = Field(..., description="نسبة المواعيد المكتملة (0..1)")
    patients: int = Field(0, description="مرضى فريدون خلال الشهر")
    records: int = Field(0, description="سجلات طبية أُنشئت خلال الشهر")


class DoctorPerformanceRow(DoctorPerformance):
    """صف في التقرير المقارن الشهري — بيانات الطبيب مع أرقام شهره."""
    full_name: str
    specialty: str
    is_available: bool
    department: Optional[str] = None


class DoctorScheduleEntry(ORMModel):
    """نوبة واحدة في أسبوع الطبيب (0=السبت … 6=الجمعة)."""
    day_of_week: int = Field(..., ge=0, le=6,
                            description="يوم الأسبوع: 0=السبت … 6=الجمعة")
    start_time: time
    end_time: time
    location: Optional[str] = None
    is_active: bool = True


class DoctorScheduleUpdate(BaseModel):
    """استبدال جدول نوبات الأسبوع كاملًا."""
    entries: List[DoctorScheduleEntry]


# ===== شاشة ملف الطبيب (الأقسام الخمسة) =====
class UserBrief(ORMModel):
    """حساب المستخدم المرتبط بالطبيب — بلا كلمة مرور."""
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool


class DoctorPermissions(BaseModel):
    """صلاحيات الطبيب الدقيقة — تُحفظ JSON نصيًا في doctors.permissions."""
    own_patients_only: bool = Field(True, description="رؤية ملفات مرضاه فقط")
    view_emergency: bool = Field(False, description="الاطلاع على مراد الطوارئ")
    order_lab: bool = Field(True, description="طلب فحوصات")
    order_radiology: bool = Field(True, description="طلب أشعة")
    prescribe: bool = Field(True, description="صرف أدوية")
    view_invoices: bool = Field(False, description="الاطلاع على فواتير مرضاه")
    view_doctor_financials: bool = Field(False, description="رؤية كشف حسابه")


class DoctorProfileUpdate(BaseModel):
    """حفظ الملف المهني (PUT /doctors/{id}/profile) — المدير أو الطبيب نفسه."""
    sub_specialty: Optional[str] = Field(None, max_length=160)
    academic_rank: Optional[Literal["استشاري", "أخصائي", "طبيب مقيم"]] = None
    branch: Optional[str] = Field(None, max_length=160)
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[EmailStr] = None
    address: Optional[str] = Field(None, max_length=300)
    user_id: Optional[int] = None
    consultation_minutes: Optional[int] = Field(None, ge=5, le=180)
    consultation_fee: Optional[float] = Field(None, ge=0)
    followup_fee: Optional[float] = Field(None, ge=0)
    permissions: Optional[DoctorPermissions] = None


class DoctorShiftCreate(BaseModel):
    """مناوبة طوارئ/تنويم/أونكول."""
    shift_type: Literal["emergency", "inpatient", "oncall"] = Field(
        "emergency", description="نوع المناوبة")
    shift_date: datetime = Field(..., description="تاريخ المناوبة")
    start_time: time
    end_time: time
    location: Optional[str] = Field(None, max_length=160)
    notes: Optional[str] = Field(None, max_length=300)


class DoctorShiftInDB(ORMModel):
    id: int
    doctor_id: int
    shift_type: str
    shift_date: datetime
    start_time: time
    end_time: time
    location: Optional[str] = None
    notes: Optional[str] = None
    created_by: str
    created_at: datetime


class DoctorLeaveCreate(BaseModel):
    """إجازة الطبيب — end_date يجب أن يكون بعد start_date (أو مساويًا)."""
    start_date: datetime
    end_date: datetime
    reason: Optional[str] = Field(None, max_length=300)
    is_approved: bool = True


class DoctorLeaveInDB(ORMModel):
    id: int
    doctor_id: int
    start_date: datetime
    end_date: datetime
    reason: Optional[str] = None
    is_approved: bool
    created_by: str
    created_at: datetime


class DoctorBlockCreate(BaseModel):
    """يوم حظر حجز — بلا وقت = اليوم كامل."""
    block_date: datetime
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    reason: Optional[str] = Field(None, max_length=300)


class DoctorBlockInDB(ORMModel):
    id: int
    doctor_id: int
    block_date: datetime
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    reason: Optional[str] = None
    created_by: str
    created_at: datetime


class DoctorCommissionCreate(BaseModel):
    """نسبة أو قيمة ثابتة للطبيب عن كل نوع خدمة."""
    service_type: Literal["consultation", "procedure", "followup", "surgery"]
    billing_type: Literal["percent", "fixed"] = Field(
        "percent", description="نسبة مئوية أم قيمة ثابتة")
    rate: float = Field(..., ge=0, description="النسبة (0..100) أو المبلغ الثابت")
    is_active: bool = True


class DoctorCommissionInDB(ORMModel):
    id: int
    doctor_id: int
    service_type: str
    billing_type: str
    rate: float
    is_active: bool
    created_at: datetime


class DoctorPayoutCreate(BaseModel):
    """تحويل مستحق للطبيب — يجب ألا يتجاوز رصيد كشف حسابه."""
    amount: float = Field(..., gt=0, description="مبلغ التحويل")
    period: str = Field(..., description="الشهر المستحق YYYY-MM")
    method: Literal["cash", "bank", "transfer"] = "bank"
    reference: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = Field(None, max_length=300)
    paid_at: datetime


class DoctorPayoutInDB(ORMModel):
    id: int
    doctor_id: int
    amount: float
    period: str
    method: str
    reference: Optional[str] = None
    note: Optional[str] = None
    paid_at: datetime
    created_by: str
    created_at: datetime


class DoctorVisitStats(BaseModel):
    """إحصاءات الزيارات (جدد/إعادة/طوارئ) + الإلغاء والانتظار."""
    new_patients: int = Field(0, description="مرضى جدد (أول زيارة للطبيب)")
    returning_patients: int = Field(0, description="مرضى عائدون (سبقت لهم زيارة)")
    emergency_visits: int = Field(0, description="زيارات طوارئ (السبب يبدأ بكلمة طوارئ)")
    cancelled: int = Field(0, description="مواعيد ملغاة")
    cancel_rate: float = Field(0, description="نسبة الإلغاء (0..1)")
    avg_wait_minutes: float = Field(0, description="متوسط الانتظار بين الوصول والموعد (دقائق)")


class DoctorOrderStats(BaseModel):
    """أكثر الأدوية والفحوصات طلبًا من الطبيب خلال الشهر."""
    top_medications: List[dict] = Field(default_factory=list)
    top_lab_tests: List[dict] = Field(default_factory=list)
    prescriptions_count: int = 0
    lab_orders_count: int = 0


class DoctorLedger(BaseModel):
    """كشف حساب الطبيب: الإيراد، المستحق، المحوَّل، المتبقي."""
    period: str = Field("", description="الشهر YYYY-MM (يفرّغ عند غياب الصلاحية)")
    revenue: float = Field(0, description="إجمالي إيرادات الفترة من فواتير مرضاه")
    earned: float = Field(0, description="المستحق بعد تطبيق نسب العمولة")
    paid: float = Field(0, description="المحوَّل فعليًا")
    balance: float = Field(0, description="المتبقي = earned - paid")
    invoices_count: int = 0
    by_commission: List[dict] = Field(default_factory=list)


class DoctorChart(DoctorInDB):
    """ملف الطبيب الكامل — طلب واحد يغذّي التبويبات الخمسة.

    يرث بيانات التعريف من DoctorInDB ويضيف الجداول والإحصاءات، حتى لا
    تتكرر الحقول بين قائمتَي الإخراج. الحقول الموروثة (الدرجة العلمية،
    التوقيع، …) تُقرأ من نموذج `Doctor` مباشرة.
    """
    # الصلاحيات مخزَّنة نصيًا في doctors.permissions، والراوتر يمرّرها
    # منفصلة عبر from_doctor — فنمنع قراءة السمة الخام (نص) عند التحقق.
    permissions: DoctorPermissions = Field(default_factory=DoctorPermissions)
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    user: Optional[UserBrief] = None
    schedules: List[DoctorScheduleEntry] = Field(default_factory=list)
    shifts: List[DoctorShiftInDB] = Field(default_factory=list)
    leaves: List[DoctorLeaveInDB] = Field(default_factory=list)
    blocks: List[DoctorBlockInDB] = Field(default_factory=list)
    commissions: List[DoctorCommissionInDB] = Field(default_factory=list)
    payouts: List[DoctorPayoutInDB] = Field(default_factory=list)
    visits: DoctorVisitStats = Field(default_factory=DoctorVisitStats)
    orders: DoctorOrderStats = Field(default_factory=DoctorOrderStats)
    ledger: DoctorLedger = Field(default_factory=DoctorLedger)

    @classmethod
    def from_doctor(cls, doctor, permissions: "DoctorPermissions") -> "DoctorChart":
        """بناء الملف من نموذج الطبيب مع الصلاحيات المحلَّلة (لا نص JSON)."""
        data = cls.model_validate(
            {k: v for k, v in vars(doctor).items() if k != "permissions"})
        data.permissions = permissions
        return data


# ===== المواعيد =====
class AppointmentBase(BaseModel):
    patient_id: int = Field(..., description="معرّف المريض")
    doctor_id: int = Field(..., description="معرّف الطبيب")
    appointment_date: datetime = Field(..., description="تاريخ الموعد")
    reason: Optional[str] = Field(None, description="سبب الزيارة")
    status: AppointmentStatus = Field(AppointmentStatus.PENDING, description="حالة الموعد")


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    appointment_date: Optional[datetime] = None
    reason: Optional[str] = None
    status: Optional[AppointmentStatus] = None


class PatientBrief(ORMModel):
    id: int
    full_name: str


class DoctorBrief(ORMModel):
    id: int
    full_name: str
    specialty: str


class AppointmentInDB(AppointmentBase):
    id: int
    created_at: datetime
    checked_in_at: Optional[datetime] = None
    queue_number: Optional[int] = None
    patient: PatientBrief
    doctor: DoctorBrief

    model_config = ConfigDict(from_attributes=True)


# ===== الموظفون =====
class StaffDocumentInDB(ORMModel):
    id: int
    staff_id: int
    doc_type: str
    original_name: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class StaffBase(BaseModel):
    full_name: str = Field(..., description="اسم الموظف الكامل")
    position: str = Field(..., description="المنصب/الوظيفة")
    phone: str = Field(..., description="رقم الهاتف")
    email: EmailStr = Field(..., description="البريد الإلكتروني")
    hire_date: datetime = Field(..., description="تاريخ التعيين")
    salary: Optional[float] = Field(None, description="الراتب")
    # البيانات الموسعة لشؤون الموظفين (يتم دمجها مع ملف JSON الموجود)
    hr_profile: dict = Field(default_factory=dict, description="ملف الموارد البشرية الكامل")


class StaffCreate(StaffBase):
    pass


class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    position: Optional[str] = None
    salary: Optional[float] = None
    hr_profile: Optional[dict] = None


class StaffInDB(StaffBase):
    id: int
    created_at: datetime
    updated_at: datetime
    documents: List[StaffDocumentInDB] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class StaffBrief(ORMModel):
    id: int
    full_name: str
    position: str


# ===== الفواتير =====
class InvoiceBase(BaseModel):
    patient_id: int = Field(..., description="معرّف المريض")
    appointment_id: Optional[int] = Field(None, description="الموعد المرتبط (اختياري)")
    record_id: Optional[int] = Field(None, description="السجل الطبي المرتبط (اختياري)")
    amount: float = Field(..., gt=0, description="المبلغ الأساسي")
    discount: float = Field(0, ge=0, description="الخصم (ر.س)")
    tax_rate: float = Field(0, ge=0, le=100, description="نسبة الضريبة %")
    description: str = Field(..., description="وصف الفاتورة")
    status: InvoiceStatus = Field(InvoiceStatus.UNPAID, description="حالة الفاتورة")
    insurer: Optional[str] = Field(None, description="شركة التأمين")
    policy_number: Optional[str] = Field(None, description="رقم وثيقة التأمين")


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceUpdate(BaseModel):
    amount: Optional[float] = Field(None, gt=0)
    discount: Optional[float] = Field(None, ge=0)
    tax_rate: Optional[float] = Field(None, ge=0, le=100)
    description: Optional[str] = None
    status: Optional[InvoiceStatus] = None
    appointment_id: Optional[int] = None
    record_id: Optional[int] = None
    insurer: Optional[str] = None
    policy_number: Optional[str] = None


class InvoicePayment(BaseModel):
    method: str = Field("cash", description="طريقة الدفع: cash / card / insurance")
    amount: Optional[float] = Field(
        None, gt=0, description="مبلغ الدفع الجزئي (اختياري — افتراضيًا المتبقي كله)")


class InvoiceInDB(InvoiceBase):
    id: int
    payment_method: Optional[str] = None
    paid_at: Optional[datetime] = None
    paid_amount: float = 0
    subtotal: float = 0
    tax: float = 0
    total: float = 0
    created_at: datetime
    updated_at: datetime
    patient: PatientBrief

    model_config = ConfigDict(from_attributes=True)


# ===== التقارير =====
class ReportBase(BaseModel):
    title: str = Field(..., description="عنوان التقرير")
    description: Optional[str] = Field(None, description="وصف التقرير")
    report_type: str = Field(..., description="نوع التقرير")


class ReportCreate(ReportBase):
    pass


class ReportUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    report_type: Optional[str] = None


class ReportInDB(ReportBase):
    id: int
    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===== السجلات الطبية =====
class MedicalRecordBase(BaseModel):
    patient_id: int = Field(..., description="معرّف المريض")
    doctor_id: Optional[int] = Field(None, description="معرّف الطبيب")
    diagnosis: str = Field(..., description="التشخيص")
    chief_complaint: Optional[str] = Field(None, description="شكوى المريض عند الزيارة")
    prescription: Optional[str] = Field(None, description="الوصفة الطبية")
    notes: Optional[str] = Field(None, description="ملاحظات إضافية")


class MedicalRecordCreate(MedicalRecordBase):
    pass


class MedicalRecordUpdate(BaseModel):
    diagnosis: Optional[str] = None
    chief_complaint: Optional[str] = None
    prescription: Optional[str] = None
    notes: Optional[str] = None


class DoctorBrief2(ORMModel):
    id: int
    full_name: str
    specialty: str


class MedicalRecordInDB(MedicalRecordBase):
    id: int
    created_at: datetime
    updated_at: datetime
    patient: PatientBrief
    doctor: Optional[DoctorBrief2] = None

    model_config = ConfigDict(from_attributes=True)


# ===== الإشعارات =====
class NotificationInDB(ORMModel):
    id: int
    type: str
    title: str
    message: str
    appointment_id: Optional[int] = None
    patient_id: Optional[int] = None
    prescription_id: Optional[int] = None
    is_read: bool
    created_at: datetime


class NotificationMark(BaseModel):
    is_read: bool = True


# ===== المرفقات =====
class AttachmentInDB(ORMModel):
    id: int
    patient_id: int
    record_id: Optional[int] = None
    original_name: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    dicom_study_uid: Optional[str] = None
    dicom_series_uid: Optional[str] = None
    dicom_sop_uid: Optional[str] = None
    modality: Optional[str] = None
    body_part: Optional[str] = None
    patient: Optional[PatientBrief] = None


# ===== لوحة التحكم / الإحصائيات =====
class DashboardStats(BaseModel):
    total_patients: int
    total_doctors: int
    total_appointments: int
    appointments_today: int
    pending_appointments: int
    total_staff: int
    total_departments: int
    beds_available: int
    beds_occupied: int
    beds_total: int
    revenue_total: float
    revenue_paid: float
    revenue_unpaid: float
    appointments_by_status: dict


# ===== تغيير كلمة المرور =====
class PasswordChange(BaseModel):
    current_password: str = Field(..., description="كلمة المرور الحالية")
    new_password: str = Field(..., min_length=6, description="كلمة المرور الجديدة")


# ===== دليل الفحوصات (كتالوج التحاليل والأشعة) =====
class LabTestBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, description="رمز الفحص (CBC…)")
    name: str = Field(..., min_length=2, description="اسم الفحص")
    category: TestType = Field(TestType.LAB, description="lab / radiology")
    price: float = Field(0, ge=0, description="السعر")
    fasting_hours: int = Field(0, ge=0, description="ساعات الصيام المطلوبة قبل الفحص")
    tube_type: Optional[str] = Field(None, description="نوع الأنبوب المطلوب (EDTA…)")
    specimen_type: Optional[str] = Field(None, description="نوع العينة (دم، بول، مسحة…)")
    unit: Optional[str] = Field(None, description="وحدة القياس")
    ref_min: Optional[float] = Field(None, description="النطاق الطبيعي: الحد الأدنى")
    ref_max: Optional[float] = Field(None, description="النطاق الطبيعي: الحد الأعلى")
    active: bool = Field(True, description="مفعّل في نموذج الطلب")


class LabTestCreate(LabTestBase):
    pass


class LabTestUpdate(BaseModel):
    """تحديث جزئي — الحقول المفقودة تبقى كما هي."""
    code: Optional[str] = Field(None, min_length=1, max_length=40)
    name: Optional[str] = Field(None, min_length=2)
    category: Optional[TestType] = None
    price: Optional[float] = Field(None, ge=0)
    fasting_hours: Optional[int] = Field(None, ge=0)
    tube_type: Optional[str] = None
    specimen_type: Optional[str] = None
    unit: Optional[str] = None
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None
    active: Optional[bool] = None


class LabTestInDB(LabTestBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ===== غرف/أجهزة الأشعة (RIS) =====
class RadiologyRoomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="اسم الغرفة")
    modality: str = Field(..., pattern="^(XRAY|CT|MRI|ULTRASOUND)$", description="نوع الجهاز")
    description: Optional[str] = Field(None, description="وصف إضافي")
    is_active: bool = Field(True, description="متاح للجدولة")


class RadiologyRoomCreate(RadiologyRoomBase):
    pass


class RadiologyRoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    modality: Optional[str] = Field(None, pattern="^(XRAY|CT|MRI|ULTRASOUND)$")
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RadiologyRoomInDB(RadiologyRoomBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ===== طلبات المختبر والأشعة =====
class LabOrderBase(BaseModel):
    patient_id: int = Field(..., description="معرّف المريض")
    doctor_id: Optional[int] = Field(None, description="الطبيب الطالب")
    test_type: TestType = Field(TestType.LAB, description="lab / radiology")
    test_name: str = Field(..., min_length=2, description="اسم التحليل أو الأشعة")
    price: float = Field(0, ge=0, description="السعر")
    notes: Optional[str] = Field(None, description="ملاحظات")
    priority: str = Field("routine", pattern="^(routine|stat)$",
                          description="الأولوية: routine عادية / stat طارئة")
    lab_test_id: Optional[int] = Field(None, description="ربط بدليل الفحوصات")
    specimen_type: Optional[str] = Field(None, description="نوع العينة المطلوبة")
    modality: Optional[str] = Field(None, description="جهاز الأشعة (XRAY|CT|MRI|ULTRASOUND)")
    room: Optional[str] = Field(None, description="غرفة الأشعة")
    scheduled_at: Optional[datetime] = Field(None, description="موعد الفحص المجدول")


class LabOrderCreate(LabOrderBase):
    pass


class LabOrderUpdate(BaseModel):
    status: Optional[LabStatus] = None
    result: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    priority: Optional[str] = Field(None, pattern="^(routine|stat)$")
    specimen_type: Optional[str] = None
    modality: Optional[str] = Field(None, pattern="^(XRAY|CT|MRI|ULTRASOUND)$")
    room: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    report: Optional[str] = Field(None, description="تقرير الأشعة التشخيصي")


class LabOrderInDB(LabOrderBase):
    id: int
    status: LabStatus
    result: Optional[str] = None
    ordered_at: datetime
    result_at: Optional[datetime] = None
    # العينة والباركود
    barcode: Optional[str] = None
    sample_status: str = "none"
    collected_at: Optional[datetime] = None
    collected_by: Optional[str] = None
    received_at: Optional[datetime] = None
    # النتيجة ونطاقها وعلامتها
    unit: Optional[str] = None
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None
    abnormal: bool = False
    critical: bool = False
    # الاعتماد والتوقيع
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    # تقرير الأشعة
    report: Optional[str] = None
    reported_by: Optional[str] = None
    reported_at: Optional[datetime] = None
    # تسليم النتائج
    delivered_at: Optional[datetime] = None
    delivered_by: Optional[str] = None
    delivery_channel: Optional[str] = None
    patient: PatientBrief
    doctor: Optional[DoctorBrief] = None

    model_config = ConfigDict(from_attributes=True)


class LabSampleCollect(BaseModel):
    """تسجيل سحب عيّنة من المريض وتوليد باركود لها."""
    specimen_type: str = Field(..., min_length=2, max_length=60,
                               description="نوع العينة (دم، بول، مسحة…)")
    collected_by: Optional[str] = Field(None, max_length=120,
                                        description="اسم من قام بالسحب")


class LabSampleReceive(BaseModel):
    """تأكيد استلام العيّنة في المختبر أو رفضها."""
    accepted: bool = Field(True, description="true استلام / false رفض العيّنة")
    reason: Optional[str] = Field(None, max_length=300,
                                  description="سبب الرفض عند accepted=false")


class LabResultEntry(BaseModel):
    """إدخال نتيجة الفحص ومقارنتها بالنطاق الطبيعي لاستخراج علاماتها."""
    result: str = Field(..., min_length=1, description="قيمة/وصف النتيجة")
    value: Optional[float] = Field(None, description="القيمة الرقمية للمقارنة بالنطاق")
    critical: bool = Field(False, description="تعليم يدوي كقيمة حرجة")
    unit: Optional[str] = Field(None, max_length=40, description="وحدة القياس")
    ref_min: Optional[float] = Field(None, description="النطاق المرجعي الأدنى (يُرثه من الدليل)")
    ref_max: Optional[float] = Field(None, description="النطاق المرجعي الأعلى (يُرثه من الدليل)")


class LabVerify(BaseModel):
    """التوقيع الإلكتروني للاستشاري عند إتاحة النتيجة."""
    note: Optional[str] = Field(None, max_length=500, description="ملاحظة المُعتمد")


# ===== الصيدلية =====
class MedicationBase(BaseModel):
    code: str = Field(..., min_length=1, description="رمز الدواء/الباركود")
    name: str = Field(..., min_length=1, description="اسم الدواء")
    quantity: int = Field(0, ge=0, description="الكمية المتوفرة")
    unit: str = Field("علبة", description="وحدة القياس")
    price: float = Field(0, ge=0, description="سعر الوحدة")
    min_quantity: int = Field(10, ge=0, description="حد التنبيه للمخزون المنخفض")
    expiry_date: Optional[datetime] = Field(None, description="تاريخ الانتهاء")


class MedicationCreate(MedicationBase):
    pass


class MedicationUpdate(BaseModel):
    name: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=0)
    unit: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    min_quantity: Optional[int] = Field(None, ge=0)
    expiry_date: Optional[datetime] = None


class MedicationInDB(MedicationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===== مخزون عام (مستلزمات/مواد غير دوائية) =====
class GeneralStockItemBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, description="رمز الصنف")
    name: str = Field(..., min_length=2, description="اسم الصنف")
    category: str = Field("medical_supplies", description="التصنيف")
    warehouse: str = Field("main", description="المخزن")
    quantity: int = Field(0, ge=0, description="الكمية الحالية")
    min_quantity: int = Field(0, ge=0, description="حد إعادة الطلب")
    unit: str = Field("قطعة", description="وحدة القياس")
    unit_cost: float = Field(0, ge=0, description="تكلفة الوحدة")
    expiry_date: Optional[datetime] = Field(None, description="تاريخ انتهاء الصلاحية")
    # بيانات تفصيلية + مستويات إعادة الطلب (دليل المواد)
    barcode: Optional[str] = Field(None, max_length=60, description="الباركود")
    trade_name: Optional[str] = Field(None, max_length=120, description="الاسم التجاري")
    generic_name: Optional[str] = Field(None, max_length=120, description="الاسم العلمي")
    storage_condition: Optional[str] = Field(None, max_length=120, description="شروط التخزين")
    max_quantity: Optional[int] = Field(None, ge=0, description="الحد الأقصى")
    reorder_point: Optional[int] = Field(None, ge=0, description="نقطة إعادة الطلب")
    supplier_name: Optional[str] = Field(None, max_length=120, description="المورد الافتراضي")
    is_active: bool = Field(True, description="الصنف نشط")


class GeneralStockItemCreate(GeneralStockItemBase):
    pass


class GeneralStockItemUpdate(BaseModel):
    """تحديث جزئي — الحقول غير المرسلة تبقى كما هي."""
    code: Optional[str] = Field(None, min_length=1, max_length=40)
    name: Optional[str] = Field(None, min_length=2)
    category: Optional[str] = None
    warehouse: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=0)
    min_quantity: Optional[int] = Field(None, ge=0)
    unit: Optional[str] = None
    unit_cost: Optional[float] = Field(None, ge=0)
    expiry_date: Optional[datetime] = None
    barcode: Optional[str] = Field(None, max_length=60)
    trade_name: Optional[str] = Field(None, max_length=120)
    generic_name: Optional[str] = Field(None, max_length=120)
    storage_condition: Optional[str] = Field(None, max_length=120)
    max_quantity: Optional[int] = Field(None, ge=0)
    reorder_point: Optional[int] = Field(None, ge=0)
    supplier_name: Optional[str] = Field(None, max_length=120)
    is_active: Optional[bool] = None


class GeneralStockItemInDB(GeneralStockItemBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GeneralStockItemMovement(BaseModel):
    """حركة مخزون عام (توريد/صرف/جرد/إتلاف/مرتجع)."""
    item_id: int
    type: str = Field(..., description="in|out|adjust|disposal|return")
    change: int
    quantity_after: int
    note: Optional[str] = None
    made_by: Optional[str] = None
    created_at: datetime


# ===== إدارة المخازن والمستودعات والمستندات =====
class WarehouseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    kind: str = Field("main", description="main|pharmacy|emergency|or|dept")
    location: Optional[str] = None
    is_default: bool = False


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    kind: Optional[str] = None
    location: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class WarehouseOut(BaseModel):
    id: int
    name: str
    kind: str
    location: Optional[str] = None
    is_default: bool
    is_active: bool
    items_count: int = 0
    total_quantity: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockDocLineIn(BaseModel):
    """سطر مستند: صنف + كمية (+ رقم التشغيلة وتاريخ الانتهاء ووحدة التكلفة)."""
    item_id: int = Field(..., gt=0)
    quantity: int = Field(0, ge=0, description="الكمية (في الجرد: يتجاهلها counted_quantity)")
    counted_quantity: Optional[int] = Field(None, ge=0, description="العدّ الفعلي (الجرد)")
    unit_cost: Optional[float] = Field(None, ge=0)
    batch_no: Optional[str] = Field(None, max_length=60)
    expiry_date: Optional[datetime] = None
    note: Optional[str] = None


class StockDocCreate(BaseModel):
    """إنشاء مستند مخزون بأنواعه الثمانية."""
    doc_type: str = Field(..., description="grn|transfer|issue|return|supplier_return|stocktake|pr|po")
    from_warehouse_id: Optional[int] = Field(None, gt=0)
    to_warehouse_id: Optional[int] = Field(None, gt=0)
    vendor_id: Optional[int] = Field(None, gt=0)
    department_id: Optional[int] = Field(None, gt=0)
    patient_id: Optional[int] = Field(None, gt=0)
    source_doc_id: Optional[int] = Field(None, gt=0, description="طلب الشراء المصدر (لأمر الشراء)")
    reference: Optional[str] = Field(None, max_length=80)
    notes: Optional[str] = None
    needed_at: Optional[datetime] = None
    expected_at: Optional[datetime] = None
    lines: List[StockDocLineIn] = Field(..., min_length=1)


class StockDocLineOut(BaseModel):
    id: int
    item_id: int
    item_name: Optional[str] = None
    item_code: Optional[str] = None
    unit: Optional[str] = None
    quantity: int
    counted_quantity: Optional[int] = None
    unit_cost: float
    batch_no: Optional[str] = None
    expiry_date: Optional[datetime] = None
    note: Optional[str] = None


class StockDocOut(BaseModel):
    id: int
    doc_type: str
    doc_no: str
    status: str
    from_warehouse: Optional[str] = None
    to_warehouse: Optional[str] = None
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None
    department_id: Optional[int] = None
    patient_id: Optional[int] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    needed_at: Optional[datetime] = None
    expected_at: Optional[datetime] = None
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    total_quantity: int = 0
    total_value: float = 0.0
    lines: List[StockDocLineOut] = []


class StockDocAction(BaseModel):
    """اعتماد/إلغاء مستند."""
    action: str = Field(..., description="approve|cancel|complete")


class GeneralStockMovementOut(BaseModel):
    id: int
    item_id: int
    item_name: Optional[str] = None
    item_code: Optional[str] = None
    warehouse: Optional[str] = None
    type: str
    change: int
    quantity_after: int
    doc_id: Optional[int] = None
    doc_no: Optional[str] = None
    batch_no: Optional[str] = None
    expiry_date: Optional[datetime] = None
    patient_id: Optional[int] = None
    department_id: Optional[int] = None
    note: Optional[str] = None
    made_by: Optional[str] = None
    created_at: datetime


class ExpiryAlertRow(BaseModel):
    item_id: int
    item_name: Optional[str] = None
    code: Optional[str] = None
    warehouse: Optional[str] = None
    quantity: int
    batch_no: Optional[str] = None
    expiry_date: Optional[datetime] = None
    days_left: int
    value: float = 0.0


class ValuationRow(BaseModel):
    item_id: int
    item_name: Optional[str] = None
    code: Optional[str] = None
    quantity: int
    average_cost: float
    fifo_cost: float
    total_average: float
    total_fifo: float


class SlowMovingRow(BaseModel):
    item_id: int
    item_name: Optional[str] = None
    code: Optional[str] = None
    quantity: int
    issued_qty: int
    received_qty: int
    last_issue_at: Optional[datetime] = None
    days_since_issue: Optional[int] = None
    value: float = 0.0
    is_slow: bool = False


class DispenseCreate(BaseModel):
    medication_id: int = Field(..., description="معرّف الدواء")
    patient_id: int = Field(..., description="معرّف المريض")
    quantity: int = Field(1, gt=0, description="الكمية المصروفة")
    notes: Optional[str] = None
    # توجيه الاستخدام (تظهر في الإيصال وتقارير الصرف)
    dosage: Optional[str] = Field(None, description="الجرعة (مثال: قرص بعد الأكل)")
    frequency: Optional[str] = Field(None, description="التكرار (مثال: 3 مرات يوميًا)")
    duration: Optional[str] = Field(None, description="المدة (مثال: 5 أيام)")
    instructions: Optional[str] = Field(None, description="تعليمات إضافية")


class DispenseInDB(ORMModel):
    id: int
    medication_id: int
    patient_id: int
    quantity: int
    unit_price: float
    total_price: float
    payment_method: str
    status: str
    paid_amount: float
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    prescription_id: Optional[int] = None
    returned_at: Optional[datetime] = None
    return_reason: Optional[str] = None
    returned_by: Optional[str] = None
    dispensed_by: Optional[str] = None
    created_at: datetime
    medication: Optional[MedicationInDB] = None
    patient: PatientBrief


class SalePayment(BaseModel):
    paid_amount: float = Field(..., gt=0, description="المبلغ المدفوع")
    payment_method: str = Field(..., description="طريقة الدفع (cash/card/insurance)")


# ===== صرف متعدد البنود + الإرجاع =====
class DispenseItemIn(BaseModel):
    """بند واحد داخل سلة الصرف الجماعي."""
    medication_id: int = Field(..., description="معرّف الدواء")
    quantity: int = Field(1, gt=0, description="الكمية")
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    notes: Optional[str] = None


class BatchDispenseIn(BaseModel):
    """سلة صرف دفعة واحدة — تُنفَّذ كلها أو لا شيء (all-or-nothing)."""
    patient_id: int = Field(..., description="معرّف المريض")
    items: List[DispenseItemIn] = Field(..., min_length=1,
                                         description="بنود الصرف (بنود واحد على الأقل)")
    notes: Optional[str] = None


class BatchDispenseOut(BaseModel):
    """نتيجة الصرف الجماعي."""
    patient_id: int
    count: int = Field(..., description="عدد البنود المصروفة")
    total: float = Field(..., description="إجمالي المبلغ")
    low_stock: List[str] = Field(default_factory=list,
                                 description="أسماء الأدوية التي بلغت حد التنبيه")
    dispenses: List[DispenseInDB]


class DispenseReturnIn(BaseModel):
    """إرجاع صرف سابق — السبب إلزامي (لا يقبل الفراغ/المسافات)."""
    reason: str = Field(..., min_length=1, description="سبب الإرجاع")

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("سبب الإرجاع إلزامي")
        return v


class DisposeIn(BaseModel):
    """إتلاف كمية منتهية الصلاحية من المخزون (للمدير فقط)."""
    quantity: int = Field(..., gt=0, description="الكمية المُتلفة (> 0)")
    note: Optional[str] = Field(None, description="سبب الإتلاف")


# ===== الوصفات الطبية =====
class PrescriptionItemIn(BaseModel):
    medication_id: int = Field(..., description="معرّف الدواء")
    quantity: int = Field(1, gt=0, description="الكمية الموصوفة")
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None


class PrescriptionItemInDB(ORMModel):
    id: int
    medication_id: int
    quantity: int
    dispensed_quantity: int
    remaining: int
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    medication: Optional[MedicationInDB] = None

    model_config = ConfigDict(from_attributes=True)


class PrescriptionCreate(BaseModel):
    patient_id: int = Field(..., description="معرّف المريض")
    doctor_id: Optional[int] = Field(None, description="الطبيب المُصدر للوصفة (اختياري)")
    record_id: Optional[int] = Field(None, description="ربط بسجل طبي (اختياري)")
    notes: Optional[str] = None
    items: List[PrescriptionItemIn] = Field(..., min_length=1,
                                             description="بنود الوصفة (بند واحد على الأقل)")


class PrescriptionUpdate(BaseModel):
    notes: Optional[str] = None
    status: Optional[str] = Field(None, description="PENDING أو CANCELLED (يدويًا)")


class PrescriptionInDB(ORMModel):
    id: int
    patient_id: int
    doctor_id: Optional[int] = None
    record_id: Optional[int] = None
    notes: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    dispensed_at: Optional[datetime] = None
    patient: PatientBrief
    doctor: Optional[DoctorBrief] = None
    items: List[PrescriptionItemInDB]

    model_config = ConfigDict(from_attributes=True)


class PrescriptionDispenseIn(BaseModel):
    """صرف أبنية وصفة (كل الأبنية المعلَّقة أو قائمة محددة)."""
    item_ids: Optional[List[int]] = Field(
        None, description="بنود محددة (اختياري) — افتراضيًا كل الأبنية المعلَّقة")


# ===== إحصاءات الصيدلية =====
class PharmacyTopMed(BaseModel):
    """أكثر الأدوية صرفًا في الفترة."""
    medication_id: int
    code: str
    name: str
    units: int
    revenue: float


class PharmacyDailyStat(BaseModel):
    """تجميع يومي للاستهلاك والإيراد."""
    date: str
    units: int
    revenue: float


class PharmacyStats(BaseModel):
    """إحصاءات الصيدلية لفترة — تستثني عمليات الإرجاع."""
    period: str
    from_date: str
    to_date: str
    dispense_count: int
    units: int
    revenue: float
    paid: float
    outstanding: float
    inventory_value: float
    low: int
    out: int
    expired: int
    expiring: int
    top_medications: List[PharmacyTopMed]
    daily: List[PharmacyDailyStat]


class ReorderItem(BaseModel):
    """صنف منخفض يحتاج توريدًا + اقتراح كمية شراء."""
    medication_id: int
    code: str
    name: str
    quantity: int
    min_quantity: int
    unit: str
    price: float
    consumed: int = Field(..., description="المستهلَك في فترة الحساب")
    avg_per_day: float
    days_cover: Optional[float] = Field(None, description="أيام التغطية الحالية (None إن لم يُستهلَك)")
    suggested_qty: int = Field(..., description="كمية الشراء المقترحة")
    suggested_cost: float


class SaleSummary(BaseModel):
    period: str
    total_sales: float
    total_paid: float
    total_outstanding: float
    count: int
    by_payment_method: dict


class RevenuePoint(BaseModel):
    """نقطة في سلسلة الإيراد اليومي/الشهري"""
    date: str = Field(..., description="اليوم YYYY-MM-DD أو الشهر YYYY-MM")
    sales: float = Field(..., description="إجمالي المبيعات")
    collected: float = Field(..., description="المُحصَّل")
    count: int = Field(..., description="عدد العمليات")


class Debtor(BaseModel):
    """مريض عليه رصيد غير مسدد"""
    patient_id: int
    full_name: str
    operations: int = Field(..., description="عدد العمليات غير المسددة")
    total: float = Field(..., description="إجمالي مستحقاتهم")
    paid: float = Field(..., description="ما دفعوه")
    outstanding: float = Field(..., description="المتبقي")


# ===== المخزون =====
class InventoryItem(MedicationInDB):
    """صنف مخزون مع قيمة محسوبة وحالة"""
    value: float = Field(..., description="القيمة = الكمية × السعر")
    status: str = Field(..., description="ok|low|out|expiring|expired")
    days_to_expiry: Optional[int] = Field(None, description="الأيام المتبقية للانتهاء")


class InventorySummary(BaseModel):
    """ملخص حالة المخزون"""
    items: int = Field(..., description="عدد الأصناف")
    units: int = Field(..., description="إجمالي القطع")
    total_value: float = Field(..., description="قيمة المخزون")
    low: int = Field(..., description="أصناف منخفضة")
    out: int = Field(..., description="أصناف نافدة")
    expired: int = Field(..., description="أصناف منتهية الصلاحية")
    expiring: int = Field(..., description="أصناف قاربة على الانتهاء")
    expiring_days: int = Field(..., description="نافذة قرب الانتهاء بالأيام")


class StockMovementInDB(ORMModel):
    """حركة مخزون في السجل"""
    id: int
    medication_id: int
    medication_name: str = Field(..., description="اسم الدواء")
    type: str = Field(..., description="in|out|adjust|disposal|return")
    change: int = Field(..., description="موجب وارد، سالب صادر")
    quantity_after: int = Field(..., description="الرصيد بعد الحركة")
    note: Optional[str] = None
    made_by: Optional[str] = None
    created_at: datetime


class RestockIn(BaseModel):
    """توريد كمية إلى صنف"""
    quantity: int = Field(..., gt=0, description="كمية التوريد (> 0)")
    note: Optional[str] = Field(None, description="ملاحظة التوريد")


class AdjustIn(BaseModel):
    """جرد مطلق للكمية (تُسجَّل الفرق كحركة adjust)"""
    quantity: int = Field(..., ge=0, description="الرصيد الفعلي بعد الجرد")
    note: Optional[str] = Field(None, description="ملاحظة الجرد")


# ===== الرواتب =====
class PayrollBase(BaseModel):
    staff_id: int = Field(..., description="معرّف الموظف")
    period: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="الشهر YYYY-MM")
    base_salary: float = Field(0, ge=0, description="الراتب الأساسي")
    bonus: float = Field(0, ge=0, description="البدلات")
    deduction: float = Field(0, ge=0, description="الاستقطاعات")
    notes: Optional[str] = Field(None, description="ملاحظات")


class PayrollCreate(PayrollBase):
    pass


class PayrollUpdate(BaseModel):
    base_salary: Optional[float] = Field(None, ge=0)
    bonus: Optional[float] = Field(None, ge=0)
    deduction: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class PayrollInDB(PayrollBase):
    id: int
    net: float
    status: PayrollStatus
    paid_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    staff: StaffBrief



# ===== المحاسبة المؤسسية =====
class LedgerAccountCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=2, max_length=120)
    account_type: Literal["asset", "liability", "equity", "revenue", "expense"]
    parent_code: Optional[str] = Field(None, max_length=30)
    is_active: bool = True


class LedgerAccountOut(ORMModel):
    id: int
    code: str
    name: str
    account_type: str
    parent_code: Optional[str] = None
    is_active: bool
    created_at: datetime


class JournalLineIn(BaseModel):
    account_code: str
    debit: float = Field(0, ge=0)
    credit: float = Field(0, ge=0)
    description: Optional[str] = None


class JournalEntryCreate(BaseModel):
    entry_date: datetime
    description: str = Field(..., min_length=2, max_length=300)
    reference_type: Optional[str] = Field(None, max_length=30)
    reference_id: Optional[int] = Field(None, gt=0)
    lines: List[JournalLineIn] = Field(..., min_length=2)


class JournalLineOut(BaseModel):
    id: int
    account_id: int
    account_code: str
    account_name: str
    debit: float
    credit: float
    description: Optional[str] = None


class JournalEntryOut(ORMModel):
    id: int
    entry_no: str
    entry_date: datetime
    description: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    is_posted: bool
    created_by: str
    created_at: datetime
    lines: List[JournalLineOut]


class InvoiceLedgerPaymentCreate(BaseModel):
    amount: float = Field(..., gt=0)
    method: Literal["cash", "card", "bank", "insurance"] = "cash"
    paid_at: datetime
    reference: Optional[str] = Field(None, max_length=100)


class VendorCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=2, max_length=150)
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_number: Optional[str] = None
    opening_balance: float = Field(0, ge=0)


class VendorOut(ORMModel):
    id: int
    code: str
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_number: Optional[str] = None
    opening_balance: float
    is_active: bool
    created_at: datetime


class VendorBillCreate(BaseModel):
    bill_no: str = Field(..., min_length=2, max_length=40)
    vendor_id: int
    bill_date: datetime
    due_date: Optional[datetime] = None
    amount: float = Field(..., gt=0)
    expense_account_code: str = Field("5100", min_length=2, max_length=30)


class VendorBillOut(BaseModel):
    id: int
    bill_no: str
    vendor_id: int
    vendor_name: str
    bill_date: datetime
    due_date: Optional[datetime] = None
    amount: float
    paid_amount: float
    outstanding: float
    status: str
    expense_account_code: str
    journal_entry_id: int
    created_at: datetime


class VendorPaymentCreate(BaseModel):
    amount: float = Field(..., gt=0)
    paid_at: datetime
    method: Literal["cash", "card", "bank"] = "bank"
    reference: Optional[str] = Field(None, max_length=80)


class AgingBucket(BaseModel):
    bucket: str
    count: int
    total: float
    outstanding: float


class LedgerSummary(BaseModel):
    as_of: datetime
    cash: float
    accounts_receivable: float
    inventory: float
    accounts_payable: float
    revenue: float
    expenses: float
    net_income: float
    trial_balance_difference: float
    debtors: List[AgingBucket]
    creditors: List[AgingBucket]

    model_config = ConfigDict(from_attributes=True)


# ===== سجل التدقيق =====
class AuditLogInDB(ORMModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    method: str
    path: str
    status_code: Optional[int] = None
    created_at: datetime
