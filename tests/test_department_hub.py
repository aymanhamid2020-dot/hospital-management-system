"""مركز الأقسام — الأقسام الستّة: الهيكل · الكادر · الغرف والأسرّة · الخدمات ·
الجداول · المؤشرات، مع الصلاحيات وقواعد التحقق.
"""
import uuid
from datetime import datetime, timedelta

from conftest import login


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _dept(client, admin, name=None, **extra):
    body = {"name": name or f"قسم {uid()}", "floor": "الأرضي"}
    body.update(extra)
    r = client.post("/departments/", headers=admin, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _doctor(client, admin, dept_id, name=None):
    r = client.post("/doctors/", headers=admin, json={
        "full_name": name or f"د. {uid()}", "specialty": "باطنية",
        "license_number": f"LC{uid()}", "phone": f"05{uuid.uuid4().hex[:8]}",
        "email": f"d{uuid.uuid4().hex[:8]}@test.com", "department_id": dept_id})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _staff(client, admin, name=None, position="ممرض"):
    r = client.post("/staff/", headers=admin, json={
        "full_name": name or f"أ. {uid()}", "position": position,
        "phone": f"05{uuid.uuid4().hex[:8]}",
        "email": f"s{uuid.uuid4().hex[:8]}@test.com",
        "hire_date": "2024-01-15T00:00:00"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض {uid()}", "date_of_birth": "1990-03-03",
        "gender": "ذكر", "phone": f"055{uuid.uuid4().hex[:6]}",
        "email": f"p{uuid.uuid4().hex[:8]}@test.com"})
    assert r.status_code == 200, r.text
    return r.json()


# ===== 1) دليل الأقسام والهيكل =====
def test_directory_tree_and_structure(client, admin):
    """شجرة الأقسام: الجذر + الوحدات الفرعية + النوع، وتعديل الهيكل بقواعده."""
    parent = _dept(client, admin, dept_type="clinical", monthly_operating_cost=50000)
    child = _dept(client, admin, dept_type="diagnostic", parent_id=parent["id"])

    tree = client.get("/department-hub/directory", headers=admin).json()
    node = next(n for n in tree if n["id"] == parent["id"])
    assert node["dept_type"] == "clinical" and node["dept_type_ar"] == "طبي/عيادي"
    assert [c["id"] for c in node["children"]] == [child["id"]]
    assert node["children"][0]["depth"] == 1
    # القسم الفرعي لا يظهر كجذر مستقل
    assert not [n for n in tree if n["id"] == child["id"]]

    # تعديل: نوع + تكلفة + تعطيل
    r = client.put(f"/department-hub/{parent['id']}/structure", headers=admin, json={
        "dept_type": "supportive", "monthly_operating_cost": 75000,
        "is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["dept_type"] == "supportive"
    # القسم المعطّل يختفي من الدليل ما لم يُطلب غير الفعّال
    assert not [n for n in client.get("/department-hub/directory", headers=admin).json()
                if n["id"] == parent["id"]]
    assert [n for n in client.get(
        "/department-hub/directory?include_inactive=true", headers=admin).json()
        if n["id"] == parent["id"]]

    # قواعد: نوع مجهول 400 · قسم أبقي نفسه 400 · دورة_ab 400
    assert client.put(f"/department-hub/{parent['id']}/structure", headers=admin,
                      json={"dept_type": "wrong"}).status_code == 400
    assert client.put(f"/department-hub/{parent['id']}/structure", headers=admin,
                      json={"parent_id": parent["id"]}).status_code == 400
    client.put(f"/department-hub/{child['id']}/structure", headers=admin,
               json={"parent_id": parent["id"]})
    assert client.put(f"/department-hub/{parent['id']}/structure", headers=admin,
                      json={"parent_id": child["id"]}).status_code == 400
    assert client.put("/department-hub/999999/structure", headers=admin,
                      json={"dept_type": "clinical"}).status_code == 404


# ===== 2) الأطباء والكادر =====
def test_team_head_and_support(client, admin):
    """رئيس القسم + الأطباء المنتسبون + توزيع الكادر المساند (بلا تكرار)."""
    dept = _dept(client, admin)
    doc = _doctor(client, admin, dept["id"])
    nurse = _staff(client, admin, position="ممرض")

    team = client.get(f"/department-hub/{dept['id']}/team", headers=admin).json()
    assert team["counts"] == {"doctors": 1, "support": 0}
    assert team["doctors"][0]["name"] == doc["full_name"]
    assert team["head"]["doctor_id"] is None

    r = client.put(f"/department-hub/{dept['id']}/head", headers=admin,
                   json={"head_doctor_id": doc["id"]})
    assert r.status_code == 200 and r.json()["head_doctor_id"] == doc["id"]
    team = client.get(f"/department-hub/{dept['id']}/team", headers=admin).json()
    assert team["head"]["name"] == doc["full_name"]
    # رئيس قسم مجهول ⇒ 404
    assert client.put(f"/department-hub/{dept['id']}/head", headers=admin,
                      json={"head_doctor_id": 999999}).status_code == 404

    sup = client.post(f"/department-hub/{dept['id']}/support", headers=admin,
                      json={"staff_id": nurse["id"], "role_in_dept": "ممرض",
                            "is_head": True})
    assert sup.status_code == 201, sup.text
    assert sup.json()["staff_name"] == nurse["full_name"] and sup.json()["is_head"]
    # تكرار التوزيع 409 · موظف مجهول 404
    assert client.post(f"/department-hub/{dept['id']}/support", headers=admin,
                      json={"staff_id": nurse["id"]}).status_code == 409
    assert client.post(f"/department-hub/{dept['id']}/support", headers=admin,
                      json={"staff_id": 999999}).status_code == 404
    # إلغاء التوزيع
    assert client.delete(f"/department-hub/{dept['id']}/support/{sup.json()['id']}",
                         headers=admin).status_code == 204
    assert client.get(f"/department-hub/{dept['id']}/team",
                      headers=admin).json()["counts"]["support"] == 0


# ===== 3) الغرف والأسرّة =====
def test_rooms_beds_and_bookings(client, admin):
    """الغرف بفئاتها · توزيع الأسرة عليها (بسعة) · حجز الغرفة بلا تداخل."""
    dept = _dept(client, admin)
    r = client.post(f"/department-hub/{dept['id']}/rooms", headers=admin, json={
        "name": "جناح الملك VIP", "room_number": "R-101", "category": "royal",
        "capacity": 2})
    assert r.status_code == 201, r.text
    room = r.json()
    assert room["category"] == "royal" and room["capacity"] == 2

    # فئة مجهولة ⇒ 400
    assert client.post(f"/department-hub/{dept['id']}/rooms", headers=admin, json={
        "name": "غرفة خطأ", "category": "gold"}).status_code == 400

    bed1 = client.post("/beds/", headers=admin,
                       json={"bed_number": "B1", "department_id": dept["id"]})
    bed2 = client.post("/beds/", headers=admin,
                       json={"bed_number": "B2", "department_id": dept["id"]})
    assert bed1.status_code in (200, 201), bed1.text
    bed2_id = bed2.json()["id"]

    a = client.put(f"/department-hub/{dept['id']}/beds/{bed1.json()['id']}/room",
                   headers=admin, params={"room_id": room["id"]})
    assert a.status_code == 200 and a.json()["room_id"] == room["id"]
    assert client.put(f"/department-hub/{dept['id']}/beds/{bed2_id}/room",
                      headers=admin, params={"room_id": room["id"]}).status_code == 200
    # السعة اكتملت ⇒ 400
    bed3 = client.post("/beds/", headers=admin,
                       json={"bed_number": "B3", "department_id": dept["id"]})
    assert client.put(f"/department-hub/{dept['id']}/beds/{bed3.json()['id']}/room",
                      headers=admin, params={"room_id": room["id"]}).status_code == 400
    # غرفة مجهولة ⇒ 404
    assert client.put(f"/department-hub/{dept['id']}/beds/{bed1.json()['id']}/room",
                      headers=admin, params={"room_id": 999999}).status_code == 404

    beds = client.get(f"/department-hub/{dept['id']}/beds", headers=admin).json()
    assert len(beds) == 3
    assert next(b for b in beds if b["id"] == bed1.json()["id"])["room_name"] == room["name"]
    rooms = client.get(f"/department-hub/{dept['id']}/rooms", headers=admin).json()
    assert rooms[0]["beds_count"] == 2

    # حجز الغرفة: نجاح ثم تداخل 409 ثم نهاية قبل البداية 400
    start = (datetime.utcnow() + timedelta(days=2)).replace(microsecond=0)
    end = start + timedelta(hours=2)
    bk = client.post(f"/department-hub/{dept['id']}/rooms/{room['id']}/bookings",
                     headers=admin, json={"starts_at": start.isoformat(),
                                          "ends_at": end.isoformat(),
                                          "purpose": "منظار هضمي"})
    assert bk.status_code == 201, bk.text
    assert bk.json()["room_name"] == room["name"]
    assert client.post(f"/department-hub/{dept['id']}/rooms/{room['id']}/bookings",
                       headers=admin, json={
                           "starts_at": (start + timedelta(minutes=30)).isoformat(),
                           "ends_at": (end + timedelta(minutes=30)).isoformat(),
                       }).status_code == 409
    assert client.post(f"/department-hub/{dept['id']}/rooms/{room['id']}/bookings",
                       headers=admin, json={"starts_at": end.isoformat(),
                                            "ends_at": start.isoformat()}
                       ).status_code == 400
    assert len(client.get(f"/department-hub/{dept['id']}/bookings",
                          headers=admin).json()) == 1

    # حذف الغرفة يفصل الأسرة ولا يحذفها
    assert client.delete(f"/department-hub/{dept['id']}/rooms/{room['id']}",
                         headers=admin).status_code == 204
    assert not [b for b in client.get(f"/department-hub/{dept['id']}/beds",
                                      headers=admin).json() if b["room_id"]]


# ===== 4) الخدمات والأسعار =====
def test_services_catalog_and_shares(client, admin):
    """كتالوج الخدمات: السعر + حصة الطبيب + تغطية التأمين مع تحقّق المجموع."""
    dept = _dept(client, admin)
    r = client.post(f"/department-hub/{dept['id']}/services", headers=admin, json={
        "code": "SRV-1", "name": "منظار هضمي", "price": 1000,
        "doctor_share_pct": 30, "insurance_pct": 70,
        "procedure_note": "صيام 8 ساعات"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["doctor_amount"] == 300.0 and body["insurance_amount"] == 700.0
    assert body["patient_amount"] == 300.0
    assert client.get(f"/department-hub/{dept['id']}/services",
                      headers=admin).json()[0]["name"] == "منظار هضمي"

    # مجموع النسب > 100 ⇒ 400 ، ونسبة خارج 0–100 ⇒ 422
    assert client.post(f"/department-hub/{dept['id']}/services", headers=admin, json={
        "name": "خدمة خاطئة", "price": 100,
        "doctor_share_pct": 60, "insurance_pct": 60}).status_code == 400
    assert client.post(f"/department-hub/{dept['id']}/services", headers=admin, json={
        "name": "نسبة خاطئة", "price": 100,
        "doctor_share_pct": 150}).status_code == 422

    upd = client.put(f"/department-hub/{dept['id']}/services/{body['id']}",
                     headers=admin, json={"name": "منظار معدّل", "price": 1200,
                                          "doctor_share_pct": 40,
                                          "insurance_pct": 50})
    assert upd.status_code == 200, upd.text
    assert upd.json()["price"] == 1200 and upd.json()["doctor_amount"] == 480.0
    assert client.delete(f"/department-hub/{dept['id']}/services/{body['id']}",
                         headers=admin).status_code == 204
    assert client.get(f"/department-hub/{dept['id']}/services",
                      headers=admin).json() == []


# ===== 5) الجداول والمواعيد =====
def test_clinic_schedule(client, admin):
    """جدول العيادة: وردية صباحية ومسائية، مع منع التكرار والوقت غير الصحيح."""
    dept = _dept(client, admin)
    r = client.post(f"/department-hub/{dept['id']}/schedule", headers=admin, json={
        "day_of_week": 0, "session": "morning", "open_time": "08:00",
        "close_time": "14:00", "room_name": "عيادة 1"})
    assert r.status_code == 201, r.text
    assert r.json()["day_of_week"] == 0 and r.json()["session"] == "morning"

    # نفس اليوم + نفس الفترة ⇒ 409 (ويُسمح بالمسائي)
    assert client.post(f"/department-hub/{dept['id']}/schedule", headers=admin, json={
        "day_of_week": 0, "session": "morning",
        "open_time": "09:00", "close_time": "12:00"}).status_code == 409
    assert client.post(f"/department-hub/{dept['id']}/schedule", headers=admin, json={
        "day_of_week": 0, "session": "evening",
        "open_time": "16:00", "close_time": "20:00"}).status_code == 201
    # إغلاق قبل الفتح ⇒ 400 · فترة مجهولة ⇒ 400 · يوم خارج 0–6 ⇒ 422
    assert client.post(f"/department-hub/{dept['id']}/schedule", headers=admin, json={
        "day_of_week": 1, "open_time": "18:00",
        "close_time": "10:00"}).status_code == 400
    assert client.post(f"/department-hub/{dept['id']}/schedule", headers=admin, json={
        "day_of_week": 1, "session": "night"}).status_code == 400
    assert client.post(f"/department-hub/{dept['id']}/schedule", headers=admin,
                       json={"day_of_week": 9}).status_code == 422

    rows = client.get(f"/department-hub/{dept['id']}/schedule", headers=admin).json()
    assert [x["session"] for x in rows] == ["morning", "evening"]
    assert rows[0]["room_name"] == "عيادة 1"
    assert client.delete(f"/department-hub/{dept['id']}/schedule/{rows[0]['id']}",
                         headers=admin).status_code == 204
    assert len(client.get(f"/department-hub/{dept['id']}/schedule",
                          headers=admin).json()) == 1


# ===== 6) التقارير وإحصائيات القسم =====
def test_analytics_occupancy_financials_productivity(client, admin):
    """المؤشرات الثلاثة تُشتقّ من البيانات الحقيقية: أسرّة ومواعيد وفواتير."""
    dept = _dept(client, admin, monthly_operating_cost=30000)
    doc = _doctor(client, admin, dept["id"])
    other = _doctor(client, admin, _dept(client, admin)["id"])  # قسم آخر

    for i in range(4):
        bed = client.post("/beds/", headers=admin, json={
            "bed_number": f"HD{i}", "department_id": dept["id"]})
        if i < 2:      # سريران مشغولان
            client.put(f"/beds/{bed.json()['id']}", headers=admin,
                       json={"status": "occupied",
                             "patient_id": _patient(client, admin)["id"]})
    client.post("/beds/", headers=admin, json={"bed_number": "HD-m",
                "department_id": dept["id"], "status": "maintenance"})

    # موعدان للطبيب + فاتورة على أحدهما (للمريض نفسه)، وموعد لقسم آخر لا يُحتسب
    for i in range(2):
        who = _patient(client, admin)
        appt = client.post("/appointments/", headers=admin, json={
            "patient_id": who["id"], "doctor_id": doc["id"],
            "appointment_date": datetime.utcnow().isoformat()})
        assert appt.status_code == 200, appt.text
        if i == 0:
            inv = client.post("/invoices/", headers=admin, json={
                "patient_id": who["id"],
                "appointment_id": appt.json()["id"], "amount": 800,
                "description": "كشف كشفية"})
            assert inv.status_code == 200, inv.text
    client.post("/appointments/", headers=admin, json={
        "patient_id": _patient(client, admin)["id"], "doctor_id": other["id"],
        "appointment_date": datetime.utcnow().isoformat()})

    a = client.get(f"/department-hub/{dept['id']}/analytics", headers=admin,
                   params={"days": 30}).json()
    assert a["occupancy"]["beds_total"] == 5
    assert a["occupancy"]["beds_occupied"] == 2
    assert a["occupancy"]["beds_maintenance"] == 1
    assert a["occupancy"]["rate"] == 40.0
    assert a["financials"]["revenue"] == 800.0
    assert a["financials"]["cost"] == 30000.0
    assert a["financials"]["net"] == 800.0 - 30000.0
    assert a["productivity"]["appointments"] == 2
    assert a["productivity"]["doctors"] == 1
    assert a["productivity"]["per_doctor"][0]["name"] == doc["full_name"]

    rows = client.get("/department-hub/analytics", headers=admin,
                      params={"days": 30}).json()
    mine = next(r for r in rows if r["department_id"] == dept["id"])
    assert mine["productivity"]["appointments"] == 2
    assert client.get("/department-hub/999999/analytics", headers=admin).status_code == 404


# ===== الصلاحيات =====
def test_hub_permissions(client, admin):
    """القراءة لكل مسجّل، والكتابة للمدير فقط."""
    dept = _dept(client, admin)
    uname = f"dh{uid()}"
    created = client.post("/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "full_name": "موظف",
        "role": "موظف استقبال", "password": "Passw0rd!"})
    rec = login(client, created.json()["username"], "Passw0rd!")

    for path in ("/department-hub/directory", f"/department-hub/{dept['id']}/team",
                 f"/department-hub/{dept['id']}/rooms",
                 f"/department-hub/{dept['id']}/services",
                 f"/department-hub/{dept['id']}/schedule",
                 f"/department-hub/{dept['id']}/analytics"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=rec).status_code == 200, path

    writes = [
        ("put", f"/department-hub/{dept['id']}/structure", {"dept_type": "clinical"}),
        ("put", f"/department-hub/{dept['id']}/head", {"head_doctor_id": 1}),
        ("post", f"/department-hub/{dept['id']}/rooms", {"name": "غرفة"}),
        ("post", f"/department-hub/{dept['id']}/services", {"name": "خدمة"}),
        ("post", f"/department-hub/{dept['id']}/schedule", {"day_of_week": 0}),
        ("post", f"/department-hub/{dept['id']}/support", {"staff_id": 1}),
    ]
    for method, path, body in writes:
        call = getattr(client, method)
        assert call(path, headers=rec, json=body).status_code == 403, path
    assert client.get("/department-hub/directory", headers=rec).status_code == 200




