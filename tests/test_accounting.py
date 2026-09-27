"""اختبارات تكامل للمحاسبة المؤسسية ودفتر القيود المزدوج."""
import uuid

from conftest import login


def _uid():
    return uuid.uuid4().hex[:8]


def _patient(client, admin):
    suffix = _uid()
    response = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض محاسبة {suffix}",
        "date_of_birth": "1990-01-01",
        "gender": "ذكر",
        "phone": f"050{suffix[-7:]}",
        "email": f"ledger_{suffix}@test.com",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _invoice(client, admin, patient_id, suffix):
    response = client.post("/invoices/", headers=admin, json={
        "patient_id": patient_id,
        "amount": 100,
        "description": f"فاتورة تأمين {suffix}",
        "insurer": "شركة اختبار للتأمين",
        "policy_number": f"POL-{suffix}",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_ledger_invoice_payment_is_balanced_and_idempotent(client, admin):
    suffix = _uid()
    patient_id = _patient(client, admin)
    invoice_id = _invoice(client, admin, patient_id, suffix)

    # الفاتورة تُرحَّل تلقائيًا لحظة إنشائها، فالتحصيل متاح فورًا
    # ولا حاجة لأمر ترحيل يدوي يسبقها.
    payment = client.post(
        f"/accounts/ledger/invoices/{invoice_id}/payments",
        headers=admin,
        json={
            "amount": 25,
            "method": "insurance",
            "paid_at": "2026-01-15T10:00:00",
            "reference": f"REC-{suffix}",
        },
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["invoice_status"] == "partial"

    # الترحيل اليدوي على فاتورة سبق ترحيلها تلقائيًّا ⇒ 409 ولا قيد ثانٍ.
    duplicate_post = client.post(f"/accounts/ledger/invoices/{invoice_id}/post", headers=admin)
    assert duplicate_post.status_code == 409, duplicate_post.text
    invoice_entries = [
        e for e in client.get("/accounts/ledger/entries", headers=admin).json()
        if e["reference_type"] == "patient_invoice" and e["reference_id"] == invoice_id
    ]
    assert len(invoice_entries) == 1, "أُنشئ قيد مكرر للفاتورة"
    lines = invoice_entries[0]["lines"]
    assert sum(line["debit"] for line in lines) == \
        sum(line["credit"] for line in lines)

    # المرجع المكرّر يُمنع على مسار التحصيل اليدوي
    duplicate_payment = client.post(
        f"/accounts/ledger/invoices/{invoice_id}/payments",
        headers=admin,
        json={
            "amount": 10,
            "method": "insurance",
            "paid_at": "2026-01-15T11:00:00",
            "reference": f"REC-{suffix}",
        },
    )
    assert duplicate_payment.status_code == 409, duplicate_payment.text

    trial = client.get("/accounts/ledger/trial-balance", headers=admin)
    assert trial.status_code == 200, trial.text
    assert trial.json()["difference"] == 0


def test_invoice_and_payment_post_journals_automatically(client, admin):
    """القيد يُنشأ لحظة الحدث لا بأمر «ترحيل»: الفاتورة ثم تحصيلها.

    النموذج القديم كان «أنشئ الفاتورة ثم اطلب ترحيلها من شاشة
    المحاسبة»، فتبقى الإيرادات خارج الدفتر إن نسي المستخدم. الآن يدخل
    القيدان لحظة وقوعهما والميزان متزن دون تدخّل.
    """
    suffix = _uid()
    patient_id = _patient(client, admin)
    invoice_id = _invoice(client, admin, patient_id, suffix)

    def entries():
        return client.get("/accounts/ledger/entries", headers=admin).json()

    auto = [e for e in entries()
            if e["reference_type"] == "patient_invoice"
            and e["reference_id"] == invoice_id]
    assert len(auto) == 1, f"قيود الفاتورة: {len(auto)} (المتوقع 1)"
    assert auto[0]["is_posted"] is True
    assert sum(l["debit"] for l in auto[0]["lines"]) == \
        sum(l["credit"] for l in auto[0]["lines"]) == 100
    # ذمم التأمين (مدين) مقابل إيراد الخدمات (دائن)
    assert {l["account_code"] for l in auto[0]["lines"]} == {"1110", "4000"}

    # التحصيل: الصندوق مدين مقابل الذمم دائن — وبصفّ سجل مربوط بالقيد
    r = client.post(f"/invoices/{invoice_id}/pay", headers=admin,
                    json={"method": "cash", "amount": 40})
    assert r.status_code == 200, r.text

    pays = [e for e in entries()
            if e["reference_type"] == "patient_invoice_payment"
            and e["reference_id"] == invoice_id]
    assert len(pays) == 1, f"قيود التحصيل: {len(pays)} (المتوقع 1)"
    assert {l["account_code"] for l in pays[0]["lines"]} == {"1000", "1110"}
    assert sum(l["debit"] for l in pays[0]["lines"]) == 40

    from app.database import SessionLocal
    from app.models import InvoiceLedgerPayment
    db = SessionLocal()
    try:
        rows = db.query(InvoiceLedgerPayment).filter(
            InvoiceLedgerPayment.invoice_id == invoice_id).all()
        assert len(rows) == 1, "لم يُنشأ صفّ سجل التحصيل"
        assert rows[0].journal_entry_id == pays[0]["id"]
        assert rows[0].amount == 40
    finally:
        db.close()

    trial = client.get("/accounts/ledger/trial-balance", headers=admin)
    assert trial.status_code == 200, trial.text
    assert trial.json()["difference"] == 0


def test_invoice_creation_survives_journal_failure(client, admin, monkeypatch):
    """فشل الترحيل التلقائي لا يُسقط إنشاء الفاتورة — ثمة ترحيل يدوي بديل.

    دالة الترحيل تفشل هنا بعمد (حساب غير نشط) فتُعاد الفاتورة مع بقائها
    خارج الدفتر حتى يُرحّلها المدير لاحقًا بـpost.
    """
    from app.routers import accounting as acc

    suffix = _uid()
    patient_id = _patient(client, admin)

    def boom(db, invoice, username):
        return None, "حساب غير نشط (تفعيل مقصود للاختبار)"

    monkeypatch.setattr(acc, "auto_post_invoice", boom)

    r = client.post("/invoices/", headers=admin, json={
        "patient_id": patient_id, "amount": 55,
        "description": f"فاتورة بلا قيد {suffix}",
    })
    assert r.status_code == 200, r.text
    invoice_id = r.json()["id"]
    assert invoice_id

    # وما زال بإمكان المدير ترحيلها يدويًّا بعد ذلك (المسار لا يعتمد
    # على الدالة المُعطَّلة — يبني القيد بنفسه)
    posted = client.post(f"/accounts/ledger/invoices/{invoice_id}/post",
                         headers=admin)
    assert posted.status_code == 200, posted.text
    assert sum(l["debit"] for l in posted.json()["lines"]) == 55


def test_ledger_vendor_bill_and_payment(client, admin):
    suffix = _uid()
    vendor = client.post("/accounts/ledger/vendors", headers=admin, json={
        "code": f"V-{suffix}",
        "name": f"مورد محاسبة {suffix}",
    })
    assert vendor.status_code == 201, vendor.text
    vendor_id = vendor.json()["id"]

    bill = client.post("/accounts/ledger/vendor-bills", headers=admin, json={
        "bill_no": f"BILL-{suffix}",
        "vendor_id": vendor_id,
        "bill_date": "2026-01-10T10:00:00",
        "due_date": "2026-02-10T10:00:00",
        "amount": 200,
        "expense_account_code": "5100",
    })
    assert bill.status_code == 201, bill.text
    bill_id = bill.json()["id"]

    duplicate_bill = client.post("/accounts/ledger/vendor-bills", headers=admin, json={
        "bill_no": f"BILL-{suffix}",
        "vendor_id": vendor_id,
        "bill_date": "2026-01-10T10:00:00",
        "amount": 200,
    })
    assert duplicate_bill.status_code == 409, duplicate_bill.text

    payment = client.post(
        f"/accounts/ledger/vendor-bills/{bill_id}/payments",
        headers=admin,
        json={
            "amount": 50,
            "paid_at": "2026-01-15T10:00:00",
            "method": "bank",
            "reference": f"VP-{suffix}",
        },
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["bill_status"] == "partial"

    duplicate_payment = client.post(
        f"/accounts/ledger/vendor-bills/{bill_id}/payments",
        headers=admin,
        json={
            "amount": 10,
            "paid_at": "2026-01-16T10:00:00",
            "method": "bank",
            "reference": f"VP-{suffix}",
        },
    )
    assert duplicate_payment.status_code == 409, duplicate_payment.text

    summary = client.get("/accounts/ledger/summary", headers=admin)
    assert summary.status_code == 200, summary.text
    assert summary.json()["trial_balance_difference"] == 0


def _staff(client, admin):
    suffix = _uid()
    r = client.post("/staff/", headers=admin, json={
        "full_name": f"موظف قيود {suffix}", "position": "ممرض",
        "phone": f"056{suffix[-7:]}", "email": f"jr_{suffix}@test.com",
        "hire_date": "2025-01-01", "salary": 4000,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ledger_for(client, admin, ref_type, ref_id):
    return [e for e in client.get("/accounts/ledger/entries", headers=admin).json()
            if e["reference_type"] == ref_type and e["reference_id"] == ref_id]


def test_payroll_accrual_and_disbursement_post_automatically(client, admin):
    """الرواتب: الاستحقاق يُثبَّت لحظة الإنشاء والصرف يُرحَّل لحظة الصرف.

    بدون هذين القيدَين يتحرك النقد بلا أثر في الدفتر ويتراجع حساب
    «مستحقات رواتب الموظفين» (2100) إلى التعريف فقط.
    """
    sid = _staff(client, admin)
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": sid, "period": "2031-03", "base_salary": 4000,
        "bonus": 500, "deduction": 100})
    assert r.status_code == 200, r.text
    pid, net = r.json()["id"], r.json()["net"]
    assert net == 4400

    # إثبات الاستحقاق: مصروف الرواتب (5200) مدين مقابل مستحقات (2100) دائن
    accruals = _ledger_for(client, admin, "payroll", pid)
    assert len(accruals) == 1, f"قيود الاستحقاق: {len(accruals)} (المتوقع 1)"
    assert {l["account_code"] for l in accruals[0]["lines"]} == {"5200", "2100"}
    assert sum(l["debit"] for l in accruals[0]["lines"]) == net

    # الصرف: إقفال المستحق مقابل النقدية
    r = client.post(f"/payroll/{pid}/pay", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    pays = _ledger_for(client, admin, "payroll_payment", pid)
    assert len(pays) == 1, f"قيود الصرف: {len(pays)} (المتوقع 1)"
    assert {l["account_code"] for l in pays[0]["lines"]} == {"2100", "1000"}
    assert sum(l["debit"] for l in pays[0]["lines"]) == net
    # وقيد الاستحقاق لم يُنشأ مرّة ثانية عند الصرف
    assert len(_ledger_for(client, admin, "payroll", pid)) == 1

    trial = client.get("/accounts/ledger/trial-balance", headers=admin)
    assert trial.status_code == 200, trial.text
    assert trial.json()["difference"] == 0


def test_payroll_update_posts_balancing_adjustment(client, admin):
    """تعديل صافي راتبٍ مُثبَّت يُنشئ قيد تعديل موازن — والصرف يستعمل الصافي الأخير.

    لولوَن التعديل لبقيت الذمة بالمبلغ القديم: استحقاق 5100 ثم صرف 5400
    يُظهر رصيدًا سالبًا في الذمة رغم أن ميزان المراجعة لا يلاحظ شيئًا.
    """
    sid = _staff(client, admin)
    r = client.post("/payroll/", headers=admin, json={
        "staff_id": sid, "period": "2031-04", "base_salary": 5000,
        "bonus": 400, "deduction": 300})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["net"] == 5100
    assert len(_ledger_for(client, admin, "payroll", pid)) == 1

    r = client.put(f"/payroll/{pid}", headers=admin, json={"bonus": 700})
    assert r.status_code == 200, r.text
    assert r.json()["net"] == 5400

    adjustments = _ledger_for(client, admin, "payroll_adjustment", pid)
    assert len(adjustments) == 1, f"قيود التعديل: {len(adjustments)} (المتوقع 1)"
    lines = adjustments[0]["lines"]
    assert {l["account_code"] for l in lines} == {"5200", "2100"}
    assert sum(l["debit"] for l in lines) == \
        sum(l["credit"] for l in lines) == 300

    # لا فرق بعد التعديل ⇒ لا قيد ثانٍ
    r = client.put(f"/payroll/{pid}", headers=admin, json={"deduction": 300})
    assert r.status_code == 200, r.text
    assert len(_ledger_for(client, admin, "payroll_adjustment", pid)) == 1

    # الصرف يستعمل الصافي الأخير: مجموع مدين 2100 = استحقاق + تعديل
    r = client.post(f"/payroll/{pid}/pay", headers=admin)
    assert r.status_code == 200, r.text
    pays = _ledger_for(client, admin, "payroll_payment", pid)
    assert sum(l["debit"] for l in pays[0]["lines"]) == 5400

    posted_2100 = 0
    for kind in ("payroll", "payroll_adjustment"):
        for e in _ledger_for(client, admin, kind, pid):
            posted_2100 += sum(l["credit"] for l in e["lines"]
                               if l["account_code"] == "2100")
    spent_2100 = sum(l["debit"] for l in pays[0]["lines"]
                     if l["account_code"] == "2100")
    assert posted_2100 == spent_2100 == 5400, "ذمة الرواتب لم تُقفل مع التعديل"

    trial = client.get("/accounts/ledger/trial-balance", headers=admin)
    assert trial.status_code == 200, trial.text
    assert trial.json()["difference"] == 0
def test_deleting_invoice_or_patient_purges_their_journal_entries(client, admin):
    """حذف الفاتورة/المريض يزيل قيودهما المرتبطة — لا بقاء لمصدر مفقود.

    إن بقي القيد بعد حذف المصدر، فعند إعادة استخدام المعرّف (حذف آخر صف
    في SQLite ثم إنشاء فاتورة) يجده _posted_entry ويعدّ الفاتورة الجديدة
    مرحّلة سابقًا فلا تُرحَّل أبدًا — فيضيع إيراد بصمت. وهذا ما كان يسقط
    test_quotation_lifecycle_and_convert حين يسبقه حذف فواتير.
    """
    # 1) حذف الفاتورة مباشرة
    pid = _patient(client, admin)
    iid = _invoice(client, admin, pid, _uid())
    assert len(_ledger_for(client, admin, "patient_invoice", iid)) == 1
    assert client.delete(f"/invoices/{iid}", headers=admin).status_code == 204
    assert _ledger_for(client, admin, "patient_invoice", iid) == []

    # 2) حذف المريض يسقط فواتيره بالـcascade دون المرور بحذف الفاتورة
    pid2 = _patient(client, admin)
    iid2 = _invoice(client, admin, pid2, _uid())
    assert len(_ledger_for(client, admin, "patient_invoice", iid2)) == 1
    assert client.delete(f"/patients/{pid2}", headers=admin).status_code == 204
    assert _ledger_for(client, admin, "patient_invoice", iid2) == []
