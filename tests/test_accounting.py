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

    # لا يُسمح بالتحصيل قبل قيد ترحيل الفاتورة.
    early_payment = client.post(
        f"/accounts/ledger/invoices/{invoice_id}/payments",
        headers=admin,
        json={"amount": 25, "method": "insurance", "paid_at": "2026-01-15T10:00:00"},
    )
    assert early_payment.status_code == 409, early_payment.text

    posted = client.post(f"/accounts/ledger/invoices/{invoice_id}/post", headers=admin)
    assert posted.status_code == 200, posted.text
    assert sum(line["debit"] for line in posted.json()["lines"]) == \
        sum(line["credit"] for line in posted.json()["lines"])

    duplicate_post = client.post(f"/accounts/ledger/invoices/{invoice_id}/post", headers=admin)
    assert duplicate_post.status_code == 409, duplicate_post.text

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
