# -*- coding: utf-8 -*-
"""إدارة العيادات.

الاختبارات هنا تثبت قرار «عدم التكرار» صراحةً: خدمات العيادة وجداول
دوامها هي نفسها جداول مركز الأقسام (DepartmentService / DepartmentSchedule)،
فأي كتابة من شاشة العيادات يجب أن تظهر في مركز الأقسام والعكس.
"""
import uuid

from conftest import login

from app.models import DepartmentSchedule, DepartmentService  # noqa: F401


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _dept_id(client, admin) -> int:
    rows = client.get("/departments/", headers=admin).json()
    if rows:
        return rows[0]["id"]
    r = client.post("/departments/", headers=admin, json={"name": f"قسم عيادات {uid()}"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _create(client, admin, **over):
    body = {"code": f"CL{uid()}", "name": f"عيادة {uid()}"}
    body.update(over)
    r = client.post("/clinics/", headers=admin, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ===== سجل العيادات =====
def test_clinic_crud_and_validation(client, admin):
    """إنشاء عيادة، ثم قراءة وتعديل وحذفها، مع رفض الكود المكرر والحقول الناقصة."""
    clinic = _create(client, admin, specialty="باطنية", location="مبنى أ",
                     consultation_fee=150, default_duration=20)
    assert clinic["status"] == "active"
    assert clinic["services_count"] == 0

    dup = client.post("/clinics/", headers=admin,
                      json={"code": clinic["code"], "name": "مكررة"})
    assert dup.status_code == 409, "كود العيادة المكرر مرفوض"

    short = client.post("/clinics/", headers=admin,
                        json={"code": f"CL{uid()}", "name": "ا"})
    assert short.status_code == 422, "الاسم القصير مرفوض"

    fetched = client.get(f"/clinics/{clinic['id']}", headers=admin)
    assert fetched.status_code == 200 and fetched.json()["specialty"] == "باطنية"

    upd = client.put(f"/clinics/{clinic['id']}", headers=admin,
                     json={"status": "closed", "location": "مبنى ب"})
    assert upd.status_code == 200
    assert upd.json()["status"] == "closed" and upd.json()["location"] == "مبنى ب"
    assert upd.json()["specialty"] == "باطنية", "التعديل الجزئي لا يمسّ باقي الحقول"

    assert client.delete(f"/clinics/{clinic['id']}", headers=admin).status_code == 204
    assert client.get(f"/clinics/{clinic['id']}", headers=admin).status_code == 404


def test_clinic_listing_filters_and_search(client, admin):
    """البحث بالاسم/الرمز، والتصفية بالتخصص والحالة، وقائمة التخصصات."""
    tag = uid()
    clinic = _create(client, admin, specialty=f"تخصص-{tag}", name=f"عيادة {tag}")
    try:
        assert any(c["id"] == clinic["id"]
                   for c in client.get("/clinics/", headers=admin).json())
        assert client.get(f"/clinics/?q={tag}", headers=admin).json()[0]["id"] == clinic["id"]
        assert client.get(f"/clinics/?specialty=تخصص-{tag}",
                          headers=admin).json()[0]["id"] == clinic["id"]
        assert client.get("/clinics/?status=closed", headers=admin).json() == []
        assert f"تخصص-{tag}" in client.get("/clinics/specialties", headers=admin).json()
    finally:
        client.delete(f"/clinics/{clinic['id']}", headers=admin)


def test_clinic_reads_department_catalog_without_copying(client, admin):
    """العيادة تقرأ كتالوج قسمها لا جدولًا موازيًا، والتعديل ينعكس على المركز."""
    dept = _dept_id(client, admin)
    clinic = _create(client, admin, department_id=dept)
    try:
        assert clinic["department_id"] == dept
        assert clinic["department_name"], "اسم القسم المرتبط يظهر"
        svc = client.post(f"/clinics/{clinic['id']}/services", headers=admin,
                          json={"code": f"CONS{uid()}", "name": "كشفية الاختبار",
                                "price": 150, "doctor_share_pct": 40,
                                "insurance_pct": 60})
        assert svc.status_code == 201, svc.text
        assert svc.json()["department_id"] == dept, "الخدمة تُكتب في جدول القسم"

        hub = client.get(f"/department-hub/{dept}/services", headers=admin).json()
        assert any(s["name"] == "كشفية الاختبار" for s in hub), "مرئية في مركز الأقسام"

        sid = svc.json()["id"]
        upd = client.put(f"/clinics/{clinic['id']}/services/{sid}", headers=admin,
                         json={"code": f"CONS{uid()}", "name": "كشفية الاختبار",
                               "price": 175})
        assert upd.status_code == 200 and upd.json()["price"] == 175
        hub2 = client.get(f"/department-hub/{dept}/services", headers=admin).json()
        assert next(s for s in hub2 if s["id"] == sid)["price"] == 175
    finally:
        client.delete(f"/clinics/{clinic['id']}", headers=admin)



def test_clinic_schedule_shares_department_table(client, admin):
    """الورديات في جدول القسم نفسه، والسعة الأسبوعية من سعات الورديات."""
    dept = _dept_id(client, admin)
    clinic = _create(client, admin, department_id=dept)
    try:
        first = client.post(f"/clinics/{clinic['id']}/schedule", headers=admin,
                            json={"day_of_week": 0, "session": "morning",
                                  "open_time": "09:00", "close_time": "13:00",
                                  "room_name": f"عيادة {uid()}", "max_patients": 12})
        assert first.status_code == 201, first.text
        assert first.json()["day_name"] == "الأحد"
        assert first.json()["session_name"] == "صباحية"
        assert first.json()["department_id"] == dept

        hub = client.get(f"/department-hub/{dept}/schedule", headers=admin).json()
        assert any(r["room_name"] == first.json()["room_name"] for r in hub), \
            "الوردية مرئية في مركز الأقسام"

        clash = client.post(f"/clinics/{clinic['id']}/schedule", headers=admin,
                            json={"day_of_week": 0, "session": "morning",
                                  "open_time": "10:00", "close_time": "14:00"})
        assert clash.status_code == 409, "تكرار اليوم+الفترة مرفوض"

        rev = client.post(f"/clinics/{clinic['id']}/schedule", headers=admin,
                          json={"day_of_week": 1, "session": "morning",
                                "open_time": "15:00", "close_time": "10:00"})
        assert rev.status_code == 400, "نهاية الدوام قبل بدايته مرفوضة"

        assert client.post(f"/clinics/{clinic['id']}/schedule", headers=admin, json={
            "day_of_week": 9, "session": "morning",
            "open_time": "09:00", "close_time": "12:00"}).status_code == 422
        assert client.post(f"/clinics/{clinic['id']}/schedule", headers=admin, json={
            "day_of_week": 1, "session": "morning",
            "open_time": "9:00", "close_time": "12:00"}).status_code == 422

        detail = client.get(f"/clinics/{clinic['id']}", headers=admin).json()
        assert detail["schedule_count"] == 1
        assert detail["weekly_capacity"] == 12, "السعة الأسبوعية من سعة الوردية"
    finally:
        client.delete(f"/clinics/{clinic['id']}", headers=admin)


def test_unlinked_clinic_refuses_operational_writes(client, admin):
    """بلا قسم مرتبط: تُبلّغ بوضوح ولا تُنشأ جداول موازية صامتة."""
    clinic = _create(client, admin)
    try:
        svc = client.post(f"/clinics/{clinic['id']}/services", headers=admin,
                          json={"name": "كشفية", "price": 100})
        assert svc.status_code == 400
        assert "قسم" in svc.json()["detail"], svc.text

        slot = client.post(f"/clinics/{clinic['id']}/schedule", headers=admin,
                           json={"day_of_week": 0, "session": "morning",
                                 "open_time": "09:00", "close_time": "12:00"})
        assert slot.status_code == 400 and "قسم" in slot.json()["detail"]

        assert client.get(f"/clinics/{clinic['id']}/services", headers=admin).json() == []
        assert client.get(f"/clinics/{clinic['id']}/schedule", headers=admin).json() == []
    finally:
        client.delete(f"/clinics/{clinic['id']}", headers=admin)


def test_department_cannot_serve_two_clinics(client, admin):
    """قسم واحد لا يخدم عيادتين — منع الازدواج التشغيلي."""
    dept = _dept_id(client, admin)
    first = _create(client, admin, department_id=dept)
    second = _create(client, admin)
    try:
        assert client.put(f"/clinics/{second['id']}", headers=admin,
                          json={"department_id": dept}).status_code == 409, \
            "الربط بقسم مرتبط بعيادة أخرى مرفوض"
        assert client.put(f"/clinics/{second['id']}", headers=admin,
                          json={"department_id": None}).status_code == 200
    finally:
        client.delete(f"/clinics/{first['id']}", headers=admin)
        client.delete(f"/clinics/{second['id']}", headers=admin)


def test_no_parallel_clinic_tables():
    """حارس التكرار: لا جداول خدمات/جداول خاصة بالعيادات.

    إن أُعيد يومًا ما إنشاء `clinic_services` أو `clinic_schedules` فذلك
    ازدواج مع مركز الأقسام، وهذا الاختبار يفشل فورًا.
    """
    from app.database import engine
    from sqlalchemy import inspect
    tables = set(inspect(engine).get_table_names())
    assert "clinics" in tables, "جدول سجل العيادات موجود"
    for banned in ("clinic_services", "clinic_schedules"):
        assert banned not in tables, f"جدول موازٍ مكرّر لمركز الأقسام: {banned}"
    # والمصدر الواحد قائم: جدولا القسم يحملان بيانات العيادة نفسها
    assert "department_services" in tables
    assert "department_schedules" in tables


def test_clinics_summary_and_permissions(client, admin):
    """الملخّص يعكس الأعداد، والقراءة متاحة، أما الكتابة فمدير فقط."""
    dept = _dept_id(client, admin)
    clinic = _create(client, admin, department_id=dept, consultation_fee=120)
    try:
        client.post(f"/clinics/{clinic['id']}/schedule", headers=admin,
                    json={"day_of_week": 1, "session": "morning", "open_time": "09:00",
                          "close_time": "12:00", "max_patients": 7})
        summary = client.get("/clinics/summary", headers=admin).json()
        assert summary["clinics"] >= 1 and summary["active"] >= 1
        assert summary["weekly_capacity"] >= 7
        assert summary["consultation_fees_total"] >= 120
        assert summary["unlinked"] >= 0
    finally:
        client.delete(f"/clinics/{clinic['id']}", headers=admin)

    assert client.get("/clinics/").status_code == 401
    assert client.post("/clinics/", json={"code": "X", "name": "س"}).status_code == 401

    uname = f"clinic_denied_{uid()}"
    reg = client.post("/auth/register", json={
        "username": uname, "password": "Test@12345", "full_name": "مستخدم عيادة",
        "email": f"{uname}@hospital-demo.com"})
    assert reg.status_code in (200, 201), reg.text
    staff = login(client, uname, "Test@12345")
    assert client.get("/clinics/", headers=staff).status_code == 200, "القراءة للجميع"
    forbidden = client.post("/clinics/", headers=staff,
                            json={"code": f"CL{uid()}", "name": "ممنوعة"})
    assert forbidden.status_code == 403, "غير المدير لا ينشئ عيادة"
