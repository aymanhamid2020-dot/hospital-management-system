"""بيانات تجريبية غنية للنظام — قسم، أسرّة، أطباء، مرضى، مواعيد، سجلات، فواتير،
صيدلية (أدوية + وصفات بكل الحالات + صرف/إرجاع)، مرفقات.

التشغيل:  python seed_demo.py
آمن التكرار: يرفض التشغيل إذا وُجدت بيانات تجريبية سابقة (بريد @demo.local).
"""
import os
import sys
from datetime import datetime, timedelta

from app.database import SessionLocal, Base, engine, ensure_columns
from app import models  # noqa: F401
from app.auth import hash_password
from app.models import (
    Department, Bed, Doctor, Patient, Staff, Appointment, Invoice,
    MedicalRecord, Attachment, Report, User,
    Gender, UserRole, AppointmentStatus, InvoiceStatus, BedStatus,
)

DEMO_DOMAIN = "@hospital-demo.com"  # .local محجوز في التحقق من صحة البريد (EmailStr)
PASSWORD = "demo12345"


def main():
    Base.metadata.create_all(bind=engine)
    ensure_columns()  # ترحيل الأعمدة الجديدة قبل الإدخال
    db = SessionLocal()
    try:
        # --- حماية من التكرار ---
        if db.query(Patient).filter(
            Patient.email.like(f"%{DEMO_DOMAIN}")
        ).union(
            db.query(Patient).filter(Patient.email.like("%@demo.local"))
        ).count() > 0:
            print("⚠️  البيانات التجريبية موجودة مسبقًا — لا شيء لإضافته.")
            print("   (لإعادة الإنشاء: احذف المرضى ذوي البريد التجريبي أولًا)")
            return

        # ===== الأقسام (يُعاد استخدام الموجود في القاعدة) =====
        departments = []
        reused = 0
        for name, floor, desc in [
            ("الباطنية", "الطابق 1", "أمراض داخلية وضغط وسكر"),
            ("الجراحة", "الطابق 2", "جراحة عامة ومناظير"),
            ("الطوارئ", "الطابق الأرضي", "خدمات طارئة 24 ساعة"),
            ("الأطفال", "الطابق 3", "أمراض أطفال وتطعيمات"),
            ("النساء والتوليد", "الطابق 4", "ولادة وصحة المرأة"),
        ]:
            d = db.query(Department).filter(Department.name == name).first()
            if d is not None:
                reused += 1
            else:
                d = Department(name=name, floor=floor, description=desc)
                db.add(d)
            departments.append(d)
        db.flush()
        print(f"✅ الأقسام: {len(departments)} (موجودة مسبقًا: {reused})")

        # ===== الأطباء =====
        doctors_data = [
            ("د. سارة العتيبي", "باطنية", "LIC-1001", departments[0]),
            ("د. خالد الشمري", "جراحة عامة", "LIC-1002", departments[1]),
            ("د. نورة القحطاني", "طب أطفال", "LIC-1003", departments[3]),
            ("د. عمر الحربي", "طوارئ", "LIC-1004", departments[2]),
            ("د. لمى الزهراني", "نساء وتوليد", "LIC-1005", departments[4]),
            ("د. فيصل العنزي", "باطنية", "LIC-1006", departments[0]),
        ]
        doctors = []
        for i, (name, spec, lic, dept) in enumerate(doctors_data, 1):
            doc = Doctor(
                full_name=name, specialty=spec, license_number=lic,
                phone=f"055100000{i}", email=f"dr{i}{DEMO_DOMAIN}",
                department_id=dept.id, is_available=True,
            )
            db.add(doc)
            doctors.append(doc)
        db.flush()

        # حسابات مستخدمين للأطباء
        for i, doc in enumerate(doctors, 1):
            db.add(User(
                username=f"demo_doc{i}", email=doc.email, full_name=doc.full_name,
                role=UserRole.DOCTOR, hashed_password=hash_password(PASSWORD),
            ))
        print(f"✅ الأطباء: {len(doctors)} (+ حسابات دخول بكلمة {PASSWORD})")

        # ===== المرضى =====
        patients_data = [
            ("فاطمة عبدالله السالم", "1985-03-12", Gender.FEMALE, "O+", "شارع الملك فهد"),
            ("محمد إبراهيم الزهراني", "1978-11-05", Gender.MALE, "A+", "حي النخيل"),
            ("نوف سعد الدوسري", "1992-07-22", Gender.FEMALE, "B+", "شارع التحلية"),
            ("عبدالرحمن ياسر الغامدي", "1969-01-30", Gender.MALE, "AB-", "حي الياسمين"),
            ("ريم خالد المطيري", "2001-09-14", Gender.FEMALE, "O-", "شارع الأمير سلطان"),
            ("أحمد صالح البقمي", "1956-05-08", Gender.MALE, "A-", "حي الروضة"),
            ("سارة ماجد الحارثي", "1995-12-01", Gender.FEMALE, "B-", "شارع العليا"),
            ("يوسف ناصر السبيعي", "2015-04-19", Gender.MALE, "O+", "حي قرطبة"),
            ("هند عمر الرشيد", "1988-08-27", Gender.FEMALE, "A+", "شارع الثمامة"),
            ("ماجد علي الهاجري", "1973-02-16", Gender.MALE, "AB+", "حي الملقا"),
        ]
        patients = []
        for i, (name, dob, gender, blood, addr) in enumerate(patients_data, 1):
            p = Patient(
                full_name=name, date_of_birth=datetime.strptime(dob, "%Y-%m-%d"),
                gender=gender, phone=f"053200000{i}",
                email=f"patient{i}{DEMO_DOMAIN}", address=addr,
                blood_type=blood,
            )
            db.add(p)
            patients.append(p)
        db.flush()
        print(f"✅ المرضى: {len(patients)}")

        # ===== الأسرّة (تُتجاهل الأقسام التي لديها أسرّة) =====
        beds = 0
        for dept in departments:
            if db.query(Bed).filter(Bed.department_id == dept.id).count() > 0:
                continue  # القسم مزوّد بالأسرّة مسبقًا
            for n in range(1, 7):
                status = BedStatus.AVAILABLE
                pid = None
                if n <= 2:  # أول سريرين مشغولان
                    status = BedStatus.OCCUPIED
                    pid = patients[(beds + n) % len(patients)].id
                elif n == 6:
                    status = BedStatus.MAINTENANCE
                db.add(Bed(
                    bed_number=f"{dept.name[:2]}-{n:02d}",
                    department_id=dept.id, status=status, patient_id=pid,
                ))
                beds += 1
        print(f"✅ الأسرّة المضافة: {beds}")

        # ===== الموظفون =====
        staff_data = [
            ("منى الشهري", "استقبال", "2022-03-01", 6500),
            ("طارق الأحمدي", "ممرض مسؤول", "2020-07-15", 9800),
            ("سلمان الزامل", "محاسب", "2019-01-10", 11000),
            ("جواهر العتيبي", "مدير تمريض", "2018-05-20", 15000),
        ]
        for i, (name, pos, hire, sal) in enumerate(staff_data, 1):
            db.add(Staff(
                full_name=name, position=pos, phone=f"054300000{i}",
                email=f"staff{i}{DEMO_DOMAIN}",
                hire_date=datetime.strptime(hire, "%Y-%m-%d"), salary=sal,
            ))
        print(f"✅ الموظفون: {len(staff_data)}")

        # ===== المواعيد =====
        now = datetime.now()
        appts_spec = [
            # (مريض، طبيب، وقت، سبب، حالة)
            (0, 0, now - timedelta(days=30, hours=2), "كشف أولي", AppointmentStatus.COMPLETED),
            (1, 1, now - timedelta(days=14, hours=1), "استشارة ما بعد الجراحة", AppointmentStatus.COMPLETED),
            (2, 2, now - timedelta(days=7), "تطعيم طفل", AppointmentStatus.COMPLETED),
            (3, 0, now.replace(hour=11, minute=0) if now.hour < 11 else now + timedelta(days=1), "متابعة سكر وضغط", AppointmentStatus.CONFIRMED),
            (4, 3, now + timedelta(hours=5), "ألم بطني حاد", AppointmentStatus.PENDING),  # ضمن نافذة التذكير!
            (5, 5, now + timedelta(days=1, hours=2), "كشف دوري", AppointmentStatus.CONFIRMED),
            (6, 0, now + timedelta(days=2), "تحاليل", AppointmentStatus.PENDING),
            (7, 2, now + timedelta(days=3), "رشح وحرارة", AppointmentStatus.PENDING),
            (8, 4, now + timedelta(days=4), "متابعة حمل", AppointmentStatus.PENDING),
            (9, 1, now + timedelta(days=5), "استشارة", AppointmentStatus.CANCELLED),
        ]
        appointments = []
        for pi, di, when, reason, st in appts_spec:
            a = Appointment(
                patient_id=patients[pi].id, doctor_id=doctors[di].id,
                appointment_date=when.replace(microsecond=0),
                reason=reason, status=st,
            )
            db.add(a)
            appointments.append(a)
        db.flush()
        print(f"✅ المواعيد: {len(appointments)} (منها موعد واحد خلال 6 ساعات 🔔)")

        # ===== السجلات الطبية =====
        records_spec = [
            (0, 0, "التهاب لوزتين حاد", "بنسلين 500مل × 3 مرات يوميًا لمدة 5 أيام", "يرجى الكحة الدافئة"),
            (1, 1, "استئصال الزائدة الدودية", "مسكن باراسيتامول + مضاد حيوي سيفترياكسون", "راحة 10 أيام — لا يرفع أوزانًا"),
            (3, 0, "سكري من النوع الثاني + ارتفاع ضغط", "ميتفورمين 850 × 2 + لوسارتان 50", "حمية قليلة الملح — متابعة بعد شهر"),
            (4, 3, "التهاب معوي", "شرب سوائل كثيرة + بروبيوتيك", "إذا استمر القيء لأكثر من 24 ساعة عد للطوارئ"),
            (5, 5, "ارتفاع ضغط الدم", "أملوديبين 5 ملغ صباحًا", "قياس الضغط يوميًا في المنزل"),
            (6, 0, "نقص فيتامين د شديد", "فيتامين د 50000 وحدة أسبوعيًا لمدة 8 أسابيع", "تفادي الشمس المباشرة بعد التكميل"),
        ]
        records = []
        for pi, di, dx, rx, notes in records_spec:
            r = MedicalRecord(
                patient_id=patients[pi].id, doctor_id=doctors[di].id,
                diagnosis=dx, prescription=rx, notes=notes,
                created_at=now - timedelta(days=(30 - pi * 3)),
            )
            db.add(r)
            records.append(r)
        db.flush()
        print(f"✅ السجلات الطبية: {len(records)}")

        # ===== الفواتير (بها حالات دفع متنوعة) =====
        inv_spec = [
            # (مريض، مبلغ، وصف، حالة، طريقة، موعد?, سجل?, تأمين?)
            (0, 350, "كشف أولي + تحاليل دم", InvoiceStatus.PAID, "cash", None, 0, None),
            (1, 4200, "عملية جراحة الزائدة (غرفة + أدوية)", InvoiceStatus.PAID, "card", 1, 1, None),
            (3, 280, "متابعة سكر وضغط + هولتر", InvoiceStatus.PAID, "insurance", 3, 2,
             ("بوبا العربية", "POL-2026-77881")),
            (4, 190, "كشف طوارئ + محاليل", InvoiceStatus.UNPAID, None, 4, 3, None),
            (5, 160, "كشف باطنة دوري", InvoiceStatus.UNPAID, None, None, None, None),
            (6, 420, "جلسات فيتامين د + تحاليل", InvoiceStatus.PARTIAL, None, 6, 5, None),
            (7, 130, "كشف أطفال", InvoiceStatus.PAID, "cash", 7, None, None),
            (2, 95, "تطعيم", InvoiceStatus.PAID, "insurance", 2, None,
             ("التعاونية", "POL-2026-10234")),
        ]
        invoices = []
        for pi, amount, desc, st, method, appt_i, rec_i, ins in inv_spec:
            inv = Invoice(
                patient_id=patients[pi].id, amount=amount, description=desc,
                status=st,
                appointment_id=appointments[appt_i].id if appt_i is not None else None,
                record_id=records[rec_i].id if rec_i is not None else None,
            )
            if st == InvoiceStatus.PAID:
                inv.payment_method = method
                inv.paid_at = now - timedelta(days=1, hours=pi)
            if ins:
                inv.insurer, inv.policy_number = ins
            db.add(inv)
            invoices.append(inv)
        print(f"✅ الفواتير: {len(invoices)} (مدفوعة/جزئية/غير مدفوعة/تأمين)")

        # ===== الصيدلية: أدوية + وصفات بكل الحالات + صرف/إرجاع =====
        from app.models import (
            Medication, Prescription, PrescriptionItem, Dispense, StockMovement,
        )

        meds_spec = [
            # (رمز، اسم، وحدة، سعر، رصيد، حد التنبيه، أيام للانتهاء؛ سالب = منتهٍ)
            ("DEM-PAR500", "باراسيتامول 500 ملغ", "علبة", 12.5, 140, 25, 520),
            ("DEM-AMOX500", "أموكسيسيلين 500 ملغ", "علبة", 38.0, 60, 25, 300),
            ("DEM-IBU400", "إيبوبروفين 400 ملغ", "علبة", 15.0, 6, 10, 260),
            ("DEM-VITD", "فيتامين د 50000 وحدة", "شريط", 45.0, 30, 8, 700),
            ("DEM-SYRUP", "شراب أطفال خافض للحرارة", "عبوة", 22.0, 0, 5, 400),
            ("DEM-OLDAB", "مضاد حيوي قديم (للإتلاف)", "علبة", 30.0, 12, 5, -15),
            ("DEM-EYEDROP", "قطرات عين تنتهي قريبًا", "عبوة", 28.0, 14, 6, 45),
        ]
        meds = []
        for code, name, unit, price, qty, minq, days in meds_spec:
            m = Medication(code=code, name=name, unit=unit, price=price,
                           quantity=qty, min_quantity=minq,
                           expiry_date=now + timedelta(days=days))
            db.add(m)
            meds.append(m)
        db.flush()
        for m in meds:
            if m.quantity:
                db.add(StockMovement(
                    medication_id=m.id, type="in", change=m.quantity,
                    quantity_after=m.quantity, note="رصيد افتتاحي تجريبي",
                    made_by="admin"))
        print(f"✅ أدوية الصيدلية: {len(meds)} "
              "(سليمة + منخفضة + نافدة + منتهية + قاربة الانتهاء)")

        def _dispense(rx_obj, med, qty, pat_obj, dos=None, freq=None, dur=None,
                      inst=None):
            """صرف تجريبي: يخصم المخزون ويسجّل حركة صادر (مرتبط بوصفة إن وُجدت)."""
            med.quantity = max(0, med.quantity - qty)
            d = Dispense(
                medication_id=med.id, patient_id=pat_obj.id, quantity=qty,
                unit_price=med.price, total_price=round(qty * med.price, 2),
                dosage=dos, frequency=freq, duration=dur, instructions=inst,
                notes=rx_obj.notes if rx_obj else None,
                prescription_id=rx_obj.id if rx_obj else None,
                dispensed_by="admin")
            db.add(d)
            db.flush()
            db.add(StockMovement(
                medication_id=med.id, type="out", change=-qty,
                quantity_after=med.quantity,
                note=(f"صرف وصفة #{rx_obj.id}" if rx_obj else "صرف تجريبي"),
                made_by="admin"))
            return d

        # وصفة معلّمة (لم تُصرف بعد)
        rx1 = Prescription(patient_id=patients[0].id, doctor_id=doctors[0].id,
                           notes="بعد الفحص الأولي", status="PENDING",
                           created_by="admin")
        db.add(rx1)
        db.flush()
        for med_i, qty, dos, freq, dur, inst in [
                (0, 10, "قرص بعد الأكل", "3 مرات يوميًا", "5 أيام",
                 "لا تتجاوز 3 غرامات يوميًا"),
                (3, 1, "كبسولة صباحًا", "مرة يوميًا", "30 يومًا", "مع أول وجبة")]:
            db.add(PrescriptionItem(
                prescription_id=rx1.id, medication_id=meds[med_i].id,
                quantity=qty, dosage=dos, frequency=freq, duration=dur,
                instructions=inst))

        # وصفة مصروفة بالكامل
        rx2 = Prescription(patient_id=patients[3].id, doctor_id=doctors[1].id,
                           notes="متابعة ما بعد الجراحة", status="PENDING",
                           created_by="admin")
        db.add(rx2)
        db.flush()
        for med_i, qty, dos, freq, dur in [
                (0, 6, "قرص بعد الأكل", "مرتين يوميًا", "3 أيام"),
                (2, 1, "قرص بعد الأكل", "3 مرات يوميًا", "5 أيام")]:
            db.add(PrescriptionItem(
                prescription_id=rx2.id, medication_id=meds[med_i].id,
                quantity=qty, dispensed_quantity=qty,
                dosage=dos, frequency=freq, duration=dur))
            _dispense(rx2, meds[med_i], qty, patients[3], dos, freq, dur)
        rx2.status = "DISPENSED"
        rx2.dispensed_at = now - timedelta(days=2)

        # وصفة ملغاة
        rx3 = Prescription(patient_id=patients[6].id, doctor_id=doctors[0].id,
                           notes="أُلغيت بعد تعديل الجرعة", status="CANCELLED",
                           created_by="admin")
        db.add(rx3)
        db.flush()
        db.add(PrescriptionItem(
            prescription_id=rx3.id, medication_id=meds[3].id, quantity=1,
            dosage="كبسولة أسبوعيًا", frequency="مرة أسبوعيًا",
            duration="8 أسابيع"))

        # وصفة صُرف منها بند واحد فقط (PARTIAL)
        rx4 = Prescription(patient_id=patients[8].id, doctor_id=doctors[5].id,
                           notes="نقص فيتامين د", status="PENDING",
                           created_by="admin")
        db.add(rx4)
        db.flush()
        db.add(PrescriptionItem(
            prescription_id=rx4.id, medication_id=meds[3].id, quantity=6,
            dispensed_quantity=6, dosage="كبسولة أسبوعيًا",
            frequency="مرة أسبوعيًا", duration="6 أسابيع"))
        db.add(PrescriptionItem(
            prescription_id=rx4.id, medication_id=meds[0].id, quantity=10,
            dosage="قرص بعد الأكل", frequency="مرتين يوميًا",
            duration="10 أيام", instructions="مع وجبة الغداء"))
        _dispense(rx4, meds[3], 6, patients[8], "كبسولة أسبوعيًا",
                  "مرة أسبوعيًا", "6 أسابيع")
        rx4.status = "PARTIAL"

        # صرف مباشر (بيع بلا وصفة) — مدفوع
        sale = _dispense(None, meds[1], 2, patients[5])
        sale.status = "PAID"
        sale.payment_method = "cash"
        sale.paid_amount = sale.total_price
        sale.paid_at = now - timedelta(days=1)

        # صرف مُرجَعة بالكامل: يظهر في سجل الصرف ولا يدخل الإيراد
        d_ret = _dispense(None, meds[3], 1, patients[4])
        meds[3].quantity += d_ret.quantity  # الإرجاع يعيد الكمية للمخزون
        db.add(StockMovement(
            medication_id=meds[3].id, type="return", change=d_ret.quantity,
            quantity_after=meds[3].quantity,
            note=f"إرجاع صرف #{d_ret.id}: الدواء غير مناسب",
            made_by="admin"))
        d_ret.returned_at = now - timedelta(hours=6)
        d_ret.return_reason = "الدواء غير مناسب للمريض"
        d_ret.returned_by = "admin"
        print("✅ وصفات الصيدلية: 4 (معلّمة/مصروفة/ملغاة/جزئية) "
              "+ صرف مباشر + مُرجَعة")

        # ===== مرفقات (صور PNG تجريبية) =====
        from app.routers.attachments import UPLOAD_DIR
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        import base64
        import uuid
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE"
            "QVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        att_count = 0
        for att_spec in [
            (0, 0, "xray_chest.png", "image/png"),
            (3, 2, "lab_glucose.png", "image/png"),
            (6, 5, "lab_vitamin_d.png", "image/png"),
        ]:
            pi, ri, fname, ctype = att_spec
            stored = f"{uuid.uuid4().hex}.png"
            with open(os.path.join(UPLOAD_DIR, stored), "wb") as f:
                f.write(png)
            db.add(Attachment(
                patient_id=patients[pi].id, record_id=records[ri].id,
                original_name=fname, stored_name=stored,
                content_type=ctype, size_bytes=len(png),
            ))
            att_count += 1
        print(f"✅ المرفقات: {att_count}")

        # ===== تقارير =====
        db.add(Report(title="التقرير الشهري للاستقبال", report_type="شهري",
                      description="إحصائيات المواعيد والمرضى"))
        db.add(Report(title="تقرير الإيرادات الربع سنوي", report_type="مالي",
                      description="الفواتير المحصلة والمتأخرات"))
        db.flush()

        db.commit()
        print("\n" + "=" * 50)
        print("🎉 تم إنشاء البيانات التجريبية بنجاح!")
        print(f"   دخول الأطباء: demo_doc1..6 / {PASSWORD}")
        print(f"   دخول المدير:  admin / admin123")
        print("=" * 50)
    except Exception:
        db.rollback()  # لا يُترك نصف بيانات عند أي خطأ
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
