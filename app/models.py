from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Boolean, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class Gender(str, enum.Enum):
    MALE = "ذكر"
    FEMALE = "أنثى"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    RECEPTIONIST = "موظف استقبال"


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class InvoiceStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    PARTIAL = "partial"


class BedStatus(str, enum.Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    MAINTENANCE = "maintenance"


class TestType(str, enum.Enum):
    LAB = "lab"            # تحاليل مخبرية
    RADIOLOGY = "radiology"  # أشعة


class LabStatus(str, enum.Enum):
    PENDING = "pending"        # الطلب مسجّل
    IN_PROGRESS = "in_progress"  # قيد التنفيذ
    READY = "ready"            # النتيجة جاهزة
    REVIEWED = "reviewed"      # راجعها الطبيب
    CANCELLED = "cancelled"


class PayrollStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PAID = "paid"


# ===== المستخدمون (للتسجيل والصلاحيات) =====
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.RECEPTIONIST, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


# ===== الأقسام =====
class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    floor = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # علاقات
    beds = relationship("Bed", back_populates="department", cascade="all, delete-orphan")
    doctors = relationship("Doctor", back_populates="department")


# ===== الأسرّة =====
class Bed(Base):
    __tablename__ = "beds"

    id = Column(Integer, primary_key=True, index=True)
    bed_number = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    status = Column(SAEnum(BedStatus), default=BedStatus.AVAILABLE)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    department = relationship("Department", back_populates="beds")
    patient = relationship("Patient")


# ===== المرضى =====
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    date_of_birth = Column(DateTime, nullable=False)
    gender = Column(SAEnum(Gender), nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    blood_type = Column(String, nullable=True)
    national_id = Column(String, nullable=True)      # الهوية الوطنية/الإقامة
    insurer = Column(String, nullable=True)          # شركة التأمين (على مستوى المريض)
    policy_number = Column(String, nullable=True)    # رقم وثيقة التأمين
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # علاقات
    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="patient", cascade="all, delete-orphan")
    medical_records = relationship("MedicalRecord", back_populates="patient", cascade="all, delete-orphan")


# ===== الأطباء =====
class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    specialty = Column(String, nullable=False)
    license_number = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    is_available = Column(Boolean, default=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # علاقات
    department = relationship("Department", back_populates="doctors")
    appointments = relationship("Appointment", back_populates="doctor", cascade="all, delete-orphan")
    medical_records = relationship("MedicalRecord", back_populates="doctor")


# ===== المواعيد =====
class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    appointment_date = Column(DateTime, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(SAEnum(AppointmentStatus), default=AppointmentStatus.PENDING)
    checked_in_at = Column(DateTime, nullable=True)   # وقت الوصول (الطابور)
    queue_number = Column(Integer, nullable=True)      # رقم الطابور لليوم
    created_at = Column(DateTime, server_default=func.now())

    # علاقات
    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")


# ===== الموظفون =====
class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    position = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hire_date = Column(DateTime, nullable=False)
    salary = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ===== الفواتير =====
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    record_id = Column(Integer, ForeignKey("medical_records.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False)            # السعر الأساسي
    discount = Column(Float, nullable=False, default=0, server_default="0")   # خصم (ر.س)
    tax_rate = Column(Float, nullable=False, default=0, server_default="0")    # نسبة الضريبة %
    paid_amount = Column(Float, nullable=False, default=0, server_default="0") # المدفوع فعليًا
    description = Column(String, nullable=True)
    status = Column(SAEnum(InvoiceStatus), default=InvoiceStatus.UNPAID)
    payment_method = Column(String, nullable=True)   # cash / card / insurance
    paid_at = Column(DateTime, nullable=True)
    insurer = Column(String, nullable=True)          # شركة التأمين
    policy_number = Column(String, nullable=True)    # رقم الوثيقة
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # علاقات
    patient = relationship("Patient", back_populates="invoices")
    appointment = relationship("Appointment")
    record = relationship("MedicalRecord")

    # ===== مبالغ محسوبة (خصم + ضريبة) =====
    @property
    def subtotal(self) -> float:
        return round(float(self.amount or 0) - float(self.discount or 0), 2)

    @property
    def tax(self) -> float:
        return round(self.subtotal * float(self.tax_rate or 0) / 100.0, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.tax, 2)


# ===== التقارير =====
class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    report_type = Column(String, nullable=False)
    generated_at = Column(DateTime, server_default=func.now())


# ===== السجلات الطبية (الزيارات/التشخيصات) =====
class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    diagnosis = Column(String, nullable=False)
    prescription = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # علاقات
    patient = relationship("Patient", back_populates="medical_records")
    doctor = relationship("Doctor", back_populates="medical_records")


# ===== المرفقات الطبية (نتائج تحاليل، صور أشعة…) =====
class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    record_id = Column(Integer, ForeignKey("medical_records.id", ondelete="SET NULL"), nullable=True)
    original_name = Column(String, nullable=False)
    stored_name = Column(String, unique=True, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())

    patient = relationship("Patient")
    record = relationship("MedicalRecord")


# ===== الإشعارات =====
class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False, default="info")  # reminder / appointment / info
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    appointment = relationship("Appointment")
    patient = relationship("Patient")


# ===== طلبات المختبر والأشعة =====
class LabOrder(Base):
    __tablename__ = "lab_orders"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    test_type = Column(SAEnum(TestType), default=TestType.LAB, nullable=False)
    test_name = Column(String, nullable=False)          # اسم التحليل/الأشعة
    status = Column(SAEnum(LabStatus), default=LabStatus.PENDING, nullable=False)
    price = Column(Float, default=0)
    result = Column(String, nullable=True)              # النتيجة
    notes = Column(String, nullable=True)
    ordered_at = Column(DateTime, server_default=func.now())
    result_at = Column(DateTime, nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")


# ===== أدوية الصيدلية =====
class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)  # باركود/رمز الدواء
    name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    unit = Column(String, nullable=False, default="علبة")
    price = Column(Float, nullable=False, default=0)
    min_quantity = Column(Integer, nullable=False, default=10)  # حد التنبيه
    expiry_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ===== صرف الأدوية =====
class Dispense(Base):
    __tablename__ = "dispenses"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False, default=0)
    notes = Column(String, nullable=True)
    dispensed_by = Column(String, nullable=True)         # اسم المستخدم الذي صرف
    created_at = Column(DateTime, server_default=func.now())
    total_price = Column(Float, nullable=False, default=0)    # الإجمالي (الكمية × السعر)
    payment_method = Column(String, nullable=False, default="cash")
    status = Column(String, nullable=False, default="UNPAID")  # UNPAID/PARTIAL/PAID
    paid_amount = Column(Float, nullable=False, default=0)
    paid_at = Column(DateTime, nullable=True)
    # ===== تطوير الصيدلية: توجيه الاستخدام + الإرجاع + ربط الوصفة =====
    dosage = Column(String, nullable=True)            # الجرعة (مثال: قرص بعد الأكل)
    frequency = Column(String, nullable=True)         # التكرار (مثال: 3 مرات يوميًا)
    duration = Column(String, nullable=True)          # المدة (مثال: 5 أيام)
    instructions = Column(String, nullable=True)      # تعليمات إضافية
    prescription_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="SET NULL"), nullable=True)
    returned_at = Column(DateTime, nullable=True)     # تاريخ الإرجاع (NULL = غير مرجَع)
    return_reason = Column(String, nullable=True)
    returned_by = Column(String, nullable=True)       # اسم من نفّذ الإرجاع

    medication = relationship("Medication")
    patient = relationship("Patient")


# ===== حركات المخزون (دفتر الجرد) =====
class StockMovement(Base):
    """حركة مخزون: توريد (in) أو تسوية/جرد (adjust) — الصرف يُسجَّل أيضًا هنا."""
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)                # in | out | adjust
    change = Column(Integer, nullable=False)             # موجب وارد، سالب صادر
    quantity_after = Column(Integer, nullable=False)     # الرصيد بعد الحركة
    note = Column(String, nullable=True)
    made_by = Column(String, nullable=True)              # اسم المستخدم
    created_at = Column(DateTime, server_default=func.now())

    medication = relationship("Medication")


# ===== الرواتب =====
class Payroll(Base):
    __tablename__ = "payroll"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.id", ondelete="CASCADE"), nullable=False)
    period = Column(String, nullable=False)              # الشهر "YYYY-MM"
    base_salary = Column(Float, nullable=False, default=0)
    bonus = Column(Float, nullable=False, default=0)
    deduction = Column(Float, nullable=False, default=0)
    net = Column(Float, nullable=False, default=0)       # الصافي المحسوب
    status = Column(SAEnum(PayrollStatus), default=PayrollStatus.UNPAID)
    paid_at = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    staff = relationship("Staff")


# ===== سجل التدقيق =====
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String, nullable=True)
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")


# ===== وصفات الدواء =====
class Prescription(Base):
    """وصفة طبية: تُنشأ من الطبيب/المدير وتُصرف كاملة أو جزئيًا من الصيدلية."""
    __tablename__ = "prescriptions"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    record_id = Column(Integer, ForeignKey("medical_records.id", ondelete="SET NULL"), nullable=True)
    notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default="PENDING")  # PENDING/PARTIAL/DISPENSED/CANCELLED
    created_by = Column(String, nullable=True)                  # اسم المستخدم منشئ الوصفة
    created_at = Column(DateTime, server_default=func.now())
    dispensed_at = Column(DateTime, nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
    items = relationship("PrescriptionItem", back_populates="prescription",
                         cascade="all, delete-orphan")


class PrescriptionItem(Base):
    """بند داخل وصفة: دواء بكمية وجرعة، مع كمية الصرف المنفَّذة."""
    __tablename__ = "prescription_items"

    id = Column(Integer, primary_key=True, index=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)          # الكمية الموصوفة
    dispensed_quantity = Column(Integer, nullable=False, default=0)  # المنصَّف فعليًا
    dosage = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    instructions = Column(String, nullable=True)

    prescription = relationship("Prescription", back_populates="items")
    medication = relationship("Medication")

    @property
    def remaining(self) -> int:
        """المتبقي من البند بعد الصرف — يُستخدم في واجهة الوصفة."""
        return max(0, (self.quantity or 0) - (self.dispensed_quantity or 0))


# ===== محاور الرعاية والتشغيل المتقدم =====
# الحالات كنصوص لتسهيل الترحيل بين SQLite وPostgreSQL دون قيود ENUM جديدة.


class ServiceRequest(Base):
    """طلب موحد لمجموعات الرعاية والأسنان والعلاج الطبيعي والطوارئ المنزلية والعافية والغذاء."""
    __tablename__ = "service_requests"
    id = Column(Integer, primary_key=True, index=True)
    service_type = Column(String, nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    details = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="normal")
    status = Column(String, nullable=False, default="pending")
    scheduled_at = Column(DateTime, nullable=True)
    assigned_to = Column(String, nullable=True)
    result = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    patient = relationship("Patient")


class NursingTask(Base):
    """مهمة تمريض مرتبطة بالمريض والقسم ووردية العمل."""
    __tablename__ = "nursing_tasks"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    instructions = Column(String, nullable=True)
    shift = Column(String, nullable=False, default="day")
    priority = Column(String, nullable=False, default="normal")
    status = Column(String, nullable=False, default="pending")
    assigned_to = Column(String, nullable=True)
    due_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient")
    department = relationship("Department")


class Surgery(Base):
    """حجز عملية ودورة تشغيلها في مسرح العمليات."""
    __tablename__ = "surgeries"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    surgeon_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    procedure_name = Column(String, nullable=False)
    theater = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="elective")
    status = Column(String, nullable=False, default="scheduled")
    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    pre_op_notes = Column(String, nullable=True)
    post_op_notes = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient")
    surgeon = relationship("Doctor")


class Admission(Base):
    """دورة تنويم داخلي مرتبطة بالمريض والسرير."""
    __tablename__ = "admissions"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    bed_id = Column(Integer, ForeignKey("beds.id", ondelete="SET NULL"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    admission_date = Column(DateTime, nullable=False)
    discharge_date = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="admitted")
    diagnosis = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient")
    bed = relationship("Bed")
    department = relationship("Department")


class BloodUnit(Base):
    """وحدة دم مع الصلاحية وحالة الاستخدام."""
    __tablename__ = "blood_units"
    id = Column(Integer, primary_key=True, index=True)
    unit_number = Column(String, nullable=False, unique=True)
    donor_name = Column(String, nullable=False)
    blood_group = Column(String, nullable=False, index=True)
    component = Column(String, nullable=False, default="whole_blood")
    quantity_ml = Column(Integer, nullable=False, default=450)
    status = Column(String, nullable=False, default="available")
    expiry_date = Column(DateTime, nullable=True, index=True)
    recipient_patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    recipient = relationship("Patient")


class MaintenanceOrder(Base):
    """أمر صيانة جهاز مع الأولوية والتكلفة ودورة الإصلاح."""
    __tablename__ = "maintenance_orders"
    id = Column(Integer, primary_key=True, index=True)
    asset_name = Column(String, nullable=False)
    serial_number = Column(String, nullable=True)
    location = Column(String, nullable=True)
    issue = Column(String, nullable=False)
    priority = Column(String, nullable=False, default="normal")
    status = Column(String, nullable=False, default="open")
    technician = Column(String, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cost = Column(Float, nullable=False, default=0)
    notes = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())



class SterilizationCycle(Base):
    """دورة تعقيم مع نتيجة فحص الإفراج."""
    __tablename__ = "sterilization_cycles"
    id = Column(Integer, primary_key=True, index=True)
    machine_name = Column(String, nullable=False)
    cycle_type = Column(String, nullable=False, default="autoclave")
    load_description = Column(String, nullable=False)
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    result = Column(String, nullable=True)
    operator_name = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class SafetyEvent(Base):
    """حادث سلامة أو مكافحة عدوى مع المتابعة."""
    __tablename__ = "safety_events"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False, default="incident")
    severity = Column(String, nullable=False, default="low")
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    location = Column(String, nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    status = Column(String, nullable=False, default="open")
    preventive_action = Column(String, nullable=True)
    reported_by = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)
    occurred_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Budget(Base):
    """ميزانية سنوية أو حسب القسم مع المخطط والمنصرف."""
    __tablename__ = "budgets"
    id = Column(Integer, primary_key=True, index=True)
    fiscal_year = Column(Integer, nullable=False, index=True)
    department = Column(String, nullable=False)
    category = Column(String, nullable=False)
    allocated_amount = Column(Float, nullable=False, default=0)
    spent_amount = Column(Float, nullable=False, default=0)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class FixedAsset(Base):
    """أصل ثابت مع التكلفة وحالة التشغيل."""
    __tablename__ = "fixed_assets"
    id = Column(Integer, primary_key=True, index=True)
    asset_code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    department = Column(String, nullable=True)
    purchase_date = Column(DateTime, nullable=True)
    purchase_cost = Column(Float, nullable=False, default=0)
    salvage_value = Column(Float, nullable=False, default=0)
    useful_life_years = Column(Integer, nullable=False, default=5)
    status = Column(String, nullable=False, default="active")
    location = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PatientPortalAccount(Base):
    """حساب بوابة مريض مرتبط بسجل واحد فقط."""
    __tablename__ = "patient_portal_accounts"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, unique=True)
    username = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
class GeneralStockItem(Base):
    """مخزون عام للمستلزمات الطبية وغير الدوائية مع حد إعادة الطلب."""
    __tablename__ = "general_stock_items"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, default="medical_supplies")
    warehouse = Column(String, nullable=False, default="main")
    quantity = Column(Integer, nullable=False, default=0)
    min_quantity = Column(Integer, nullable=False, default=0)
    unit = Column(String, nullable=False, default="قطعة")
    unit_cost = Column(Float, nullable=False, default=0)
    expiry_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
