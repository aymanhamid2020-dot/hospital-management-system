from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean, Time, ForeignKey,
    Enum as SAEnum, Index, UniqueConstraint
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


class ClaimStatus(str, enum.Enum):
    SUBMITTED = "submitted"   # مُقدَّمة لشركة التأمين
    APPROVED = "approved"     # موافق عليها
    REJECTED = "rejected"     # مرفوضة
    PAID = "paid"             # مسدَّدة لشركة التأمين


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
    # ===== الملف الشخصي والإداري (تكميل) =====
    nationality = Column(String, nullable=True)      # الجنسية
    smoking_status = Column(String, nullable=True)   # حالة التدخين
    emergency_contact_name = Column(String, nullable=True)      # جهة الطوارئ
    emergency_contact_phone = Column(String, nullable=True)     # هاتف الطوارئ
    emergency_contact_relation = Column(String, nullable=True)  # صلة القرابة
    insurance_grade = Column(String, nullable=True)  # درجة التغطية (ذهبية/فضية/…)
    insurance_copay = Column(Float, nullable=True)    # نسبة التحمل Co-pay %
    # ===== التاريخ الطبي والحساسية (تُحدَّث في الملف) =====
    chronic_conditions = Column(Text, nullable=True)     # الأمراض المزمنة
    past_surgeries = Column(Text, nullable=True)         # العمليات السابقة
    family_history = Column(Text, nullable=True)         # التاريخ العائلي المرضي
    allergies = Column(Text, nullable=True)              # الحساسية (أدوية/أطعمة)
    medical_warnings = Column(Text, nullable=True)       # تحذيرات (سكر، سيولة…)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # علاقات
    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="patient", cascade="all, delete-orphan")
    medical_records = relationship("MedicalRecord", back_populates="patient", cascade="all, delete-orphan")
    vital_signs = relationship(
        "VitalSign", back_populates="patient", cascade="all, delete-orphan",
        order_by="desc(VitalSign.recorded_at)")
    insurance_claims = relationship(
        "InsuranceClaim", back_populates="patient", cascade="all, delete-orphan",
        order_by="desc(InsuranceClaim.submitted_at)")


# ===== العلامات الحيوية (الضغط/الحرارة/النبض/الوزن/الطول عبر الزيارات) =====
class VitalSign(Base):
    __tablename__ = "vital_signs"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    recorded_by = Column(String, nullable=True)        # من سجّل القراءة
    systolic = Column(Integer, nullable=True)         # الضغط الانقباضي
    diastolic = Column(Integer, nullable=True)         # الضغط الانبساطي
    temperature = Column(Float, nullable=True)         # الحرارة °C
    pulse = Column(Integer, nullable=True)             # النبض
    weight = Column(Float, nullable=True)              # الوزن كجم
    height = Column(Float, nullable=True)              # الطول سم
    notes = Column(String, nullable=True)
    recorded_at = Column(DateTime, server_default=func.now())

    patient = relationship("Patient", back_populates="vital_signs")

    @property
    def bmi(self):
        """مؤشر كتلة الجسم من الوزن والطول — None إن نقص أحدهما."""
        if not self.weight or not self.height or self.height <= 0:
            return None
        return round(self.weight / ((self.height / 100) ** 2), 1)


# ===== مطالبات التأمين (الموافقة/الرفض من شركة التأمين) =====
class InsuranceClaim(Base):
    __tablename__ = "insurance_claims"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    claim_number = Column(String, nullable=False)     # رقم المطالبة
    insurer = Column(String, nullable=True)           # شركة التأمين (مطابقة للمريض)
    amount = Column(Float, nullable=False, default=0)  # قيمة المطالبة
    approved_amount = Column(Float, nullable=True)     # القيمة الموافق عليها
    status = Column(SAEnum(ClaimStatus), default=ClaimStatus.SUBMITTED, nullable=False)
    decision_notes = Column(String, nullable=True)    # ملاحظات القرار
    rejection_reason = Column(String, nullable=True)   # سبب الرفض
    submitted_at = Column(DateTime, server_default=func.now())
    decided_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="insurance_claims")
    invoice = relationship("Invoice")


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
    # ملف الموارد البشرية: الأقسام السبعة تُحفظ كـ JSON لتفادي كسر قواعد
    # SQLite/PostgreSQL عند إضافة أعمدة جديدة. القيم الافتراضية تُملأ في الواجهة.
    hr_profile = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    documents = relationship(
        "StaffDocument", back_populates="staff", cascade="all, delete-orphan", lazy="selectin"
    )


class StaffDocument(Base):
    """مرفق موظف: هوية/عقد/سيرة ذاتية/شهادة."""
    __tablename__ = "staff_documents"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    stored_name = Column(String, unique=True, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())

    staff = relationship("Staff", back_populates="documents")


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
    chief_complaint = Column(String, nullable=True)   # شكوى المريض عند الزيارة
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

    # — أولوية الطلب وربطه بدليل الفحوصات (LIS/RIS) —
    priority = Column(String, default="routine")        # routine | stat
    lab_test_id = Column(Integer, ForeignKey("lab_tests.id", ondelete="SET NULL"), nullable=True)
    # — سحب العينة والباركود —
    specimen_type = Column(String, nullable=True)       # دم، بول، مسحة…
    barcode = Column(String, unique=True, nullable=True)
    sample_status = Column(String, default="none")      # none|collected|received|rejected
    collected_at = Column(DateTime, nullable=True)
    collected_by = Column(String, nullable=True)
    received_at = Column(DateTime, nullable=True)
    # — إدخال النتيجة ونطاقها المرجعي —
    unit = Column(String, nullable=True)
    ref_min = Column(Float, nullable=True)
    ref_max = Column(Float, nullable=True)
    abnormal = Column(Boolean, default=False)           # خارج النطاق الطبيعي
    critical = Column(Boolean, default=False)           # قيمة حرجة تتطلب إشعارًا
    # — اعتماد التقرير والتوقيع الإلكتروني —
    verified_by = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    # — الأشعة (RIS): تصنيف وجدولة وتقرير —
    modality = Column(String, nullable=True)            # XRAY|CT|MRI|ULTRASOUND
    room = Column(String, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    report = Column(Text, nullable=True)                # التقرير التشخيصي
    reported_by = Column(String, nullable=True)
    reported_at = Column(DateTime, nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")


# ===== دليل الفحوصات (كتالوج التحاليل والأشعة) =====
class LabTest(Base):
    __tablename__ = "lab_tests"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)   # رمز الفحص (CBC، XR-PA)
    name = Column(String, nullable=False)
    category = Column(SAEnum(TestType), default=TestType.LAB, nullable=False)
    price = Column(Float, default=0)
    fasting_hours = Column(Integer, default=0)           # ساعات الصيام المطلوبة
    tube_type = Column(String, nullable=True)            # نوع الأنبوب (EDTA، سيرم…)
    specimen_type = Column(String, nullable=True)        # نوع العينة
    unit = Column(String, nullable=True)                 # وحدة القياس
    ref_min = Column(Float, nullable=True)               # النطاق الطبيعي: الحد الأدنى
    ref_max = Column(Float, nullable=True)               # النطاق الطبيعي: الحد الأعلى
    active = Column(Boolean, default=True)               # مفعّل في نموذج الطلب

    orders = relationship("LabOrder", backref="test_catalog")


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


class CarePlan(Base):
    """خطة رعاية متعددة العناصر مرتبطة بالمريض وقد تربط بالتنويم والطلب."""
    __tablename__ = "care_plans"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id", ondelete="SET NULL"), nullable=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id", ondelete="SET NULL"), nullable=True, index=True)
    responsible_doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    goals = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    coordinator = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    patient = relationship("Patient")
    service_request = relationship("ServiceRequest")
    admission = relationship("Admission")
    responsible_doctor = relationship("Doctor")
    items = relationship("CarePlanItem", back_populates="plan", cascade="all, delete-orphan", lazy="selectin")


class CarePlanItem(Base):
    """بند داخل خطة الرعاية، له مسؤول وموعد وطريقة تحقق."""
    __tablename__ = "care_plan_items"
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("care_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String, nullable=False)
    title = Column(String, nullable=False)
    instructions = Column(String, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    assigned_to = Column(String, nullable=True)
    verification_method = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    plan = relationship("CarePlan", back_populates="items")
    executions = relationship("CarePlanExecution", back_populates="item", cascade="all, delete-orphan", lazy="selectin")


class CarePlanExecution(Base):
    """سجل تنفيذ فعلي لبند؛ يضمن فهرس التفرد عدم تكرار التنفيذ في الوقت نفسه."""
    __tablename__ = "care_plan_executions"
    __table_args__ = (
        UniqueConstraint("item_id", "executed_at", name="uq_care_item_execution_time"),
    )
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("care_plan_items.id", ondelete="CASCADE"), nullable=False, index=True)
    executed_at = Column(DateTime, nullable=False, index=True)
    performed_by = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    outcome = Column(String, nullable=False, default="completed")
    item = relationship("CarePlanItem", back_populates="executions")

class DentalChart(Base):
    """مخطط أسنان وملخص طبي لمريض؛ سجل واحد لكل مريض."""
    __tablename__ = "dental_charts"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    allergies = Column(String, nullable=True)
    medical_conditions = Column(String, nullable=True)
    last_exam_at = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)
    updated_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    patient = relationship("Patient")


class DentalTreatmentPlan(Base):
    """خطة علاج سنchner مرتبطة بالمريض والطبيب وطلب خدمة الأسنان."""
    __tablename__ = "dental_treatment_plans"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    dentist_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String, nullable=False)
    chief_complaint = Column(String, nullable=False)
    diagnosis = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active", index=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    patient = relationship("Patient")
    dentist = relationship("Doctor")
    service_request = relationship("ServiceRequest")
    procedures = relationship(
        "DentalProcedure", back_populates="plan", cascade="all, delete-orphan", lazy="selectin",
        order_by="DentalProcedure.id",
    )


class DentalProcedure(Base):
    """إجراء سنchner مخطط أو منفذ داخل خطة علاج."""
    __tablename__ = "dental_procedures"
    __table_args__ = (
        UniqueConstraint(
            "plan_id", "tooth_number", "procedure_type", "performed_at",
            name="uq_dental_procedure_session",
        ),
    )
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("dental_treatment_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    dentist_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    tooth_number = Column(Integer, nullable=True)
    surfaces = Column(String, nullable=True)
    procedure_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="planned", index=True)
    scheduled_at = Column(DateTime, nullable=True)
    performed_at = Column(DateTime, nullable=True, index=True)
    notes = Column(String, nullable=True)
    material = Column(String, nullable=True)
    cost = Column(Float, nullable=False, default=0)
    follow_up_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    plan = relationship("DentalTreatmentPlan", back_populates="procedures")
    dentist = relationship("Doctor")




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


# ===== المحاسبة المؤسسية: شجرة الحسابات والقيود المزدوجة =====
class Account(Base):
    """حساب في دليل الحسابات المؤسسي."""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False, unique=True)
    account_type = Column(String, nullable=False)  # asset/liability/equity/revenue/expense
    parent_code = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    lines = relationship("JournalLine", back_populates="account")


class JournalEntry(Base):
    """قيد يومية متوازن؛ كل قيد له سطران أو أكثر على الأقل."""
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    entry_no = Column(String, nullable=False, unique=True, index=True)
    entry_date = Column(DateTime, nullable=False, index=True)
    description = Column(String, nullable=False)
    reference_type = Column(String, nullable=True, index=True)  # invoice/payment/manual/expense
    reference_id = Column(Integer, nullable=True, index=True)
    is_posted = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    lines = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan", lazy="joined"
    )


class JournalLine(Base):
    """سطر مدين/دائن ضمن قيد محاسبي."""
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    debit = Column(Float, nullable=False, default=0)
    credit = Column(Float, nullable=False, default=0)
    description = Column(String, nullable=True)

    entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account", back_populates="lines")


class Vendor(Base):
    """مورد/دائن مستقل مع رصيد افتتاحي."""
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False, unique=True)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    tax_number = Column(String, nullable=True)
    opening_balance = Column(Float, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    bills = relationship("VendorBill", back_populates="vendor")


class VendorBill(Base):
    """فاتورة مورد تكوّن دين الموردين في حساب الذمم الدائنة."""
    __tablename__ = "vendor_bills"

    id = Column(Integer, primary_key=True, index=True)
    bill_no = Column(String, nullable=False, unique=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    bill_date = Column(DateTime, nullable=False, index=True)
    due_date = Column(DateTime, nullable=True, index=True)
    amount = Column(Float, nullable=False)
    paid_amount = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="unpaid")  # unpaid/partial/paid
    expense_account_code = Column(String, nullable=False, default="5100")
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, unique=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    vendor = relationship("Vendor", back_populates="bills")
    payments = relationship("VendorPayment", back_populates="bill", cascade="all, delete-orphan")


class VendorPayment(Base):
    """دفعة إلى مورد مرتبطة بفاتورة وقيد محاسبي."""
    __tablename__ = "vendor_payments"
    __table_args__ = (
        UniqueConstraint("bill_id", "reference", name="uq_vendor_ledger_payment_reference"),
    )

    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey("vendor_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, nullable=False)
    method = Column(String, nullable=False, default="bank")
    reference = Column(String, nullable=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, unique=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    bill = relationship("VendorBill", back_populates="payments")


class InvoiceLedgerPayment(Base):
    """دفعة فاتورة مرتبطة بقيد محاسبي مع منع تكرار المرجع."""
    __tablename__ = "invoice_ledger_payments"
    __table_args__ = (
        UniqueConstraint("invoice_id", "reference", name="uq_invoice_ledger_payment_reference"),
    )

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    method = Column(String, nullable=False, default="cash")
    paid_at = Column(DateTime, nullable=False)
    reference = Column(String, nullable=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, unique=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class DoctorSchedule(Base):
    """نوبات عمل الطبيب الأسبوعية — نوبتان كحد أقصى لكل يوم."""
    __tablename__ = "doctor_schedules"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False)  # 0=السبت … 6=الجمعة
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    location = Column(String, nullable=True)       # حجرة/عيادة اختيارية
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_schedule_doctor_day", "doctor_id", "day_of_week"),
    )


# ===== وحدات تشغيل مستقلة للخدمات المكملة =====
class PhysiotherapyCase(Base):
    __tablename__ = "physiotherapy_cases"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    therapist_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(160), nullable=False)
    assessment = Column(String(2000), nullable=True)
    plan = Column(String(2000), nullable=True)
    notes = Column(String(2000), nullable=True)
    status = Column(String(30), nullable=False, default="assessed", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


class NutritionCase(Base):
    __tablename__ = "nutrition_cases"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    dietary_plan = Column(String(2000), nullable=True)
    meal_plan = Column(String(2000), nullable=True)
    notes = Column(String(2000), nullable=True)
    status = Column(String(30), nullable=False, default="assessed", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)


class EmergencyCase(Base):
    __tablename__ = "emergency_cases"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True)
    complaint = Column(String(1000), nullable=False)
    triage_level = Column(String(20), nullable=False, default="standard")
    arrival_at = Column(DateTime, nullable=False, index=True)
    disposition = Column(String(160), nullable=True)
    notes = Column(String(2000), nullable=True)
    status = Column(String(30), nullable=False, default="arrived", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)


class HomeHealthCase(Base):
    __tablename__ = "home_health_cases"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    coordinator = Column(String(120), nullable=True)
    care_plan = Column(String(2000), nullable=True)
    next_visit_at = Column(DateTime, nullable=True, index=True)
    visits_completed = Column(Integer, nullable=False, default=0)
    notes = Column(String(2000), nullable=True)
    status = Column(String(30), nullable=False, default="referred", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


class WellnessProgram(Base):
    __tablename__ = "wellness_programs"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    program_name = Column(String(160), nullable=False)
    goal = Column(String(1000), nullable=False)
    baseline_metrics = Column(String(2000), nullable=True)
    progress_notes = Column(String(2000), nullable=True)
    next_review_at = Column(DateTime, nullable=True, index=True)
    status = Column(String(30), nullable=False, default="planned", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)


class HomeCareManagementCase(Base):
    __tablename__ = "home_care_management_cases"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment = Column(String(2000), nullable=True)
    intervention_plan = Column(String(2000), nullable=True)
    follow_up_at = Column(DateTime, nullable=True, index=True)
    notes = Column(String(2000), nullable=True)
    status = Column(String(30), nullable=False, default="assessment", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)



class HousekeepingTask(Base):
    __tablename__ = "housekeeping_tasks"
    id = Column(Integer, primary_key=True, index=True)
    room_number = Column(String(50), nullable=False, index=True)
    task_type = Column(String(50), nullable=False, default="cleaning")
    priority = Column(String(20), nullable=False, default="normal")
    assigned_to = Column(String(100), nullable=True)
    notes = Column(String(2000), nullable=True)
    status = Column(String(30), nullable=False, default="pending", index=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

