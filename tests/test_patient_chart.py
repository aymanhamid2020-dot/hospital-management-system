"""شاشة ملف المريض: الأقسام الستة + العلامات الحيوية + مطالبات التأمين.

تغطي نقطة الملف المجمّعة GET /patients/{id}/chart وتحديث الملف الشخصي
والعلامات الحيوية عبر الزيارات ودورة مطالبة التأمين (تقديم → موافقة/رفض).
"""
from conftest import login
from test_api import uid, _make_patient


def _chart(client, admin, pat_id):
    r = client.get(f"/patients/{pat_id}/chart", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


# ========== (1) الملف الشخصي والإداري ==========
def test_chart_has_six_sections(client, admin):
    pat = _make_patient(client, admin)
    c = _chart(client, admin, pat)
    for key in ("profile", "records", "vitals", "appointments", "lab_orders",
                "prescriptions", "dispenses", "invoices", "financials",
                "claims", "attachments"):
        assert key in c, key
    assert c["profile"]["id"] == pat
    for key in ("past", "upcoming", "upcoming_total"):
        assert key in c["appointments"], key
    for key in ("dues", "outstanding", "invoices_total", "sales_total"):
        assert key in c["financials"], key


def test_chart_unknown_patient_404(client, admin):
    assert client.get("/patients/999999/chart", headers=admin).status_code == 404


def test_chart_requires_auth(client):
    assert client.get("/patients/1/chart").status_code == 401


def test_update_profile_demographics_and_insurance(client, admin):
    pat = _make_patient(client, admin)
    r = client.put(f"/patients/{pat}/profile", headers=admin, json={
        "nationality": "سعودي", "smoking_status": "غير مدخن",
        "emergency_contact_name": "أحمد", "emergency_contact_phone": "0501112222",
        "emergency_contact_relation": "الأخ", "insurance_grade": "ذهبية",
        "insurance_copay": 20, "allergies": "بنسلين",
        "medical_warnings": "مريض سكر", "chronic_conditions": "سكري نوع 2",
        "past_surgeries": "مرارة 2019", "family_history": "القلب",
    })
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["nationality"] == "سعودي"
    assert p["smoking_status"] == "غير مدخن"
    assert p["emergency_contact_name"] == "أحمد"
    assert p["insurance_grade"] == "ذهبية"
    assert p["insurance_copay"] == 20
    assert p["allergies"] == "بنسلين"
    assert p["medical_warnings"] == "مريض سكر"
    # تظهر في نقطة الملف المجمّع
    assert _chart(client, admin, pat)["profile"]["allergies"] == "بنسلين"


def test_update_profile_rejects_copay_out_of_range(client, admin):
    pat = _make_patient(client, admin)
    r = client.put(f"/patients/{pat}/profile", headers=admin, json={"insurance_copay": 150})
    assert r.status_code == 422
    assert client.put(f"/patients/{pat}/profile", headers=admin,
                      json={"insurance_copay": -5}).status_code == 422


def test_update_profile_unknown_patient_404(client, admin):
    assert client.put("/patients/999999/profile", headers=admin,
                      json={"nationality": "سعودي"}).status_code == 404


# ========== (2) العلامات الحيوية ==========
def test_vitals_crud_with_bmi(client, admin):
    pat = _make_patient(client, admin)
    r = client.post(f"/patients/{pat}/vitals", headers=admin, json={
        "systolic": 130, "diastolic": 85, "temperature": 37.2,
        "pulse": 78, "weight": 80, "height": 175, "notes": "روتيني"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["patient_id"] == pat
    assert v["bmi"] == 26.1          # 80 / 1.75²
    vid = v["id"]

    assert client.post(f"/patients/{pat}/vitals", headers=admin,
                       json={"pulse": 70}).json()["bmi"] is None
    r = client.put(f"/patients/{pat}/vitals/{vid}", headers=admin, json={"pulse": 60})
    assert r.status_code == 200 and r.json()["pulse"] == 60

    assert len(_chart(client, admin, pat)["vitals"]) == 2
    assert client.delete(f"/patients/{pat}/vitals/{vid}", headers=admin).status_code == 204
    assert client.delete(f"/patients/{pat}/vitals/{vid}", headers=admin).status_code == 404
    assert len(_chart(client, admin, pat)["vitals"]) == 1


def test_vitals_validation(client, admin):
    pat = _make_patient(client, admin)
    r = client.post(f"/patients/{pat}/vitals", headers=admin, json={"notes": "فارغ"})
    assert r.status_code == 400            # لا قياس واحد على الأقل
    r = client.post(f"/patients/{pat}/vitals", headers=admin, json={"systolic": 120})
    assert r.status_code == 400            # الضغط نصفه
    assert client.post(f"/patients/{pat}/vitals", headers=admin,
                       json={"temperature": 55}).status_code == 422
    assert client.post(f"/patients/{pat}/vitals", headers=admin,
                       json={"weight": 0}).status_code == 422
    assert client.post("/patients/999999/vitals", headers=admin,
                       json={"pulse": 70}).status_code == 404


def test_vitals_isolated_per_patient(client, admin):
    p1, p2 = _make_patient(client, admin), _make_patient(client, admin)
    client.post(f"/patients/{p1}/vitals", headers=admin, json={"pulse": 70})
    assert client.get(f"/patients/{p2}/vitals", headers=admin).json() == []
    v = client.post(f"/patients/{p1}/vitals", headers=admin, json={"pulse": 70}).json()
    assert client.delete(f"/patients/{p2}/vitals/{v['id']}", headers=admin).status_code == 404


def test_chief_complaint_in_medical_record(client, admin):
    pat = _make_patient(client, admin)
    r = client.post("/medical-records/", headers=admin, json={
        "patient_id": pat, "diagnosis": "نزلة برد",
        "chief_complaint": "حمى وألم حلق منذ ثلاثة أيام"})
    assert r.status_code == 200, r.text
    assert r.json()["chief_complaint"] == "حمى وألم حلق منذ ثلاثة أيام"
    assert _chart(client, admin, pat)["records"][0]["chief_complaint"].startswith("حمى")


# ========== (5) مطالبات التأمين ==========
def test_claim_lifecycle_approve(client, admin):
    pat = _make_patient(client, admin)
    client.put(f"/patients/{pat}/profile", headers=admin, json={"insurer": "بوبا العربية"})
    r = client.post(f"/patients/{pat}/claims", headers=admin,
                    json={"claim_number": "CLM-" + uid(), "amount": 800})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "submitted"
    assert c["insurer"] == "بوبا العربية"      # تُورَث من ملف المريض
    cid = c["id"]

    r = client.put(f"/patients/{pat}/claims/{cid}", headers=admin, json={"status": "approved"})
    assert r.status_code == 400               # الموافقة بلا قيمة ⇒ 400
    r = client.put(f"/patients/{pat}/claims/{cid}", headers=admin,
                   json={"status": "approved", "approved_amount": 650})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "approved" and d["approved_amount"] == 650
    assert d["decided_at"] is not None

    assert len(_chart(client, admin, pat)["claims"]) == 1
    assert client.delete(f"/patients/{pat}/claims/{cid}", headers=admin).status_code == 204
    assert client.get(f"/patients/{pat}/claims", headers=admin).json() == []


def test_claim_rejection_requires_reason(client, admin):
    pat = _make_patient(client, admin)
    cid = client.post(f"/patients/{pat}/claims", headers=admin,
                      json={"claim_number": "CLM-" + uid(), "amount": 300}).json()["id"]
    r = client.put(f"/patients/{pat}/claims/{cid}", headers=admin, json={"status": "rejected"})
    assert r.status_code == 400
    r = client.put(f"/patients/{pat}/claims/{cid}", headers=admin,
                   json={"status": "rejected", "rejection_reason": "خارج التغطية"})
    assert r.status_code == 200
    assert r.json()["rejection_reason"] == "خارج التغطية"


def test_claim_duplicate_number_and_bad_invoice(client, admin):
    pat = _make_patient(client, admin)
    no = "CLM-" + uid()
    assert client.post(f"/patients/{pat}/claims", headers=admin,
                       json={"claim_number": no, "amount": 100}).status_code == 201
    assert client.post(f"/patients/{pat}/claims", headers=admin,
                       json={"claim_number": no, "amount": 100}).status_code == 400
    r = client.post(f"/patients/{pat}/claims", headers=admin,
                    json={"claim_number": "CLM-" + uid(), "amount": 100,
                          "invoice_id": 999999})
    assert r.status_code == 404


def test_claims_require_admin(client, admin):
    u = "rec_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "موظف", "password": "secret123"})
    rec = login(client, u, "secret123")
    pat = _make_patient(client, admin)
    assert client.get(f"/patients/{pat}/claims", headers=rec).status_code == 200
    assert client.post(f"/patients/{pat}/claims", headers=rec,
                       json={"claim_number": "CLM-" + uid(), "amount": 10}).status_code == 403


def test_claim_operations_require_auth(client):
    assert client.get("/patients/1/claims").status_code == 401
    assert client.post("/patients/1/claims",
                       json={"claim_number": "X", "amount": 1}).status_code == 401


# ========== الواجهة ==========
def test_chart_ui_markers(client):
    ui = client.get("/").text + client.get("/app.js").text
    assert "openPatientChart" in ui
    assert "CHART_TABS" in ui
    for marker in ("الملف الشخصي", "السجل الطبي", "المواعيد والزيارات",
                   "الفحوصات والوصفات", "الحسابات والتأمين", "المرفقات"):
        assert marker in ui, marker
    assert "/chart" in ui


