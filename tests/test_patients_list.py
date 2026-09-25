"""قائمة المرضى: بحث على الخادم + فلاتر + ترقيم + ترتيب + أعمدة محسوبة + CSV.

يغطي أن البحث لا يطابق أعمدة غير مقصودة (كان في الواجهة يطابق نص الصف كله)،
وأن العدد الكلي يصل في الترويسة X-Total-Count، وأن تصديرًا ثم استيرادًا
لا يفقد أي حقل من حقول الملف الشخصي.
"""
import uuid

import io  # noqa: F401  (يُستخدم في اختبارات لاحقة)


def uid():
    return uuid.uuid4().hex[:8]


def _mk(client, admin, **over):
    """مريض ببيانات قابلة للتحكم (بحث/فلترة)."""
    body = {
        "full_name": f"مريض قائمة {uid()}",
        "date_of_birth": "1990-05-05", "gender": "ذكر",
        "phone": "0555" + uid()[:6], "email": f"lst_{uid()}@test.com",
    }
    body.update(over)
    r = client.post("/patients/", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _row(client, admin, pid):
    """صف المريض من القائمة (بلا حد ⇒ يرجع الكل)."""
    rows = client.get("/patients/", headers=admin, params={"limit": 500}).json()
    return next(x for x in rows if x["id"] == pid)


# ══════════ الترقيم والعدّاد ══════════
def test_list_total_header_and_pagination(client, admin):
    for _ in range(3):
        _mk(client, admin)
    r = client.get("/patients/", headers=admin, params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    page1 = r.json()
    assert len(page1) == 2
    total = int(r.headers["X-Total-Count"])
    assert total >= 3

    r2 = client.get("/patients/", headers=admin, params={"limit": 2, "offset": 2})
    page2 = r2.json()
    assert not ({p["id"] for p in page1} & {p["id"] for p in page2})
    assert r2.headers["X-Total-Count"] == str(total)


def test_list_pagination_bounds(client, admin):
    assert client.get("/patients/", headers=admin, params={"limit": 900}).status_code == 422
    assert client.get("/patients/", headers=admin, params={"offset": -1}).status_code == 422
    assert client.get("/patients/", headers=admin, params={"limit": 500}).status_code == 200


# ══════════ البحث ══════════
def test_list_search_is_field_scoped_and_case_insensitive(client, admin):
    p = _mk(client, admin, full_name=f"AbCdEf {uid()}")
    nat = "77" + uid()[:8]
    p2 = _mk(client, admin, national_id=nat)

    found = client.get("/patients/", headers=admin,
                       params={"search": p["full_name"].lower()}).json()
    assert any(x["id"] == p["id"] for x in found)
    found = client.get("/patients/", headers=admin, params={"search": nat}).json()
    assert [x["id"] for x in found] == [p2["id"]]
    found = client.get("/patients/", headers=admin, params={"search": p["email"]}).json()
    assert any(x["id"] == p["id"] for x in found)


def test_list_search_ignores_dates_and_other_columns(client, admin):
    """تاريخ الإنشاء لم يكن هدف البحث — كان يُطابق في الواجهة (نص الصف)."""
    _mk(client, admin)
    assert client.get("/patients/", headers=admin, params={"search": "2006"}).json() == []


def test_list_requires_auth(client):
    assert client.get("/patients/").status_code == 401


# ══════════ الفلاتر ══════════
def test_list_filter_by_blood_type(client, admin):
    _mk(client, admin, blood_type="AB-")
    rows = client.get("/patients/", headers=admin, params={"blood_type": "AB-"}).json()
    assert rows and all(x["blood_type"] == "AB-" for x in rows)


def test_list_alert_filter(client, admin):
    with_alert = _mk(client, admin, allergies="بنسلين")
    plain = _mk(client, admin)
    rows = client.get("/patients/", headers=admin, params={"alert": "has"}).json()
    ids = {x["id"] for x in rows}
    assert with_alert["id"] in ids
    assert plain["id"] not in ids
    assert all(x["has_alerts"] for x in rows)


# ══════════ الترتيب ══════════
def test_list_sort_direction_matters(client, admin):
    a = _mk(client, admin, full_name="AAA sort first " + uid())
    z = _mk(client, admin, full_name="ZZZ sort last " + uid())
    asc = client.get("/patients/", headers=admin,
                     params={"sort": "name", "dir": "asc", "limit": 500}).json()
    desc = client.get("/patients/", headers=admin,
                      params={"sort": "name", "dir": "desc", "limit": 500}).json()
    ids_asc = [x["id"] for x in asc]
    ids_desc = [x["id"] for x in desc]
    assert ids_asc.index(a["id"]) < ids_asc.index(z["id"])
    assert ids_desc.index(z["id"]) < ids_desc.index(a["id"])
    assert ids_asc == list(reversed(ids_desc))


def test_list_sort_by_age(client, admin):
    age = client.get("/patients/", headers=admin,
                     params={"sort": "age", "dir": "asc", "limit": 500}).json()
    dobs = [x["date_of_birth"] for x in age]
    assert dobs == sorted(dobs)


# ══════════ التصدير والاستيراد بالحقول الجديدة ══════════
def test_export_csv_has_new_profile_columns(client, admin):
    csv_text = client.get("/patients/export.csv", headers=admin).text
    head = csv_text.lstrip("\ufeff").splitlines()[0]
    for col in ("الجنسية", "جهة الطوارئ", "هاتف الطوارئ", "درجة التغطية",
                "نسبة التحمل", "الحساسية", "التحذيرات", "الأمراض المزمنة"):
        assert col in head, col


def test_export_then_import_roundtrip_has_no_row_errors(client, admin):
    """تصدير ⇒ استيراد: الخلايا الفارغة لا تُرفض، والمكرّر يُتخطّى."""
    _mk(client, admin, nationality="سعودي", insurance_grade="ذهبية",
        insurance_copay=20, allergies="بنسلين", medical_warnings="مريض سكر",
        emergency_contact_name="ولي الأمر", emergency_contact_phone="0509999999")
    csv_text = client.get("/patients/export.csv", headers=admin).text
    r = client.post("/patients/import", headers=admin, files={
        "file": ("patients.csv", csv_text.lstrip("\ufeff").encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["errors"] == []
    assert rep["created"] == 0        # كلهم مكرّرون (نفس البريد/الهوية)
    assert rep["skipped"] >= 1


def test_import_new_fields_from_csv(client, admin):
    u = uid()
    csv_text = ("الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد,الجنسية,درجة التغطية,"
                "نسبة التحمل,الحساسية,التحذيرات\n"
                f"مستورد ملف,1988-03-03,ذكر,0551234567,imp_{u}@test.com,مصري,فضية,25,غبار,ربو\n")
    r = client.post("/patients/import", headers=admin, files={
        "file": ("p.csv", csv_text.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1

    rows = client.get("/patients/", headers=admin,
                      params={"search": f"imp_{u}@test.com"}).json()
    assert len(rows) == 1
    p = rows[0]
    assert p["nationality"] == "مصري"
    assert p["insurance_grade"] == "فضية"
    assert p["insurance_copay"] == 25.0
    assert p["allergies"] == "غبار"
    assert p["medical_warnings"] == "ربو"
    assert p["has_alerts"] is True


def test_import_copay_out_of_range_reports_row_error(client, admin):
    u = uid()
    csv_text = ("الاسم الكامل,تاريخ الميلاد,النوع,الهاتف,البريد,نسبة التحمل\n"
                f"تحمل خاطئ,1990-01-01,ذكر,0559999999,cp_{u}@test.com,150\n")
    r = client.post("/patients/import", headers=admin, files={
        "file": ("p.csv", csv_text.encode("utf-8"), "text/csv")})
    assert r.status_code == 200
    rep = r.json()
    assert rep["created"] == 0
    assert rep["errors"] and "insurance_copay" in rep["errors"][0]["error"]


# ══════════ الواجهة ══════════
def test_patients_ui_markers(client):
    ui = client.get("/").text + client.get("/app.js").text
    for marker in ("getPatientListState", "searchPatients", "sortPatients",
                   "gotoPatientPage", "resetPatients", "patientAddForm",
                   "X-Total-Count"):
        assert marker in ui, marker


def test_patients_ui_no_longer_filters_by_row_text(client):
    """فلترة نص الصف كانت تُطابق أعمدة غير مقصودة (التاريخ/البريد) — أُزيلت."""
    js = client.get("/app.js").text
    body = js.split("async patients(main)")[1][:3000]
    assert "filterTable('tbl'" not in body
    assert "/patients/?" in body

# ══════════ الأعمدة المحسوبة (العمر · التحذير · آخر زيارة · المتبقي) ══════════
def test_list_computed_columns(client, admin):
    p = _mk(client, admin, allergies="أسبرين")
    row = _row(client, admin, p["id"])
    assert row["has_alerts"] is True
    assert isinstance(row["age"], int) and row["age"] > 0
    assert row["outstanding"] == 0.0


def test_list_outstanding_matches_invoice_total_formula(client, admin):
    """(المبلغ − الخصم) + الضريبة − المدفوع — نفس معادلة Invoice.total."""
    p = _mk(client, admin)
    inv = client.post("/invoices/", headers=admin, json={
        "patient_id": p["id"], "amount": 1000, "discount": 100, "tax_rate": 15,
        "description": "خدمة"}).json()
    assert inv["total"] == 1035.0
    assert _row(client, admin, p["id"])["outstanding"] == 1035.0

    client.post(f"/invoices/{inv['id']}/pay", headers=admin,
                json={"amount": 35, "method": "cash"})
    assert _row(client, admin, p["id"])["outstanding"] == 1000.0


def test_list_last_visit_and_upcoming(client, admin):
    p = _mk(client, admin)
    doc = client.post("/doctors/", headers=admin, json={
        "full_name": "طبيب قائمة", "specialty": "عام", "license_number": "LIC-" + uid(),
        "phone": "0500000000", "email": f"doc_{uid()}@test.com"}).json()
    for when in ("2020-01-10T10:00:00", "2031-06-01T09:00:00"):
        r = client.post("/appointments/", headers=admin, json={
            "patient_id": p["id"], "doctor_id": doc["id"],
            "appointment_date": when, "reason": "متابعة"})
        assert r.status_code == 200, r.text

    row = _row(client, admin, p["id"])
    assert row["last_visit"].startswith("2020-01-10")
    assert row["upcoming"].startswith("2031-06-01")

