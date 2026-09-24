"""اختبار تكامل للمحاور التشغيلية الجديدة وبوابة المريض.

يغطي دورة مريض/سرير، طلب خدمة، تنويم وإخراج، وحساب بوابة،
ويتحقق كذلك من عزل توكن المريض عن توكن الموظف.
"""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _make_patient(client, admin):
    suffix = _suffix()
    response = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض تكامل {suffix}",
        "date_of_birth": "1990-01-01",
        "gender": "ذكر",
        "phone": f"050{suffix[-7:]}",
        "email": f"advanced_{suffix}@test.com",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_advanced_clinical_and_patient_portal_flow(client, admin):
    suffix = _suffix()

    department = client.post("/departments/", headers=admin, json={
        "name": f"قسم التكامل {suffix}",
        "description": "قسم اختبار دورة المحاور المتقدمة",
    })
    assert department.status_code == 200, department.text
    department_id = department.json()["id"]

    patient_id = _make_patient(client, admin)
    bed = client.post("/beds/", headers=admin, json={
        "bed_number": f"BED-{suffix}",
        "department_id": department_id,
    })
    assert bed.status_code == 200, bed.text
    bed_id = bed.json()["id"]
    assert bed.json()["status"] == "available"

    service = client.post("/clinical/service-requests", headers=admin, json={
        "service_type": "physiotherapy",
        "patient_id": patient_id,
        "title": "جلسة علاج طبيعي تكاملية",
        "details": "اختبار إنشاء الطلب ودورة حالته",
        "priority": "high",
    })
    assert service.status_code == 200, service.text
    service_id = service.json()["id"]
    assert service.json()["status"] == "pending"

    service_status = client.post(
        f"/clinical/service-requests/status/{service_id}",
        headers=admin,
        json={"status": "in_progress"},
    )
    assert service_status.status_code == 200, service_status.text
    assert service_status.json()["status"] == "in_progress"

    admission = client.post("/clinical/admissions", headers=admin, json={
        "patient_id": patient_id,
        "bed_id": bed_id,
        "department_id": department_id,
        "admission_date": "2026-01-15T08:00:00",
        "diagnosis": "دخول للاختبار",
    })
    assert admission.status_code == 200, admission.text
    admission_id = admission.json()["id"]
    assert admission.json()["status"] == "admitted"

    occupied_bed = client.get(f"/beds/{bed_id}", headers=admin)
    assert occupied_bed.status_code == 200, occupied_bed.text
    assert occupied_bed.json()["status"] == "occupied"

    discharge = client.post(
        f"/clinical/admissions/status/{admission_id}",
        headers=admin,
        json={"status": "discharged"},
    )
    assert discharge.status_code == 200, discharge.text
    assert discharge.json()["status"] == "discharged"
    assert discharge.json()["discharge_date"] is not None

    released_bed = client.get(f"/beds/{bed_id}", headers=admin)
    assert released_bed.status_code == 200, released_bed.text
    assert released_bed.json()["status"] == "available"
    assert released_bed.json()["patient_id"] is None

    portal_username = f"portal_{suffix}"
    portal_password = "PortalPass123!"
    portal_account = client.post("/clinical/patient-portal-accounts", headers=admin, json={
        "patient_id": patient_id,
        "username": portal_username,
        "password": portal_password,
    })
    assert portal_account.status_code == 200, portal_account.text
    assert "password" not in portal_account.json()
    assert "hashed_password" not in portal_account.json()

    portal_login = client.post("/patient-portal/login", json={
        "username": portal_username,
        "password": portal_password,
    })
    assert portal_login.status_code == 200, portal_login.text
    assert portal_login.json()["patient"]["id"] == patient_id
    portal_headers = {"Authorization": f"Bearer {portal_login.json()['access_token']}"}

    portal_profile = client.get("/patient-portal/me", headers=portal_headers)
    assert portal_profile.status_code == 200, portal_profile.text
    profile = portal_profile.json()
    assert profile["patient"]["id"] == patient_id
    assert any(item["id"] == service_id for item in profile["service_requests"])
    assert any(item["id"] == admission_id for item in profile["admissions"])

    # توكن المريض لا يُقبل في مسارات الموظفين.
    employee_route = client.get("/clinical/service-requests", headers=portal_headers)
    assert employee_route.status_code == 401

    # توكن الموظف لا يُقبل في بوابة المريض.
    patient_route = client.get("/patient-portal/me", headers=admin)
    assert patient_route.status_code == 401

    # تسجيل دخول خاطئ لا يمنح جلسة بوابة.
    bad_login = client.post("/patient-portal/login", json={
        "username": portal_username,
        "password": "WrongPassword123!",
    })
    assert bad_login.status_code == 401
