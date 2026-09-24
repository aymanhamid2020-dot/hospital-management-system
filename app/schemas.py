from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime

from app.models import (
    Gender, UserRole, AppointmentStatus, InvoiceStatus, BedStatus,
    TestType, LabStatus, PayrollStatus,
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
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    floor: Optional[str] = None


class BedInDB(ORMModel):
    id: int
    bed_number: str
    status: BedStatus
    patient_id: Optional[int] = None


class DepartmentInDB(ORMModel):
    id: int
    name: str
    description: Optional[str] = None
    floor: Optional[str] = None
    created_at: datetime
    beds: List[BedInDB] = []


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


class PatientInDB(PatientBase):
    id: int
    created_at: datetime
    updated_at: datetime

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
    pass


class DoctorUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    specialty: Optional[str] = None
    is_available: Optional[bool] = None
    department_id: Optional[int] = None


class DepartmentBrief(ORMModel):
    id: int
    name: str


class DoctorInDB(DoctorBase):
    id: int
    created_at: datetime
    updated_at: datetime
    department: Optional[DepartmentBrief] = None

    model_config = ConfigDict(from_attributes=True)


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
class StaffBase(BaseModel):
    full_name: str = Field(..., description="اسم الموظف الكامل")
    position: str = Field(..., description="المنصب/الوظيفة")
    phone: str = Field(..., description="رقم الهاتف")
    email: EmailStr = Field(..., description="البريد الإلكتروني")
    hire_date: datetime = Field(..., description="تاريخ التعيين")
    salary: Optional[float] = Field(None, description="الراتب")


class StaffCreate(StaffBase):
    pass


class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    position: Optional[str] = None
    salary: Optional[float] = None


class StaffInDB(StaffBase):
    id: int
    created_at: datetime
    updated_at: datetime

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
    prescription: Optional[str] = Field(None, description="الوصفة الطبية")
    notes: Optional[str] = Field(None, description="ملاحظات إضافية")


class MedicalRecordCreate(MedicalRecordBase):
    pass


class MedicalRecordUpdate(BaseModel):
    diagnosis: Optional[str] = None
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


# ===== طلبات المختبر والأشعة =====
class LabOrderBase(BaseModel):
    patient_id: int = Field(..., description="معرّف المريض")
    doctor_id: Optional[int] = Field(None, description="الطبيب الطالب")
    test_type: TestType = Field(TestType.LAB, description="lab / radiology")
    test_name: str = Field(..., min_length=2, description="اسم التحليل أو الأشعة")
    price: float = Field(0, ge=0, description="السعر")
    notes: Optional[str] = Field(None, description="ملاحظات")


class LabOrderCreate(LabOrderBase):
    pass


class LabOrderUpdate(BaseModel):
    status: Optional[LabStatus] = None
    result: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class LabOrderInDB(LabOrderBase):
    id: int
    status: LabStatus
    result: Optional[str] = None
    ordered_at: datetime
    result_at: Optional[datetime] = None
    patient: PatientBrief
    doctor: Optional[DoctorBrief] = None

    model_config = ConfigDict(from_attributes=True)


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
