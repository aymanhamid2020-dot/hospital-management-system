"""اختبارات البحث العام السريع Ctrl+K (نقطة /search/)."""
from pathlib import Path

from conftest import login
from test_api import uid, _make_doctor, _make_patient
from test_pharmacy import _mk_med


def _tag():
    """وسم فريد يوضع في أسماء الكيانات حتى يطابقه البحث دون لمس بيانات أخرى."""
    return "GS" + uid()[:8].upper()


def _entities(client, admin, tag):
    """مجموعة كيانات بوسم فريد: مريض + دواء + موعد + فاتورة."""
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض {tag}", "date_of_birth": "1990-01-01",
        "gender": "ذكر", "phone": "0555555555",
        "email": f"{tag.lower()}@test.com"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    med = _mk_med(client, admin, name=f"دواء {tag}", code=tag)
    doc = _make_doctor(client, admin, f"{tag.lower()}d@test.com")
    r = client.post("/appointments/", headers=admin, json={
        "patient_id": pid, "doctor_id": doc,
        "appointment_date": "2031-03-03T10:00:00", "reason": f"سبب {tag}"})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post("/invoices/", headers=admin, json={
        "patient_id": pid, "amount": 120.0, "description": f"وصف {tag}"})
    assert r.status_code == 200, r.text
    return pid, med["id"], aid, r.json()["id"]


# ================= التحقق الأساسي =================
def test_search_requires_auth(client):
    assert client.get("/search/", params={"q": "x"}).status_code == 401


def test_search_empty_query_400(client, admin):
    for params in ({"q": "   "}, None):
        r = client.get("/search/", headers=admin, params=params)
        assert r.status_code == 400, r.text
        assert "حرف واحد" in r.json()["detail"]


def test_search_finds_all_entity_types(client, admin):
    tag = _tag()
    pid, mid, aid, invid = _entities(client, admin, tag)
    r = client.get("/search/", headers=admin, params={"q": tag})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == tag
    by = {(x["type"], x["id"]): x for x in body["results"]}
    assert by[("patient", pid)]["view"] == "patients"
    assert by[("medication", mid)]["view"] == "inventory"
    assert by[("appointment", aid)]["view"] == "appointments"
    assert by[("invoice", invid)]["view"] == "invoices"
    p = by[("patient", pid)]
    assert p["title"] == f"مريض {tag}" and p["type_label"] == "مريض"
    assert p["subtitle"] and p["icon"]
    # لا وصفات بعد (لم تُنشأ ضمن المجموعة)
    assert not [x for x in body["results"] if x["type"] == "prescription"]


def test_search_no_results(client, admin):
    r = client.get("/search/", headers=admin, params={"q": "zz-no-such-zzz"})
    assert r.status_code == 200
    assert r.json() == {"query": "zz-no-such-zzz", "results": []}


def test_search_case_insensitive(client, admin):
    name = "ZebraQ" + uid()[:6]
    r = client.post("/patients/", headers=admin, json={
        "full_name": name, "date_of_birth": "1991-01-01", "gender": "ذكر",
        "phone": "0533333333", "email": f"zb_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.get("/search/", headers=admin, params={"q": name.lower()})
    assert r.status_code == 200
    assert any(x["type"] == "patient" and x["id"] == pid
               for x in r.json()["results"])


def test_search_by_numeric_id(client, admin):
    pid, *_ = _entities(client, admin, _tag())
    r = client.get("/search/", headers=admin, params={"q": str(pid)})
    assert r.status_code == 200
    assert any(x["type"] == "patient" and x["id"] == pid
               for x in r.json()["results"])


def test_search_limit_and_validation(client, admin):
    tag = _tag()
    for s in "ABC":
        r = client.post("/patients/", headers=admin, json={
            "full_name": f"مريض {tag}{s}", "date_of_birth": "1990-01-01",
            "gender": "ذكر", "phone": "0544444444",
            "email": f"{tag.lower()}{s}@test.com"})
        assert r.status_code == 200, r.text
    r = client.get("/search/", headers=admin, params={"q": tag, "limit": 2})
    assert r.status_code == 200
    assert len([x for x in r.json()["results"] if x["type"] == "patient"]) <= 2
    # limit خارج النطاق1–20 → تحقّق FastAPI422
    assert client.get("/search/", headers=admin,
                      params={"q": tag, "limit": 0}).status_code == 422
    assert client.get("/search/", headers=admin,
                      params={"q": tag, "limit": 99}).status_code == 422


# ================= قواعد الأدوار على الوصفات =================
def test_search_prescription_doctor_scope(client, admin):
    tag = _tag()
    u = "gsdoc_" + uid()
    email = f"{u}@test.com"
    _make_doctor(client, admin, email)
    client.post("/auth/register", json={
        "username": u, "email": email, "full_name": "طبيب البحث",
        "password": "secret123", "role": "doctor"})
    doc_h = login(client, u, "secret123")

    med = _mk_med(client, admin)
    p1 = _make_patient(client, admin)
    p2 = _make_patient(client, admin)
    # وصفة الطبيب لمرضاه (يُنسبها تلقائيًا إلى سجله)
    r = client.post("/prescriptions/", headers=doc_h, json={
        "patient_id": p1, "items": [{"medication_id": med["id"], "quantity": 1}],
        "notes": f"ملاحظة {tag} الأولى"})
    assert r.status_code == 200, r.text
    rx1 = r.json()["id"]
    # وصفة أخرى بوسم البحث نفسه دون ربط بهذا الطبيب
    r = client.post("/prescriptions/", headers=admin, json={
        "patient_id": p2, "items": [{"medication_id": med["id"], "quantity": 1}],
        "notes": f"ملاحظة {tag} الأخرى"})
    assert r.status_code == 200, r.text
    rx2 = r.json()["id"]

    def _rx_ids(headers):
        r = client.get("/search/", headers=headers, params={"q": tag})
        assert r.status_code == 200, r.text
        return [x["id"] for x in r.json()["results"]
                if x["type"] == "prescription"]

    # الطبيب يرى وصفته فقط
    ids = _rx_ids(doc_h)
    assert rx1 in ids and rx2 not in ids
    # المدير يرى الوصفتين
    ids = _rx_ids(admin)
    assert rx1 in ids and rx2 in ids
    # الاستقبال يرى الوصفتين (نفس قواعد /prescriptions)
    u2 = "gsrec_" + uid()
    client.post("/auth/register", json={
        "username": u2, "email": f"{u2}@test.com", "full_name": "موظف استقبال",
        "password": "secret123"})
    rec_h = login(client, u2, "secret123")
    ids = _rx_ids(rec_h)
    assert rx1 in ids and rx2 in ids


def test_search_unlinked_doctor_sees_no_prescriptions(client, admin):
    tag = _tag()
    u = "gsnd_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "طبيب بلا سجل",
        "password": "secret123", "role": "doctor"})
    h = login(client, u, "secret123")
    med = _mk_med(client, admin)
    p = _make_patient(client, admin)
    r = client.post("/prescriptions/", headers=admin, json={
        "patient_id": p, "items": [{"medication_id": med["id"], "quantity": 1}],
        "notes": f"ملاحظة {tag}"})
    assert r.status_code == 200, r.text

    # طبيب غير مرتبط بسجل → لا وصفات في البحث
    r = client.get("/search/", headers=h, params={"q": tag})
    assert not [x for x in r.json()["results"] if x["type"] == "prescription"]
    # والمدير على البيانات نفسها يجد الوصفة
    r = client.get("/search/", headers=admin, params={"q": tag})
    assert any(x["type"] == "prescription" for x in r.json()["results"])


# ================= مؤشرات الواجهة =================
def test_search_ui_markers():
    root = Path(__file__).resolve().parent.parent
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    css = (root / "static" / "app.css").read_text(encoding="utf-8")
    assert 'id="gsearch-back"' in html
    assert 'id="gsearch-input"' in html
    assert 'id="gsearch-results"' in html
    assert 'onclick="openGSearch()"' in html
    assert "function openGSearch(" in js
    assert "function closeGSearch(" in js
    assert "function gsRun(" in js and "function gsGo(" in js
    assert "/search/?q=" in js
    assert "e.ctrlKey" in js and "e.key === 'k'" in js
    assert "#gsearch-back" in css and ".gs-item" in css and ".gs-empty" in css
