"""اختبار تكامل للمحاور التشغيلية الجديدة وبوابة المريض.

يغطي دورة مريض/سرير، طلب خدمة، تنويم وإخراج، وحساب بوابة،
ويتحقق كذلك من عزل توكن المريض عن توكن الموظف.
"""
import uuid

import pytest


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


@pytest.mark.parametrize("service_type", [
    "care_sets", "dental", "physiotherapy", "emergency",
    "home_health", "wellness", "nutrition", "housekeeping",
])
def test_all_service_request_types_flow(client, admin, service_type):
    suffix = _suffix()
    patient_id = _make_patient(client, admin)
    response = client.post("/clinical/service-requests", headers=admin, json={
        "service_type": service_type,
        "patient_id": patient_id,
        "title": f"طلب {service_type} {suffix}",
        "priority": "normal",
    })
    assert response.status_code == 200, response.text
    item_id = response.json()["id"]
    assert response.json()["service_type"] == service_type

    completed = client.post(
        f"/clinical/service-requests/status/{item_id}",
        headers=admin,
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None


def test_support_and_governance_resources_flow(client, admin):
    suffix = _suffix()
    patient_id = _make_patient(client, admin)
    department = client.post("/departments/", headers=admin, json={
        "name": f"قسم الدعم {suffix}",
    })
    assert department.status_code == 200, department.text
    department_id = department.json()["id"]

    resources = [
        ("nursing-tasks", {
            "patient_id": patient_id, "department_id": department_id,
            "title": f"مهمة تمريض {suffix}", "shift": "night",
        }, "completed"),
        ("surgeries", {
            "patient_id": patient_id,
            "procedure_name": f"عملية {suffix}", "priority": "elective",
        }, "completed"),
        ("blood-bank", {
            "unit_number": f"BU-{suffix}", "donor_name": "متبرع تكاملي",
            "blood_group": "O+", "expiry_date": "2028-01-01T00:00:00",
        }, "issued"),
        ("maintenance", {
            "asset_name": f"جهاز {suffix}", "issue": "فحص دوري",
            "priority": "high",
        }, "completed"),
        ("sterilization", {
            "machine_name": f"Autoclave {suffix}", "load_description": "حزمة أدوات",
            "started_at": "2026-01-15T08:00:00",
        }, "passed"),
        ("safety-events", {
            "category": "incident", "severity": "low",
            "title": f"حادثة اختبار {suffix}", "patient_id": patient_id,
        }, "resolved"),
        ("budgets", {
            "fiscal_year": 2026, "department": "الدعم",
            "category": "صيانة", "allocated_amount": 5000,
        }, None),
        ("assets", {
            "asset_code": f"AST-{suffix}", "name": f"أصل {suffix}",
            "category": "medical_equipment", "purchase_cost": 12000,
        }, "active"),
    ]

    for path, payload, terminal_status in resources:
        created = client.post(f"/clinical/{path}", headers=admin, json=payload)
        assert created.status_code == 200, (path, created.text)

        # الميزانيات سجل مستقل بلا حالة تشغيلية.
        if terminal_status is None:
            assert created.json()["allocated_amount"] == payload["allocated_amount"]
            continue

        # الأصول لا تحتاج تغيير حالة لاختبار الإنشاء، والحالة الافتراضية active.
        if terminal_status == "active":
            assert created.json()["status"] == "active"
            continue

        item_id = created.json()["id"]
        changed = client.post(
            f"/clinical/{path}/status/{item_id}", headers=admin,
            json={"status": terminal_status},
        )
        assert changed.status_code == 200, (path, changed.text)
        assert changed.json()["status"] == terminal_status


def test_care_plan_execution_lifecycle(client, admin):
    suffix = _suffix()
    patient_id = _make_patient(client, admin)
    request = client.post("/clinical/service-requests", headers=admin, json={
        "service_type": "care_sets",
        "patient_id": patient_id,
        "title": f"طلب خطة رعاية {suffix}",
    })
    assert request.status_code == 200, request.text
    request_id = request.json()["id"]

    created = client.post("/clinical/care-plans", headers=admin, json={
        "patient_id": patient_id,
        "service_request_id": request_id,
        "title": f"خطة تعافٍ {suffix}",
        "goals": "استعادة الحركة والتحكم بالألم",
        "started_at": "2026-01-15T08:00:00",
        "items": [
            {"category": "mobility", "title": "تمارين الحركة"},
            {"category": "education", "title": "تعليمات الخروج"},
        ],
    })
    assert created.status_code == 201, created.text
    plan = created.json()
    plan_id = plan["id"]
    first_item, second_item = plan["items"][0]["id"], plan["items"][1]["id"]
    assert plan["completion_percentage"] == 0

    early = client.post(f"/clinical/care-plans/{plan_id}/complete", headers=admin)
    assert early.status_code == 409, early.text

    failed = client.post(f"/clinical/care-plan-items/{first_item}/execute", headers=admin, json={
        "executed_at": "2026-01-15T09:00:00", "outcome": "failed", "notes": "ألم أعلى من المتوقع",
    })
    assert failed.status_code == 201, failed.text
    duplicate = client.post(f"/clinical/care-plan-items/{first_item}/execute", headers=admin, json={
        "executed_at": "2026-01-15T09:00:00", "outcome": "completed",
    })
    assert duplicate.status_code == 409, duplicate.text

    retried = client.post(f"/clinical/care-plan-items/{first_item}/execute", headers=admin, json={
        "executed_at": "2026-01-15T10:00:00", "outcome": "completed", "notes": "تم التنفيذ",
    })
    assert retried.status_code == 201, retried.text
    terminal = client.post(f"/clinical/care-plan-items/{first_item}/execute", headers=admin, json={
        "executed_at": "2026-01-15T11:00:00", "outcome": "completed",
    })
    assert terminal.status_code == 409, terminal.text

    second = client.post(f"/clinical/care-plan-items/{second_item}/execute", headers=admin, json={
        "executed_at": "2026-01-15T12:00:00", "outcome": "completed",
    })
    assert second.status_code == 201, second.text
    completed = client.post(f"/clinical/care-plans/{plan_id}/complete", headers=admin)
    assert completed.status_code == 200, completed.text
    assert completed.json()["completion_percentage"] == 100
    assert completed.json()["status"] == "completed"

    cancelled_plan = client.post("/clinical/care-plans", headers=admin, json={
        "patient_id": patient_id,
        "title": f"خطة ملغاة {suffix}",
        "goals": "اختبار الإلغاء",
        "started_at": "2026-01-15T08:00:00",
        "items": [{"category": "nursing", "title": "فحص غير منفذ"}],
    })
    assert cancelled_plan.status_code == 201, cancelled_plan.text
    cancelled_id = cancelled_plan.json()["id"]
    cancelled_item = cancelled_plan.json()["items"][0]["id"]
    cancelled = client.post(f"/clinical/care-plans/{cancelled_id}/cancel", headers=admin)
    assert cancelled.status_code == 200, cancelled.text
    blocked = client.post(f"/clinical/care-plan-items/{cancelled_item}/execute", headers=admin, json={
        "executed_at": "2026-01-15T13:00:00", "outcome": "completed",
    })
    assert blocked.status_code == 409, blocked.text


def test_dental_treatment_plan_lifecycle(client, admin):
    suffix = _suffix()
    patient_id = _make_patient(client, admin)

    chart = client.put(f"/dental/charts/{patient_id}", headers=admin, json={
        "allergies": "بنسلين",
        "medical_conditions": "لا يوجد",
        "last_exam_at": "2026-02-01T09:00:00",
        "notes": "فحص أسنان دوري",
    })
    assert chart.status_code == 200, chart.text
    assert chart.json()["allergies"] == "بنسلين"

    service = client.post("/clinical/service-requests", headers=admin, json={
        "service_type": "dental",
        "patient_id": patient_id,
        "title": f"طلب علاج أسنان {suffix}",
        "details": "ألم السن رقم 16",
    })
    assert service.status_code == 200, service.text

    plan_response = client.post("/dental/plans", headers=admin, json={
        "patient_id": patient_id,
        "service_request_id": service.json()["id"],
        "title": f"خطة علاج سن 16 {suffix}",
        "chief_complaint": "ألم و تسوس",
        "diagnosis": "تسوس عميق",
        "started_at": "2026-02-01T10:00:00",
    })
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]
    assert plan_response.json()["completion_percentage"] == 0

    first = client.post(f"/dental/plans/{plan_id}/procedures", headers=admin, json={
        "tooth_number": 16,
        "surfaces": "MO",
        "procedure_type": "filling",
        "scheduled_at": "2026-02-01T11:00:00",
    })
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    failed = client.post(f"/dental/procedures/{first_id}/execute", headers=admin, json={
        "performed_at": "2026-02-01T11:05:00",
        "outcome": "failed",
        "notes": "فشل أثناء التحضير",
        "cost": 25.556,
    })
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["cost"] == 25.56

    duplicate = client.post(f"/dental/procedures/{first_id}/execute", headers=admin, json={
        "performed_at": "2026-02-01T11:05:00",
        "outcome": "failed",
    })
    assert duplicate.status_code == 409, duplicate.text

    blocked = client.post(f"/dental/plans/{plan_id}/complete", headers=admin)
    assert blocked.status_code == 409, blocked.text

    second = client.post(f"/dental/plans/{plan_id}/procedures", headers=admin, json={
        "tooth_number": 26,
        "procedure_type": "cleaning",
        "scheduled_at": "2026-02-01T12:00:00",
    })
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    retried = client.post(f"/dental/procedures/{first_id}/execute", headers=admin, json={
        "performed_at": "2026-02-01T12:30:00",
        "outcome": "completed",
        "notes": "تمت المعالجة بنجاح",
        "cost": 50,
    })
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "completed"

    cleaned = client.post(f"/dental/procedures/{second_id}/execute", headers=admin, json={
        "performed_at": "2026-02-01T13:00:00",
        "outcome": "completed",
        "cost": 30,
    })
    assert cleaned.status_code == 200, cleaned.text

    completed = client.post(f"/dental/plans/{plan_id}/complete", headers=admin)
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["completion_percentage"] == 100
    assert completed.json()["total_cost"] == 80


def test_service_units_complete_lifecycle(client, admin):
    patient_id = _make_patient(client, admin)
    resources = [
        ("physiotherapy", {
            "patient_id": patient_id, "title": "خطة علاج طبيعي",
            "assessment": "تقييم الحركة", "notes": "ملاحظة أولية",
        }, {"plan": "جلسات أسبوعية"}, "in_treatment", "completed"),
        ("nutrition", {
            "patient_id": patient_id, "title": "خطة غذائية",
            "dietary_plan": "نظام متوازن", "notes": "ملاحظة أولية",
        }, {"meal_plan": "ثلاث وجبات"}, "active", "completed"),
        ("emergency", {
            "patient_id": patient_id, "complaint": "ألم شديد",
            "triage_level": "urgent", "arrival_at": "2026-03-01T10:00:00",
            "notes": "ملاحظة أولية",
        }, {"disposition": "بعد الملاحظة"}, "under_treatment", "closed"),
        ("home-health", {
            "patient_id": patient_id, "coordinator": "منسق الرعاية",
            "care_plan": "زيارة منزلية", "notes": "ملاحظة أولية",
        }, {"visits_completed": 2}, "active", "completed"),
        ("wellness", {
            "patient_id": patient_id, "program_name": "برنامج حركة",
            "goal": "تحسين النشاط", "progress_notes": "ملاحظة أولية",
        }, {"progress_notes": "تحسن تدريجي"}, "active", "completed"),
        ("housekeeping", {
            "room_number": "101", "task_type": "cleaning",
            "priority": "normal", "notes": "ملاحظة أولية",
        }, {"assigned_to": "فريق النظافة"}, "in_progress", "completed"),
    ]

    created_ids = {}
    terminal_statuses = {}
    for path, create_payload, update_payload, active_status, terminal_status in resources:
        prefix = f"/service-units/{path}"
        created = client.post(prefix, headers=admin, json=create_payload)
        assert created.status_code == 201, (path, created.text)
        case_id = created.json()["id"]
        created_ids[path] = case_id
        terminal_statuses[path] = terminal_status

        fetched = client.get(f"{prefix}/{case_id}", headers=admin)
        assert fetched.status_code == 200, (path, fetched.text)
        assert fetched.json()["id"] == case_id

        updated = client.put(f"{prefix}/{case_id}", headers=admin, json=update_payload)
        assert updated.status_code == 200, (path, updated.text)

        activated = client.post(
            f"{prefix}/{case_id}/status", headers=admin,
            json={"status": active_status},
        )
        assert activated.status_code == 200, (path, activated.text)
        assert activated.json()["status"] == active_status

        invalid = client.post(
            f"{prefix}/{case_id}/status", headers=admin,
            json={"status": "unknown"},
        )
        assert invalid.status_code == 422, (path, invalid.text)

        closed = client.post(
            f"{prefix}/{case_id}/status", headers=admin,
            json={"status": terminal_status},
        )
        assert closed.status_code == 200, (path, closed.text)
        assert closed.json()["status"] == terminal_status
        closed_at_key = "closed_at" if path == "emergency" else "completed_at"
        assert closed.json()[closed_at_key] is not None

        repeated = client.post(
            f"{prefix}/{case_id}/status", headers=admin,
            json={"status": terminal_status},
        )
        assert repeated.status_code == 200, (path, repeated.text)
        assert repeated.json()[closed_at_key] == closed.json()[closed_at_key]

        reopened = client.post(
            f"{prefix}/{case_id}/status", headers=admin,
            json={"status": active_status},
        )
        assert reopened.status_code == 409, (path, reopened.text)
        blocked_update = client.put(
            f"{prefix}/{case_id}", headers=admin,
            json={"progress_notes": "محاولة تعديل"} if path == "wellness"
            else {"notes": "محاولة تعديل"},
        )
        assert blocked_update.status_code == 409, (path, blocked_update.text)

    for path in created_ids:
        expected_status = terminal_statuses[path]
        query = f"?status={expected_status}"
        if path != "housekeeping":
            query += f"&patient_id={patient_id}"
        listed = client.get(f"/service-units/{path}{query}", headers=admin)
        assert listed.status_code == 200, (path, listed.text)
        assert any(item["id"] == created_ids[path] for item in listed.json())
        assert all(item["status"] == expected_status for item in listed.json())
