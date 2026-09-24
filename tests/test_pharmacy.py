"""اختبارات تطوير الصيدلية:
رفض المنتهي + الصرف الجماعي all-or-nothing + الإرجاع واستثناؤه من الحسابات
+ الإتلاف + الإحصاءات/اقتراحات الطلب + الوصفات الطبية + التقارير الجديدة
+ مؤشرات واجهة الصيدلية.
"""
from datetime import datetime, timedelta

from conftest import login
from test_api import uid, _make_doctor, _make_patient


def _mk_med(client, admin, **kw):
    """إنشاء دواء فريد وإرجاعه."""
    payload = {
        "code": "PH" + uid()[:7].upper(),
        "name": "دواء صيدلية " + uid()[:5],
        "quantity": 20, "unit": "علبة", "price": 10.0, "min_quantity": 5,
    }
    payload.update(kw)
    r = client.post("/medications/", headers=admin, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _med(client, admin, med_id):
    return client.get(f"/medications/{med_id}", headers=admin).json()


def _receptionist(client):
    u = "recph_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "موظف استقبال",
        "password": "secret123"})
    return login(client, u, "secret123")


def _doctor_user(client, admin, prefix):
    """سجل طبيب + حساب مستخدم role=doctor بنفس البريد."""
    u = f"{prefix}_{uid()}"
    email = f"{u}@test.com"
    doc_id = _make_doctor(client, admin, email)
    client.post("/auth/register", json={
        "username": u, "email": email, "full_name": "طبيب الصيدلية",
        "password": "secret123", "role": "doctor"})
    return doc_id, login(client, u, "secret123")


# ================= رفض صرف المنتهي =================
def test_expired_single_dispense_rejected(client, admin):
    med = _mk_med(client, admin,
                  expiry_date=(datetime.now() - timedelta(days=3)).isoformat())
    pat = _make_patient(client, admin)
    before = _med(client, admin, med["id"])["quantity"]

    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat, "quantity": 1})
    assert r.status_code == 400, r.text
    assert "منتهي الصلاحية" in r.json()["detail"]
    assert _med(client, admin, med["id"])["quantity"] == before


def test_expired_batch_and_rx_rejected(client, admin):
    med = _mk_med(client, admin,
                  expiry_date=(datetime.now() - timedelta(days=1)).isoformat())
    pat = _make_patient(client, admin)
    before = _med(client, admin, med["id"])["quantity"]

    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat, "items": [{"medication_id": med["id"], "quantity": 1}]})
    assert r.status_code == 400 and "منتهي الصلاحية" in r.json()["detail"]
    assert _med(client, admin, med["id"])["quantity"] == before

    r = client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": med["id"], "quantity": 1}]})
    assert r.status_code == 200
    r = client.post(f"/prescriptions/{r.json()['id']}/dispense", headers=admin,
                    json={})
    assert r.status_code == 400 and "منتهي الصلاحية" in r.json()["detail"]
    assert _med(client, admin, med["id"])["quantity"] == before


# ================= الصرف الجماعي =================
def test_batch_dispense_happy_path(client, admin):
    m1 = _mk_med(client, admin, quantity=15, price=8.0)
    m2 = _mk_med(client, admin, quantity=30, price=4.0)
    pat = _make_patient(client, admin)

    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat, "notes": "سلة اختبار",
        "items": [
            {"medication_id": m1["id"], "quantity": 3,
             "dosage": "قرص بعد الأكل", "frequency": "3 مرات يوميًا",
             "duration": "5 أيام", "instructions": "لا تتجاوز الجرعة"},
            {"medication_id": m2["id"], "quantity": 10},
        ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["total"] == 3 * 8.0 + 10 * 4.0
    assert len(body["dispenses"]) == 2

    # خفض المخزون
    assert _med(client, admin, m1["id"])["quantity"] == 12
    assert _med(client, admin, m2["id"])["quantity"] == 20
    # حقول التوجيه محفوظة على البنود المصروفة
    d1 = next(d for d in body["dispenses"] if d["medication_id"] == m1["id"])
    assert d1["dosage"] == "قرص بعد الأكل"
    assert d1["frequency"] == "3 مرات يوميًا"
    assert d1["duration"] == "5 أيام"
    assert d1["instructions"] == "لا تتجاوز الجرعة"
    assert d1["dispensed_by"] == "admin"
    # حركات صادر سُجّلت
    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": m1["id"], "type": "out"}).json()
    assert any(x["change"] == -3 for x in mv)


def test_batch_is_all_or_nothing(client, admin):
    ok_med = _mk_med(client, admin, quantity=10)
    poor_med = _mk_med(client, admin, quantity=2)
    pat = _make_patient(client, admin)
    before_ok = _med(client, admin, ok_med["id"])["quantity"]
    before_poor = _med(client, admin, poor_med["id"])["quantity"]

    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": ok_med["id"], "quantity": 2},
                  {"medication_id": poor_med["id"], "quantity": 9}]})
    assert r.status_code == 400, r.text
    assert "تتجاوز المتوفر" in r.json()["detail"]
    # لا تعديل نصفي: المخزون كما كان ولا صرف جديد
    assert _med(client, admin, ok_med["id"])["quantity"] == before_ok
    assert _med(client, admin, poor_med["id"])["quantity"] == before_poor
    sales = client.get("/accounts/sales", headers=admin,
                       params={"patient_id": pat}).json()
    assert sales == []


def test_batch_aggregates_duplicate_items(client, admin):
    med = _mk_med(client, admin, quantity=5)
    pat = _make_patient(client, admin)
    before = _med(client, admin, med["id"])["quantity"]

    # نفس الدواء مكرر مجموعه 9 > 5 ⇒ مرفوض قبل أي تعديل
    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": med["id"], "quantity": 5},
                  {"medication_id": med["id"], "quantity": 4}]})
    assert r.status_code == 400
    assert _med(client, admin, med["id"])["quantity"] == before

    # ومجموعها ضمن المتوفر ⇒ يُصرف (سطران = عمليتان)
    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": med["id"], "quantity": 3},
                  {"medication_id": med["id"], "quantity": 2}]})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    assert _med(client, admin, med["id"])["quantity"] == before - 5


def test_batch_validations(client, admin):
    med = _mk_med(client, admin)
    pat = _make_patient(client, admin)

    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat, "items": []})
    assert r.status_code == 422
    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": 999999,
        "items": [{"medication_id": med["id"], "quantity": 1}]})
    assert r.status_code == 404
    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": 999999, "quantity": 1}]})
    assert r.status_code == 404
    r = client.post("/dispenses/batch", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": med["id"], "quantity": 0}]})
    assert r.status_code == 422
    # الحماية: 401 دون توكن
    assert client.post("/dispenses/batch",
                       json={"patient_id": pat, "items": []}).status_code == 401


# ================= جرعة الصرف والإيصال =================
def test_single_dispense_dosage_fields_and_receipt(client, admin):
    med = _mk_med(client, admin, quantity=10, price=6.0)
    pat = _make_patient(client, admin)
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat, "quantity": 2,
        "dosage": "ملعقة كبيرة", "frequency": "مرة يوميًا",
        "duration": "3 أيام", "instructions": "بعد الوجبة"})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    assert r.json()["dosage"] == "ملعقة كبيرة"
    assert r.json()["total_price"] == 12.0

    html = client.get(f"/accounts/sales/{did}/receipt", headers=admin).text
    assert "ملعقة كبيرة" in html
    assert "مرة يوميًا" in html
    assert "بعد الوجبة" in html
    # لغة خاطئة ⇒ 400
    assert client.get(f"/accounts/sales/{did}/receipt",
                      headers=admin, params={"lang": "fr"}).status_code == 400


# ================= الإرجاع =================
def test_return_flow_restores_stock(client, admin):
    med = _mk_med(client, admin, quantity=10, price=5.0)
    pat = _make_patient(client, admin)
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat, "quantity": 4})
    did = r.json()["id"]
    assert _med(client, admin, med["id"])["quantity"] == 6

    # سبب إلزامي
    assert client.post(f"/dispenses/{did}/return", headers=admin,
                       json={}).status_code == 422
    assert client.post(f"/dispenses/{did}/return", headers=admin,
                       json={"reason": "   "}).status_code == 422

    r = client.post(f"/dispenses/{did}/return", headers=admin,
                    json={"reason": "وصفة خاطئة"})
    assert r.status_code == 200, r.text
    assert r.json()["returned_at"] is not None
    assert r.json()["return_reason"] == "وصفة خاطئة"
    assert r.json()["returned_by"] == "admin"
    # الكمية عادت + حركة return سُجّلت
    assert _med(client, admin, med["id"])["quantity"] == 10
    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"], "type": "return"}).json()
    assert any(x["change"] == 4 for x in mv)
    # إرجاع مكرر ⇒ 409
    r = client.post(f"/dispenses/{did}/return", headers=admin,
                    json={"reason": "مرة أخرى"})
    assert r.status_code == 409
    # غير موجود ⇒ 404
    assert client.post("/dispenses/999999/return", headers=admin,
                       json={"reason": "x"}).status_code == 404
    # الإيصال يبين المرتجع
    html = client.get(f"/accounts/sales/{did}/receipt", headers=admin).text
    assert "مرتجع" in html


def test_return_excluded_from_accounts(client, admin):
    med = _mk_med(client, admin, quantity=20, price=7.0)
    pat = _make_patient(client, admin)
    before_count = client.get("/accounts/summary",
                              headers=admin).json()["count"]

    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat, "quantity": 3})
    did = r.json()["id"]
    sales = client.get("/accounts/sales", headers=admin,
                       params={"patient_id": pat}).json()
    assert [s["id"] for s in sales] == [did]
    assert client.get("/accounts/summary",
                      headers=admin).json()["count"] == before_count + 1

    # المريض مدين قبل الإرجاع
    debtors = client.get("/accounts/debtors", headers=admin).json()
    assert any(d["patient_id"] == pat for d in debtors)

    assert client.post(f"/dispenses/{did}/return", headers=admin,
                       json={"reason": "خطأ في الوصفة"}).status_code == 200

    # استُثني من كل استعلامات الحسابات
    sales = client.get("/accounts/sales", headers=admin,
                       params={"patient_id": pat}).json()
    assert sales == []
    assert client.get("/accounts/summary",
                      headers=admin).json()["count"] == before_count
    debtors = client.get("/accounts/debtors", headers=admin).json()
    assert not any(d["patient_id"] == pat for d in debtors)
    statement = client.get(f"/accounts/statement/{pat}", headers=admin).json()
    assert statement["sales"] == []
    assert statement["totals"]["sales_total"] == 0
    # تسديد المرتجع ممنوع
    r = client.put(f"/accounts/sales/{did}/payment", headers=admin,
                   json={"paid_amount": 1, "payment_method": "cash"})
    assert r.status_code == 409
    assert "لا يمكن تسجيل دفعة" in r.json()["detail"]


# ================= الإتلاف =================
def test_dispose_flow_and_permissions(client, admin):
    h_rec = _receptionist(client)
    med = _mk_med(client, admin, quantity=12)
    before = 12

    # غير مدير ⇒ 403
    assert client.post(f"/inventory/{med['id']}/dispose", headers=h_rec,
                       json={"quantity": 1}).status_code == 403
    # دون توكن ⇒ 401
    assert client.post(f"/inventory/{med['id']}/dispose",
                       json={"quantity": 1}).status_code == 401
    # كمية غير صحيحة
    assert client.post(f"/inventory/{med['id']}/dispose", headers=admin,
                       json={"quantity": 0}).status_code == 422
    assert client.post(f"/inventory/{med['id']}/dispose", headers=admin,
                       json={"quantity": 999}).status_code == 400
    assert _med(client, admin, med["id"])["quantity"] == before

    r = client.post(f"/inventory/{med['id']}/dispose", headers=admin,
                    json={"quantity": 5, "note": "منتهي الصلاحية"})
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == before - 5
    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"], "type": "disposal"}).json()
    assert any(x["change"] == -5 and "منتهي" in (x["note"] or "") for x in mv)
    # نوع الحركة الجديدة مقبول في الفلتر (وغير المعروف ما زال 400)
    assert client.get("/inventory/movements", headers=admin,
                      params={"type": "return"}).status_code == 200
    assert client.get("/inventory/movements", headers=admin,
                      params={"type": "bogus"}).status_code == 400


# ================= الإحصاءات واقتراحات الطلب =================
def test_stats_endpoint(client, admin):
    med = _mk_med(client, admin, quantity=50, price=9.0)
    pat = _make_patient(client, admin)

    r = client.get("/pharmacy/stats", headers=admin)
    assert r.status_code == 200, r.text
    base = r.json()
    for key in ("period", "dispense_count", "units", "revenue", "paid",
                "outstanding", "inventory_value", "low", "out", "expired",
                "expiring", "top_medications", "daily"):
        assert key in base, key

    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat, "quantity": 4})
    did = r.json()["id"]
    after = client.get("/pharmacy/stats", headers=admin).json()
    assert after["dispense_count"] == base["dispense_count"] + 1
    assert after["units"] == base["units"] + 4
    assert round(after["revenue"] - base["revenue"], 2) == 36.0
    assert any(t["medication_id"] == med["id"] and t["units"] == 4
               for t in after["top_medications"])
    assert after["daily"]

    # الإرجاع يستثني من الإحصاء
    assert client.post(f"/dispenses/{did}/return", headers=admin,
                       json={"reason": "إحصاء"}).status_code == 200
    back = client.get("/pharmacy/stats", headers=admin).json()
    assert back["dispense_count"] == base["dispense_count"]
    assert round(back["revenue"] - base["revenue"], 2) == 0.0

    # صيغة تاريخ خاطئة ⇒ 400
    r = client.get("/pharmacy/stats", headers=admin,
                   params={"from_date": "bad"})
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"]
    # 401 دون توكن
    assert client.get("/pharmacy/stats").status_code == 401


def test_reorder_suggestions(client, admin):
    low = _mk_med(client, admin, quantity=2, min_quantity=10, price=3.0)
    ok = _mk_med(client, admin, quantity=100, min_quantity=5)

    r = client.get("/pharmacy/reorder", headers=admin)
    assert r.status_code == 200, r.text
    rows = r.json()
    low_row = next((x for x in rows if x["medication_id"] == low["id"]), None)
    assert low_row is not None, "الصنف المنخفض يجب أن يظهر في الاقتراحات"
    # المقترح = (متوسط يومي × 30) + حد التنبيه − الرصيد = 0 + 10 − 2
    assert low_row["suggested_qty"] >= 8
    assert low_row["avg_per_day"] == 0
    assert low_row["days_cover"] is None
    assert low_row["suggested_cost"] == low_row["suggested_qty"] * 3.0
    assert not any(x["medication_id"] == ok["id"] for x in rows)

    # نافذة الأيام: 1–365 فقط
    assert client.get("/pharmacy/reorder", headers=admin,
                      params={"days": 0}).status_code == 422
    assert client.get("/pharmacy/reorder", headers=admin,
                      params={"days": 400}).status_code == 422
    assert client.get("/pharmacy/reorder").status_code == 401


# ================= الوصفات الطبية =================
def test_prescription_create_permissions(client, admin):
    pat = _make_patient(client, admin)
    med = _mk_med(client, admin)
    body = {"patient_id": pat,
            "items": [{"medication_id": med["id"], "quantity": 2,
                       "dosage": "قرص"}]}

    # موظف استقبال ⇒ 403 (إنشاء فقط)
    h_rec = _receptionist(client)
    r = client.post("/prescriptions/", headers=h_rec, json=body)
    assert r.status_code == 403
    assert client.get("/prescriptions/", headers=h_rec).status_code == 200
    assert client.post("/prescriptions/").status_code == 401

    # المدير ينشئ وصفة
    r = client.post("/prescriptions/", headers=admin, json=body)
    assert r.status_code == 200, r.text
    rx = r.json()
    assert rx["status"] == "PENDING"
    assert rx["created_by"] == "admin"
    assert rx["items"][0]["dispensed_quantity"] == 0
    assert rx["items"][0]["remaining"] == 2
    assert rx["items"][0]["dosage"] == "قرص"

    # طبيب مرتبط بنفس البريد ⇒ يُنسب لنفسه
    doc_id, doc_h = _doctor_user(client, admin, "rxdr")
    r = client.post("/prescriptions/", headers=doc_h, json=body)
    assert r.status_code == 200 and r.json()["doctor_id"] == doc_id

    # طبيب بلا سجل طبيب مرتبط ⇒ 403
    u = "rxnl_" + uid()
    client.post("/auth/register", json={
        "username": u, "email": f"{u}@test.com", "full_name": "بلا سجل",
        "password": "secret123", "role": "doctor"})
    h_nl = login(client, u, "secret123")
    assert client.post("/prescriptions/", headers=h_nl, json=body).status_code == 403

    # بيانات خاطئة
    assert client.post("/prescriptions/", headers=admin,
                       json={"patient_id": 999999,
                             "items": [{"medication_id": med["id"],
                                        "quantity": 1}]}).status_code == 404
    assert client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat, "items": []}).status_code == 422
    assert client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": 999999, "quantity": 1}]}).status_code == 404


def test_prescription_list_filters_and_scoping(client, admin):
    doc_id, doc_h = _doctor_user(client, admin, "rxsc")
    pat = _make_patient(client, admin)
    med = _mk_med(client, admin)
    body = {"patient_id": pat,
            "items": [{"medication_id": med["id"], "quantity": 1}]}
    own = client.post("/prescriptions/", headers=doc_h, json=body).json()
    other = client.post("/prescriptions/", headers=admin, json=body).json()

    # الطبيب يرى وصفاته فقط
    ids = [r["id"] for r in client.get("/prescriptions/",
                                       headers=doc_h).json()]
    assert own["id"] in ids and other["id"] not in ids
    # وصفة طبيب آخر ⇒ 404 (غير مدرجة لديه) / التفاصيل 403
    r = client.get(f"/prescriptions/{other['id']}", headers=doc_h)
    assert r.status_code == 403

    # فلترة الحالة + صيغة خاطئة
    r = client.get("/prescriptions", headers=admin,
                   params={"status": "PENDING"})
    assert r.status_code == 200 and own["id"] in [x["id"] for x in r.json()]
    r = client.get("/prescriptions", headers=admin, params={"status": "bogus"})
    assert r.status_code == 400
    # بحث بالpatient
    rows = client.get("/prescriptions", headers=admin,
                      params={"patient_id": pat}).json()
    assert {x["id"] for x in rows} >= {own["id"], other["id"]}
    # غير موجود
    assert client.get("/prescriptions/999999", headers=admin).status_code == 404


def test_prescription_full_dispense(client, admin):
    med = _mk_med(client, admin, quantity=25, price=5.0)
    pat = _make_patient(client, admin)
    rx = client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat, "notes": "بعد الفحص",
        "items": [{"medication_id": med["id"], "quantity": 5,
                   "dosage": "قرص", "frequency": "مرتان", "duration": "يومان"}]
    }).json()

    r = client.post(f"/prescriptions/{rx['id']}/dispense", headers=admin,
                    json={})
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["prescription_id"] == rx["id"]
    assert entries[0]["dosage"] == "قرص"
    assert _med(client, admin, med["id"])["quantity"] == 20

    after = client.get(f"/prescriptions/{rx['id']}", headers=admin).json()
    assert after["status"] == "DISPENSED"
    assert after["dispensed_at"] is not None
    assert after["items"][0]["dispensed_quantity"] == 5
    assert after["items"][0]["remaining"] == 0

    # صرف مكرر بلا معلَّق ⇒ 409
    r = client.post(f"/prescriptions/{rx['id']}/dispense", headers=admin,
                    json={})
    assert r.status_code == 409
    # لا يمكن إلغاء وصفة صُرفت
    r = client.put(f"/prescriptions/{rx['id']}", headers=admin,
                   json={"status": "CANCELLED"})
    assert r.status_code == 409
    # لا يمكن حذف وصفة صُرفت (للمدير فقط أصلًا)
    assert client.delete(f"/prescriptions/{rx['id']}",
                         headers=admin).status_code == 409


def test_prescription_partial_and_return_recompute(client, admin):
    m1 = _mk_med(client, admin, quantity=30)
    m2 = _mk_med(client, admin, quantity=30)
    pat = _make_patient(client, admin)
    rx = client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": m1["id"], "quantity": 2},
                  {"medication_id": m2["id"], "quantity": 3}]}).json()

    # صرف بند واحد فقط (item_ids) ⇒ PARTIAL
    item1 = rx["items"][0]["id"]
    r = client.post(f"/prescriptions/{rx['id']}/dispense", headers=admin,
                    json={"item_ids": [item1]})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    after = client.get(f"/prescriptions/{rx['id']}", headers=admin).json()
    assert after["status"] == "PARTIAL"
    assert after["items"][0]["dispensed_quantity"] == 2
    assert after["items"][1]["dispensed_quantity"] == 0

    # بنود لا تابعة للوصفة ⇒ 404
    r = client.post(f"/prescriptions/{rx['id']}/dispense", headers=admin,
                    json={"item_ids": [999999]})
    assert r.status_code == 404

    # إرجاع الصرف يُرجع الكمية ويعيد احتساب الحالة
    # جلب الصرف المرتبط بالوصفة من سجل الحسابات
    rows = client.get("/accounts/sales", headers=admin,
                      params={"patient_id": pat}).json()
    target = next(d for d in rows if d["prescription_id"] == rx["id"])
    r = client.post(f"/dispenses/{target['id']}/return", headers=admin,
                    json={"reason": "جرعة خاطئة"})
    assert r.status_code == 200
    after = client.get(f"/prescriptions/{rx['id']}", headers=admin).json()
    assert after["items"][0]["dispensed_quantity"] == 0
    assert after["status"] == "PENDING"  # لم يبقَ أي صرف


def test_prescription_stock_short_is_atomic(client, admin):
    good = _mk_med(client, admin, quantity=20)
    poor = _mk_med(client, admin, quantity=1)
    pat = _make_patient(client, admin)
    rx = client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": good["id"], "quantity": 2},
                  {"medication_id": poor["id"], "quantity": 8}]}).json()
    before = _med(client, admin, good["id"])["quantity"]

    r = client.post(f"/prescriptions/{rx['id']}/dispense", headers=admin,
                    json={})
    assert r.status_code == 400 and "تتجاوز المتوفر" in r.json()["detail"]
    assert _med(client, admin, good["id"])["quantity"] == before
    after = client.get(f"/prescriptions/{rx['id']}", headers=admin).json()
    assert after["status"] == "PENDING"
    assert all(i["dispensed_quantity"] == 0 for i in after["items"])


def test_prescription_cancel_update_delete(client, admin):
    h_rec = _receptionist(client)
    med = _mk_med(client, admin)
    pat = _make_patient(client, admin)
    rx = client.post("/prescriptions/", headers=admin, json={
        "patient_id": pat,
        "items": [{"medication_id": med["id"], "quantity": 1}]}).json()

    # تعديل: صلاحيات وصيغة الحالة
    assert client.put(f"/prescriptions/{rx['id']}", headers=h_rec,
                      json={"notes": "x"}).status_code == 403
    r = client.put(f"/prescriptions/{rx['id']}", headers=admin,
                   json={"status": "DISPENSED"})
    assert r.status_code == 400
    r = client.put(f"/prescriptions/{rx['id']}", headers=admin,
                   json={"status": "bogus"})
    assert r.status_code == 400
    r = client.put(f"/prescriptions/{rx['id']}", headers=admin,
                   json={"status": "CANCELLED", "notes": "ملغاة بالخطأ"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"

    # وصفة ملغاة لا تُصرف
    r = client.post(f"/prescriptions/{rx['id']}/dispense", headers=admin,
                    json={})
    assert r.status_code == 409

    # الرجوع للانتظار ثم الحذف
    r = client.put(f"/prescriptions/{rx['id']}", headers=admin,
                   json={"status": "PENDING"})
    assert r.status_code == 200 and r.json()["status"] == "PENDING"
    assert client.delete(f"/prescriptions/{rx['id']}",
                         headers=h_rec).status_code == 403
    assert client.delete(f"/prescriptions/{rx['id']}",
                         headers=admin).status_code == 204
    assert client.get(f"/prescriptions/{rx['id']}",
                      headers=admin).status_code == 404
    assert client.delete("/prescriptions/999999",
                         headers=admin).status_code == 404


# ================= التقارير الجديدة =================
def test_pharmacy_stats_reports(client, admin):
    h_rec = _receptionist(client)
    # PDF الإحصاءات
    r = client.get("/reports/pharmacy/stats/pdf", headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert client.get("/reports/pharmacy/stats/pdf",
                      headers=h_rec).status_code == 403
    assert client.get("/reports/pharmacy/stats/pdf",
                      headers=admin, params={"lang": "fr"}).status_code == 400
    assert client.get("/reports/pharmacy/stats/pdf", headers=admin,
                      params={"from_date": "nope"}).status_code == 400
    r = client.get("/reports/pharmacy/stats/pdf", headers=admin,
                   params={"lang": "en"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"

    # CSV الإحصاءات
    r = client.get("/reports/pharmacy/stats/csv", headers=admin)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "الإيراد" in text and "القسم" in text
    assert client.get("/reports/pharmacy/stats/csv",
                      headers=h_rec).status_code == 403
    assert client.get("/reports/pharmacy/stats/csv",
                      headers=admin, params={"to_date": "x"}).status_code == 400


def test_pharmacy_csv_sections_and_accounts_exclusion(client, admin):
    # قسم الإتلاف/الإرجاع
    med = _mk_med(client, admin, quantity=8)
    pat = _make_patient(client, admin)
    r = client.post(f"/inventory/{med['id']}/dispose", headers=admin,
                    json={"quantity": 2, "note": "اختبار الإتلاف"})
    assert r.status_code == 200

    r = client.get("/reports/pharmacy/csv", headers=admin,
                   params={"section": "disposals"})
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "النوع" in text and "إتلاف" in text

    # قسم الصرف يحمل أعمدة الجرعة وحالة الدفع
    r = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat, "quantity": 1,
        "dosage": "دواء الاختبارCSV"})
    did = r.json()["id"]
    r = client.get("/reports/pharmacy/csv", headers=admin,
                   params={"section": "dispenses"})
    text = r.content.decode("utf-8-sig")
    assert "الجرعة" in text and "حالة الدفع" in text and "المرتجع" in text
    assert "دواء الاختبارCSV" in text

    # الإرجاع يستثني من سجل المبيعات CSV
    assert client.post(f"/dispenses/{did}/return", headers=admin,
                       json={"reason": "لاختبار CSV"}).status_code == 200
    r = client.get("/reports/accounts/sales/csv", headers=admin)
    assert r.status_code == 200
    assert "دواء الاختبارCSV" not in r.content.decode("utf-8-sig")

    # قسم خاطئ ما زال 400
    assert client.get("/reports/pharmacy/csv", headers=admin,
                      params={"section": "bad"}).status_code == 400


# ================= مؤشرات الواجهة =================
def test_ui_pharmacy_markers():
    """واجهة الصيدلية تحمل عناصر السلة والوصفات والإرجاع/الإتلاف."""
    import pathlib
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "static" / "app.js").read_text(encoding="utf-8")
    for marker in ("/dispenses/batch", "basket-rows", "basketRowHTML(",
                   "dispenseBatch(", "quickFind(", "filterPharmacy(",
                   "returnDispense(", "disposeMed(", "dispenseRx(",
                   "createRx(", "restockSuggested(",
                   "/pharmacy/stats", "/pharmacy/reorder",
                   "/prescriptions/", "/dispenses/' + id + '/return",
                   "/inventory/' + id + '/dispose",
                   "/reports/pharmacy/stats/pdf",
                   "/reports/pharmacy/stats/csv",
                   "section=disposals", "async pharmacy(main)",
                   "/prescriptions/${r.id}/pdf", "section=reorder",
                   "f-rx-status", "function filterRxRows(",
                   "data-rxstatus"):
        assert marker in js, f"مؤشر مفقود في الواجهة: {marker}"
    assert "dispenseMed(" not in js, "الدالة القديمة dispenseMed بقيت حية"


# ================= طباعة الوصفة PDF =================
def test_prescription_print_pdf(client, admin):
    """طباعة وصفة PDF: عربي/إنجليزي + تحقق lang والملكية والمصادقة."""
    med = _mk_med(client, admin)
    pat = _make_patient(client, admin)
    _, doc_h = _doctor_user(client, admin, "rxpr")
    r = client.post("/prescriptions/", headers=doc_h, json={
        "patient_id": pat, "notes": "اختبار الطباعة",
        "items": [{"medication_id": med["id"], "quantity": 5,
                   "dosage": "قرص بعد الأكل", "frequency": "مرتين يوميًا",
                   "duration": "3 أيام", "instructions": "مع الوجبات"}]})
    assert r.status_code == 200, r.text
    rx_id = r.json()["id"]

    # الطبيب مالك الوصفة يطبعها — عربي
    r = client.get(f"/prescriptions/{rx_id}/pdf", headers=doc_h)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert f"prescription_{rx_id}.pdf" in r.headers.get("content-disposition", "")

    # النسخة الإنجليزية باسم مختلف
    r = client.get(f"/prescriptions/{rx_id}/pdf", headers=admin,
                   params={"lang": "en"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert (f"prescription_{rx_id}_en.pdf"
            in r.headers.get("content-disposition", ""))

    # lang خاطئ + طبيب آخر ممنوع + بلا توكن + غير موجود
    assert client.get(f"/prescriptions/{rx_id}/pdf", headers=admin,
                      params={"lang": "fr"}).status_code == 400
    _, other_h = _doctor_user(client, admin, "rxot")
    assert client.get(f"/prescriptions/{rx_id}/pdf",
                      headers=other_h).status_code == 403
    assert client.get(f"/prescriptions/{rx_id}/pdf").status_code == 401
    assert client.get("/prescriptions/999999/pdf",
                      headers=admin).status_code == 404


# ================= CSV اقتراحات الطلب =================
def test_reorder_csv_section(client, admin):
    """section=reorder في CSV الصيدلية (للمدير) + تغذية /pharmacy/reorder."""
    med = _mk_med(client, admin, quantity=2, min_quantity=10)

    r = client.get("/reports/pharmacy/csv", headers=admin,
                   params={"section": "reorder"})
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "المقترح شراءه" in text and "التكلفة المقترحة" in text
    assert med["code"] in text

    r = client.get("/pharmacy/reorder", headers=admin)
    assert r.status_code == 200
    row = next((x for x in r.json() if x["code"] == med["code"]), None)
    assert row is not None and row["suggested_qty"] >= 8

    assert client.get("/reports/pharmacy/csv", headers=admin,
                      params={"section": "nope"}).status_code == 400
    h_rec = _receptionist(client)
    assert client.get("/reports/pharmacy/csv", headers=h_rec,
                      params={"section": "reorder"}).status_code == 403
