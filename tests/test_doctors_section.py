"""تطوير قسم الأطباء — بحث وفلاتر · إحصاءات · ملخّص طبيب · صلاحيات · تحديث كامل · حذف محميّ.

معزول عن بقية الاختبارات بوسوم فريدة (uid) حتى يعمل على القاعدة المشتركة بأمان.
"""
import uuid
from datetime import datetime

from conftest import login


def uid():
    return uuid.uuid4().hex[:8]


def _mk_doctor(client, admin, **kw):
    body = {
        "full_name": kw.get("name", "د. " + uid()),
        "specialty": kw.get("spec", "باطنة"),
        "license_number": kw.get("lic", "DOC-" + uid()),
        "phone": "0555550000",
        "email": kw.get("email", f"doc_{uid()}@test.com"),
        "is_available": kw.get("avail", True),
        "department_id": kw.get("dept"),
    }
    if kw.get("addr"):
        body["address"] = kw["addr"]
    r = client.post("/doctors/", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_dept(client, admin):
    name = "قسم-" + uid()
    r = client.post("/departments/", headers=admin,
                    json={"name": name, "description": "قسم اختبار تطوير الأطباء"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mk_patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض قسم الأطباء", "date_of_birth": "1990-03-03",
        "gender": "ذكر", "phone": "0566660000", "email": f"p_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _nonadmin(client, prefix):
    """حساب غير مدير (دور طبيب) لاختبارات الصلاحيات."""
    u = prefix + "_" + uid()
    r = client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "مستخدم " + u,
        "role": "doctor", "password": "secret123"})
    assert r.status_code == 200, r.text
    return login(client, u, "secret123")


# ========== المصادقة والصلاحيات ==========
def test_endpoints_require_auth(client):
    """بلا توكن ⇒ 401 على كل النهايات الجديدة والقديمة."""
    assert client.get("/doctors/").status_code == 401
    assert client.get("/doctors/stats").status_code == 401
    assert client.get("/doctors/1").status_code == 401
    assert client.post("/doctors/", json={}).status_code == 401
    assert client.put("/doctors/1/availability",
                      json={"is_available": True}).status_code == 401
    assert client.delete("/doctors/1").status_code == 401


def test_create_is_admin_only(client, admin):
    """الإنشاء لم يعد متاحًا لأي مستخدم مصادَق — المدير فقط (مطابق للواجهة)."""
    h = _nonadmin(client, "cr")
    r = client.post("/doctors/", headers=h, json={
        "full_name": "د. محاولة", "specialty": "باطنة",
        "license_number": "NO-" + uid(), "phone": "0500000001",
        "email": f"no_{uid()}@test.com"})
    assert r.status_code == 403


# ========== التحقق عند الإنشاء ==========
def test_create_validations(client, admin):
    d = _mk_doctor(client, admin)

    r = client.post("/doctors/", headers=admin, json={
        "full_name": "د. مكرر", "specialty": "باطنة",
        "license_number": d["license_number"], "phone": "0500000002",
        "email": f"dup_{uid()}@test.com"})
    assert r.status_code == 400 and "رقم التراخيص" in r.json()["detail"]

    r = client.post("/doctors/", headers=admin, json={
        "full_name": "د. مكرر بريد", "specialty": "باطنة",
        "license_number": "DUP-" + uid(), "phone": "0500000003",
        "email": d["email"]})
    assert r.status_code == 400 and "البريد الإلكتروني" in r.json()["detail"]

    r = client.post("/doctors/", headers=admin, json={
        "full_name": "د. قسم مفقود", "specialty": "باطنة",
        "license_number": "NOD-" + uid(), "phone": "0500000004",
        "email": f"nod_{uid()}@test.com", "department_id": 999999})
    assert r.status_code == 404 and "القسم غير موجود" in r.json()["detail"]


# ========== البحث والفلاتر والترتيب ==========
def test_list_filters_and_sort(client, admin):
    dept_a = _mk_dept(client, admin)
    spec = "جهاز-" + uid()
    a = _mk_doctor(client, admin, name="د. وحيد-" + uid(),
                   spec=spec, dept=dept_a, avail=True)
    b = _mk_doctor(client, admin, name="د. معطّل-" + uid(),
                   spec=spec, dept=dept_a, avail=False)
    _mk_doctor(client, admin, name="د. بلا قسم-" + uid(), spec=spec, dept=None)

    # q بالاسم الجزئي
    term = a["full_name"].split("د. ")[-1]
    ids = [r["id"] for r in client.get(
        "/doctors/", headers=admin, params={"q": term}).json()]
    assert ids == [a["id"]]

    # q بالتخصص الفريد
    ids = [r["id"] for r in client.get(
        "/doctors/", headers=admin, params={"q": spec}).json()]
    assert {a["id"], b["id"]} <= set(ids) and len(ids) == 3

    # فلتر القسم
    ids = [r["id"] for r in client.get(
        "/doctors/", headers=admin, params={"department_id": dept_a}).json()]
    assert {a["id"], b["id"]} <= set(ids)

    # فلتر التوافر
    ids = [r["id"] for r in client.get(
        "/doctors/", headers=admin, params={"available": "false"}).json()]
    assert b["id"] in ids and a["id"] not in ids

    # الترتيب
    names = [r["full_name"] for r in client.get(
        "/doctors/", headers=admin, params={"sort": "name"}).json()]
    assert names == sorted(names)
    names = [r["specialty"] for r in client.get(
        "/doctors/", headers=admin, params={"sort": "specialty"}).json()]
    assert names == sorted(names)

    # ترتيب غير صالح ⇒ 400
    r = client.get("/doctors/", headers=admin, params={"sort": "hack"})
    assert r.status_code == 400 and "sort" in r.json()["detail"]


# ========== الإحصاءات ==========
def test_stats_shape(client, admin):
    _mk_doctor(client, admin)  # ضمان وجود طبيب واحد على الأقل
    s = client.get("/doctors/stats", headers=admin).json()
    assert s["total"] == s["available"] + s["unavailable"]
    assert s["total"] >= 1 and s["specialties"] >= 1 and s["appointments"] >= 0
    assert sum(d["count"] for d in s["departments"]) + s["without_department"] <= s["total"]
    assert all("name" in d and "count" in d for d in s["departments"])


# ========== ملخّص الطبيب ==========
def test_detail_with_stats(client, admin):
    doc = _mk_doctor(client, admin)
    pat = _mk_patient(client, admin)

    r = client.get(f"/doctors/{doc['id']}", headers=admin)
    assert r.status_code == 200
    assert r.json()["stats"] == {"appointments": 0, "records": 0, "patients": 0}

    assert client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc["id"],
        "appointment_date": "2031-04-04T11:00:00", "reason": "فحص"}).status_code == 200
    assert client.post("/medical-records/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc["id"], "diagnosis": "كشف"}).status_code == 200

    st = client.get(f"/doctors/{doc['id']}", headers=admin).json()["stats"]
    assert st == {"appointments": 1, "records": 1, "patients": 1}

    assert client.get("/doctors/999999", headers=admin).status_code == 404


# ========== التحديث الكامل ومنع التكرار ==========
def test_update_completeness_and_uniqueness(client, admin):
    d1 = _mk_doctor(client, admin)
    d2 = _mk_doctor(client, admin)

    # ترخيص وعنوان — كانا غائبَين في DoctorUpdate (بلا تعديل عليهما أصلًا)
    r = client.put(f"/doctors/{d1['id']}", headers=admin, json={
        "license_number": "NEW-" + uid(), "address": "الرياض، حي الاختبار",
        "specialty": "جراحة عامة"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["address"] == "الرياض، حي الاختبار" and j["specialty"] == "جراحة عامة"

    # تكرار ترخيص طبيب آخر — كان IntegrityError 500 والآن 400
    r = client.put(f"/doctors/{d1['id']}", headers=admin,
                   json={"license_number": d2["license_number"]})
    assert r.status_code == 400 and "رقم التراخيص" in r.json()["detail"]

    r = client.put(f"/doctors/{d1['id']}", headers=admin, json={"email": d2["email"]})
    assert r.status_code == 400 and "البريد الإلكتروني" in r.json()["detail"]

    r = client.put(f"/doctors/{d1['id']}", headers=admin, json={"department_id": 999999})
    assert r.status_code == 404 and "القسم غير موجود" in r.json()["detail"]

    assert client.put("/doctors/999999", headers=admin,
                      json={"full_name": "x"}).status_code == 404

    h = _nonadmin(client, "up")
    assert client.put(f"/doctors/{d1['id']}", headers=h,
                      json={"full_name": "x"}).status_code == 403


# ========== التوافر: مدير أو الطبيب نفسه ==========
def test_availability_permissions(client, admin):
    d1 = _mk_doctor(client, admin, avail=True)
    d2 = _mk_doctor(client, admin, avail=True)

    h = _nonadmin(client, "av")
    r = client.put(f"/doctors/{d1['id']}/availability", headers=h,
                   json={"is_available": False})
    assert r.status_code == 403 and "لا تملك صلاحية تغيير توافر هذا الطبيب" \
        in r.json()["detail"]

    r = client.put(f"/doctors/{d1['id']}/availability", headers=admin,
                   json={"is_available": False})
    assert r.status_code == 200 and r.json()["is_available"] is False

    # حساب طبيب مرتبط بنفس بريد d2 ⇒ يغيّر توافره هو
    u = "self_" + uid()
    r = client.post("/auth/register", json={
        "username": u, "email": d2["email"], "full_name": "ذاتي",
        "role": "doctor", "password": "secret123"})
    assert r.status_code == 200, r.text
    hs = login(client, u, "secret123")
    r = client.put(f"/doctors/{d2['id']}/availability", headers=hs,
                   json={"is_available": False})
    assert r.status_code == 200 and r.json()["is_available"] is False

    assert client.put("/doctors/999999/availability", headers=admin,
                      json={"is_available": True}).status_code == 404


# ========== الحذف المحميّ ==========
def test_delete_guards(client, admin):
    pat = _mk_patient(client, admin)

    # سجل طبي ⇒ 409 (كان انفجار FK 500)
    d1 = _mk_doctor(client, admin)
    assert client.post("/medical-records/", headers=admin, json={
        "patient_id": pat, "doctor_id": d1["id"], "diagnosis": "مزمن"}).status_code == 200
    r = client.delete(f"/doctors/{d1['id']}", headers=admin)
    assert r.status_code == 409 and "سجل طبي" in r.json()["detail"]
    assert client.get(f"/doctors/{d1['id']}", headers=admin).status_code == 200

    # مواعيد ⇒ 409 (كانت تُحذف مع الطبيب بهدوء)
    d2 = _mk_doctor(client, admin)
    assert client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": d2["id"],
        "appointment_date": "2031-05-05T09:00:00", "reason": "متابعة"}).status_code == 200
    r = client.delete(f"/doctors/{d2['id']}", headers=admin)
    assert r.status_code == 409 and "موعد" in r.json()["detail"]

    # نظيف ⇒ 204 ثم 404
    d3 = _mk_doctor(client, admin)
    assert client.delete(f"/doctors/{d3['id']}", headers=admin).status_code == 204
    assert client.get(f"/doctors/{d3['id']}", headers=admin).status_code == 404

    assert client.delete("/doctors/999999", headers=admin).status_code == 404
    h = _nonadmin(client, "dl")
    d4 = _mk_doctor(client, admin)
    assert client.delete(f"/doctors/{d4['id']}", headers=h).status_code == 403


# ========== تقرير الأداء الشهري ==========
def test_performance_report(client, admin):
    """تقرير شهري: مواعيد حسب الحالة + نسبة الإتمام + مرضى وسجلات الشهر + تحقق month."""
    doc = _mk_doctor(client, admin)
    pat = _mk_patient(client, admin)

    # موعدان في 2031-04: أحدهما مكتمل والآخر ملغى
    a1 = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc["id"],
        "appointment_date": "2031-04-04T10:00:00", "reason": "كشف"})
    a2 = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc["id"],
        "appointment_date": "2031-04-05T10:00:00", "reason": "متابعة"})
    assert a1.status_code == 200 and a2.status_code == 200, a1.text + a2.text
    assert client.put(f"/appointments/{a1.json()['id']}", headers=admin,
                      json={"status": "completed"}).status_code == 200
    assert client.put(f"/appointments/{a2.json()['id']}", headers=admin,
                      json={"status": "cancelled"}).status_code == 200

    r = client.get(f"/doctors/{doc['id']}/performance", headers=admin,
                   params={"month": "2031-04"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["month"] == "2031-04" and j["doctor_id"] == doc["id"]
    assert j["total"] == 2 and j["completed"] == 1 and j["cancelled"] == 1
    assert j["pending"] == 0 and j["confirmed"] == 0
    assert j["completion_rate"] == 0.5 and j["patients"] == 1
    assert j["records"] == 0

    # شهر بلا مواعيد ⇒ أصفار صريحة
    j0 = client.get(f"/doctors/{doc['id']}/performance", headers=admin,
                    params={"month": "2031-01"}).json()
    assert j0["total"] == 0 and j0["completion_rate"] == 0.0
    assert j0["patients"] == 0 and j0["records"] == 0

    # سجل طبي يُنشأ الآن ⇒ يظهر في الشهر الحالي فقط
    assert client.post("/medical-records/", headers=admin, json={
        "patient_id": pat, "doctor_id": doc["id"], "diagnosis": "كشف"}
    ).status_code == 200
    now_m = datetime.now().strftime("%Y-%m")
    jn = client.get(f"/doctors/{doc['id']}/performance", headers=admin,
                    params={"month": now_m}).json()
    assert jn["records"] == 1 and jn["total"] == 0

    # month غير صالح ⇒ 400 برسالة معيارية
    for bad in ("2031-13", "203104", "04-2031", "hack"):
        rb = client.get(f"/doctors/{doc['id']}/performance", headers=admin,
                        params={"month": bad})
        assert rb.status_code == 400, (bad, rb.status_code)
        assert "YYYY-MM" in rb.json()["detail"]

    # 401 بلا توكن + 404 لمعرف مفقود
    assert client.get(f"/doctors/{doc['id']}/performance",
                      params={"month": "2031-04"}).status_code == 401
    assert client.get("/doctors/999999/performance", headers=admin,
                      params={"month": "2031-04"}).status_code == 404


# ========== التقرير المقارن + التصدير ==========
def test_performance_ranking_and_exports(client, admin):
    """تقرير مقارن: ترتيب حسب الإتمام + أصفار + تصدير CSV/PDF وبطاقة ترخيص."""
    doc_a = _mk_doctor(client, admin)      # إتمام 100%
    doc_b = _mk_doctor(client, admin)      # إتمام 0%
    pat = _mk_patient(client, admin)

    def mk_appt(doc, when, status):
        r = client.post("/appointments/", headers=admin, json={
            "patient_id": pat, "doctor_id": doc["id"],
            "appointment_date": when, "reason": "كشف"})
        assert r.status_code == 200, r.text
        assert client.put(f"/appointments/{r.json()['id']}", headers=admin,
                          json={"status": status}).status_code == 200

    mk_appt(doc_a, "2031-06-01T10:00:00", "completed")
    mk_appt(doc_b, "2031-06-02T10:00:00", "cancelled")

    r = client.get("/doctors/performance", headers=admin, params={"month": "2031-06"})
    assert r.status_code == 200, r.text
    rows = r.json()
    ids = [x["doctor_id"] for x in rows]
    assert doc_a["id"] in ids and doc_b["id"] in ids and len(rows) >= 2
    ra = next(x for x in rows if x["doctor_id"] == doc_a["id"])
    rb = next(x for x in rows if x["doctor_id"] == doc_b["id"])
    assert ra["full_name"] == doc_a["full_name"]
    assert ra["completion_rate"] == 1.0 and ra["completed"] == 1
    assert rb["completion_rate"] == 0.0 and rb["cancelled"] == 1
    assert ids.index(doc_a["id"]) < ids.index(doc_b["id"])  # 100% قبل 0%
    assert all(k in ra for k in ("specialty", "is_available", "month", "patients"))

    # شهر بلا مواعيد لأي طبيب ⇒ كل الصفوف أصفار
    r0 = client.get("/doctors/performance", headers=admin, params={"month": "2031-01"})
    assert r0.status_code == 200 and all(x["total"] == 0 for x in r0.json())

    # month خاطئ ⇒ 400 · 401 بلا توكن
    assert client.get("/doctors/performance", headers=admin,
                      params={"month": "2031-13"}).status_code == 400
    assert client.get("/doctors/performance",
                      params={"month": "2031-06"}).status_code == 401

    # تصدير الفرد: CSV
    rc = client.get(f"/doctors/{doc_a['id']}/performance/export.csv",
                    headers=admin, params={"month": "2031-06"})
    assert rc.status_code == 200 and rc.headers["content-type"].startswith("text/csv")
    body = rc.content.decode("utf-8-sig")
    assert "نسبة الإتمام" in body and doc_a["full_name"] in body
    assert "2031-06" in body and "100.0" in body

    # تصدير الفرد: PDF التقرير
    rp = client.get(f"/doctors/{doc_a['id']}/performance/report.pdf",
                    headers=admin, params={"month": "2031-06"})
    assert rp.status_code == 200
    assert rp.headers["content-type"].startswith("application/pdf")
    assert rp.content[:4] == b"%PDF"

    # التصدير المقارن
    rl = client.get("/doctors/performance/export.csv",
                    headers=admin, params={"month": "2031-06"})
    assert rl.status_code == 200
    lb = rl.content.decode("utf-8-sig")
    assert doc_a["full_name"] in lb and "نسبة الإتمام" in lb

    # بطاقة الترخيص
    rlic = client.get(f"/doctors/{doc_a['id']}/license.pdf", headers=admin)
    assert rlic.status_code == 200 and rlic.content[:4] == b"%PDF"

    # month خاطئ في التصدير ⇒ 400 · مفقود ⇒ 404 · بلا توكن ⇒ 401
    assert client.get(f"/doctors/{doc_a['id']}/performance/export.csv",
                      headers=admin, params={"month": "xx"}).status_code == 400
    assert client.get("/doctors/999999/license.pdf", headers=admin).status_code == 404
    assert client.get(f"/doctors/{doc_a['id']}/license.pdf").status_code == 401


# ========== نوبات العمل ==========
def test_doctor_schedule(client, admin):
    """نوبات الأسبوع: حفظ/استبدال/استرجاع + تكرار اليوم + صلاحيات."""
    doc = _mk_doctor(client, admin)
    url = f"/doctors/{doc['id']}/schedule"

    # فارغ قبل أول حفظ
    r = client.get(url, headers=admin)
    assert r.status_code == 200 and r.json() == []

    entries = [
        {"day_of_week": 0, "start_time": "09:00", "end_time": "14:00",
         "location": "عيادة 1"},
        {"day_of_week": 3, "start_time": "10:00", "end_time": "16:00"},
    ]
    r = client.put(url, headers=admin, json={"entries": entries})
    assert r.status_code == 200, r.text
    back = r.json()
    assert len(back) == 2 and back[0]["day_of_week"] == 0
    assert back[0]["start_time"].startswith("09:00") and back[0]["location"] == "عيادة 1"
    assert back[1]["location"] is None and back[1]["end_time"].startswith("16:00")

    # الاستبدال الكامل: نوبة واحدة فقط تبقى
    r = client.put(url, headers=admin, json={"entries": [entries[1]]})
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]["day_of_week"] == 3

    # نوبتان متداخلتان في نفس اليوم ⇒ 400
    dup = [entries[1], {"day_of_week": 3, "start_time": "12:00", "end_time": "15:00"}]
    r = client.put(url, headers=admin, json={"entries": dup})
    assert r.status_code == 400 and "متداخلتان" in r.json()["detail"]

    # نهاية قبل البداية ⇒ 400
    r = client.put(url, headers=admin, json={"entries": [
        {"day_of_week": 1, "start_time": "15:00", "end_time": "09:00"}]})
    assert r.status_code == 400 and "النهاية" in r.json()["detail"]

    # يوم خارج 0..6 ⇒ 422 (تحقّق السكيما)
    r = client.put(url, headers=admin, json={"entries": [
        {"day_of_week": 9, "start_time": "09:00", "end_time": "12:00"}]})
    assert r.status_code == 422

    # فشل التحقق لا يمسّ المحفوظ (الحذف بعد التحقق فقط)
    assert len(client.get(url, headers=admin).json()) == 1

    # صلاحيات: غير المدير ولا الذات ⇒ 403 برسالة النوبات
    h = _nonadmin(client, "sch")
    r = client.put(url, headers=h, json={"entries": []})
    assert r.status_code == 403 and "نوبات" in r.json()["detail"]
    # القراءة متاحة لأي مستخدم موثّق
    assert client.get(url, headers=h).status_code == 200

    # 404 + 401
    assert client.put("/doctors/999999/schedule", headers=admin,
                      json={"entries": []}).status_code == 404
    assert client.get(url).status_code == 401


# ===== حجز خارج النوبة =====
def test_appointment_outside_schedule(client, admin):
    """حجز في يوم بدون نوبات أو خارج النوبة → 400"""
    from datetime import datetime
    doc = _mk_doctor(client, admin)
    doct0 = doc["id"]
    pat = _mk_patient(client, admin)
    d0 = (datetime(2031, 7, 5)).date()
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doct0,
        "appointment_date": d0.isoformat() + "T10:00:00",
        "reason": "اختبار", "status": "pending"})
    assert r.status_code == 200
    client.put(f"/doctors/{doct0}/schedule", headers=admin, json={
        "entries": [{"day_of_week": 1, "start_time": "09:00", "end_time": "13:00"}]})
    d_sat = (datetime(2031, 7, 5)).date()
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doct0,
        "appointment_date": d_sat.isoformat() + "T10:00:00",
        "reason": "اختبار", "status": "pending"})
    assert r.status_code == 400 and "لا يعمل في يوم" in r.json()["detail"]
    d_sun = (datetime(2031, 7, 6)).date()
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doct0,
        "appointment_date": d_sun.isoformat() + "T14:00:00",
        "reason": "اختبار", "status": "pending"})
    assert r.status_code == 400 and "خارج نوبات" in r.json()["detail"]
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pat, "doctor_id": doct0,
        "appointment_date": d_sun.isoformat() + "T10:00:00",
        "reason": "اختبار", "status": "pending"})
    assert r.status_code == 200
