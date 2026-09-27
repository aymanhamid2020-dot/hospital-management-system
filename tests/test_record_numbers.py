"""أرقام النظام: رقم ملف المريض يبدأ من 1000 ورقم الموظف من 1.

الرقم مشتقّ من المعرّف (لا استعلام إضافي ولا خطر تزامن)، نظاميّ لا يُقبل
من الخارج، ويُبحث به من قائمة المرضى ودليل الموظفين ولوحة Ctrl+K.
"""
from pathlib import Path

from test_advanced import _register
from test_api import uid


def _new_patient(client, admin, tag):
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مريض {tag}", "date_of_birth": "1990-01-01",
        "gender": "ذكر", "phone": "055" + uid()[:7],
        "email": f"{tag.lower()}@example.com"})
    assert r.status_code in (200, 201), r.text
    return r.json()


# ================= الصيغة =================
def test_numbering_formulas():
    from app.models import (PATIENT_NO_BASE, STAFF_NO_BASE,
                            patient_no_for, staff_no_for)
    assert PATIENT_NO_BASE == 1000
    assert STAFF_NO_BASE == 1
    assert patient_no_for(1) == 1000
    assert patient_no_for(2) == 1001
    assert staff_no_for(1) == 1
    assert staff_no_for(9) == 9
    # رقم ممحو لا يُعاد استخدامه: الفجوات آمنة لأن الرقم دالّة على المعرّف
    assert patient_no_for(3) - patient_no_for(2) == 1


# ================= المريض =================
def test_patient_gets_file_number(client, admin):
    p = _new_patient(client, admin, "FN" + uid()[:6].upper())
    assert p["file_no"] is not None
    assert p["file_no"] == 999 + p["id"]
    assert p["file_no"] >= 1000


def test_file_number_is_system_generated(client, admin):
    """الرقم لا يُقبل من العميل ولا يُمسَّ في التحديث — بحث لا تحرير."""
    tag = "SP" + uid()[:6].upper()
    r = client.post("/patients/", headers=admin, json={
        "full_name": f"مزيف رقم {tag}", "date_of_birth": "1993-05-05",
        "gender": "ذكر", "phone": "057" + uid()[:7],
        "email": f"{tag.lower()}@example.com", "file_no": 99999})
    assert r.status_code in (200, 201), r.text
    p = r.json()
    assert p["file_no"] != 99999
    assert p["file_no"] == 999 + p["id"]

    r = client.put(f"/patients/{p['id']}", headers=admin,
                   json={"full_name": p["full_name"] + " ع", "file_no": 12345})
    assert r.status_code == 200, r.text
    assert r.json()["file_no"] == p["file_no"]


def test_every_listed_patient_has_a_file_number(client, admin):
    rows = client.get("/patients/", headers=admin).json()
    assert rows, "لا مرضى في قاعدة الاختبار؟"
    assert all(r.get("file_no") is not None for r in rows)
    assert all(r["file_no"] == 999 + r["id"] for r in rows)


def test_search_by_file_number(client, admin):
    tag = "FS" + uid()[:6].upper()
    p = _new_patient(client, admin, tag)
    no = str(p["file_no"])

    # لوحة Ctrl+K
    r = client.get("/search/", headers=admin, params={"q": no, "limit": 20})
    assert r.status_code == 200, r.text
    hits = [x for x in r.json()["results"]
            if x["type"] == "patient" and x["id"] == p["id"]]
    assert hits, f"لم يعثر البحث على رقم الملف {no}"
    assert "رقم الملف" in hits[0]["subtitle"]

    # قائمة المرضى (الفلتر الخادمي نفسه)
    r = client.get("/patients/", headers=admin, params={"search": no})
    assert r.status_code == 200, r.text
    assert any(row["id"] == p["id"] for row in r.json())


# ================= الموظف =================
def _new_staff(client, admin, tag):
    r = client.post("/staff/", headers=admin, json={
        "full_name": f"موظف {tag}", "position": "استقبال",
        "phone": "054" + uid()[:7], "email": f"{tag.lower()}@example.com",
        "hire_date": "2024-01-01", "salary": 7000})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_staff_gets_employee_number(client, admin):
    s = _new_staff(client, admin, "EN" + uid()[:6].upper())
    assert s["employee_no"] is not None
    assert s["employee_no"] == s["id"]
    assert s["employee_no"] >= 1
    # أول موظف في قاعدة نظيفة يحمل الرقم1 (الترقيم يبدأ من 1 لا من 0)
    from app.models import Staff  # noqa: F401  (المعنى موثّق في أعلاه)


def test_employee_number_is_system_generated(client, admin):
    tag = "ES" + uid()[:6].upper()
    r = client.post("/staff/", headers=admin, json={
        "full_name": f"مزيف رقم {tag}", "position": "محاسب",
        "phone": "054" + uid()[:7], "email": f"{tag.lower()}@example.com",
        "hire_date": "2024-02-02", "salary": 9000, "employee_no": 777})
    assert r.status_code in (200, 201), r.text
    assert r.json()["employee_no"] != 777


def test_search_by_employee_number(client, admin):
    tag = "SN" + uid()[:6].upper()
    s = _new_staff(client, admin, tag)
    no = str(s["employee_no"])

    r = client.get("/search/", headers=admin, params={"q": no, "limit": 20})
    assert r.status_code == 200, r.text
    hits = [x for x in r.json()["results"]
            if x["type"] == "staff" and x["id"] == s["id"]]
    assert hits, f"لم يعثر البحث على رقم الموظف {no}"
    assert "رقم الموظف" in hits[0]["subtitle"]
    assert hits[0]["view"] == "hr"

    # المستخدم غير المدير لا يرى نتائج الموظفين (شاشة شؤون الموظفين مقيدة به)
    _, _, h_rec = _register(client, prefix="rsn")
    r = client.get("/search/", headers=h_rec, params={"q": no, "limit": 20})
    assert r.status_code == 200, r.text
    assert not [x for x in r.json()["results"] if x["type"] == "staff"]


# ================= الترحيل =================
def test_ensure_columns_backfills_record_numbers():
    """أي رقم ناقص (من مسار قديم/استيراد) يُملأ من المعرّف عند الإقلاع."""
    from app.database import SessionLocal, ensure_columns
    from app.models import Patient, Staff

    db = SessionLocal()
    try:
        pat = db.query(Patient).order_by(Patient.id.desc()).first()
        assert pat is not None
        pid, expected_p = pat.id, pat.file_no
        pat.file_no = None
        staff = db.query(Staff).order_by(Staff.id.desc()).first()
        sid = expected_s = None
        if staff is not None:
            sid, expected_s = staff.id, staff.employee_no
            staff.employee_no = None
        db.commit()
    finally:
        db.close()

    ensure_columns()

    db = SessionLocal()
    try:
        pat = db.query(Patient).get(pid)
        assert pat.file_no == expected_p == 999 + pid
        if sid is not None:
            staff = db.query(Staff).get(sid)
            assert staff.employee_no == expected_s == sid
    finally:
        db.close()


# ================= مؤشرات الواجهة =================
def test_record_number_ui_markers():
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    assert "رقم الملف — يتسلسل من 1000 ويُبحث به" in js
    assert "الرقم الوظيفي" in js
    assert "بحث بالاسم/الهاتف/الهوية/رقم الملف…" in js
    assert "بحث بالاسم أو رقم الموظف…" in js
    assert "p.file_no != null" in js
    assert "s.employee_no != null" in js
    assert "function hrDirectoryHTML(" in js
