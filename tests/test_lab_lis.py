"""اختبارات نواة المختبر (LIS): دليل الفحوصات + سحب العيّنة والباركود +
إدخال النتيجة ونطاقاتها + الاعتماد والتوقيع الإلكتروني."""
from test_api import uid
from test_advanced import _register


def _mk_test(client, admin, **kw):
    """تعريف فحص في الدليل وإرجاعه"""
    payload = {
        "code": "LIS" + uid()[:6].upper(),
        "name": "فحص " + uid()[:4],
        "category": "lab", "price": 40.0, "fasting_hours": 4,
        "tube_type": "EDTA", "specimen_type": "دم",
        "unit": "g/dL", "ref_min": 12.0, "ref_max": 17.0,
    }
    payload.update(kw)
    r = client.post("/lab-tests/", headers=admin, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض اختبار LIS " + uid()[:5],
        "gender": "ذكر", "phone": "055" + uid()[:7],
        "date_of_birth": "1990-01-01", "email": f"lis{uid()[:6]}@example.com",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


def _mk_order(client, admin, cat, patient, **kw):
    payload = {"patient_id": patient["id"], "test_name": cat["name"],
               "lab_test_id": cat["id"]}
    payload.update(kw)
    r = client.post("/lab-orders/", headers=admin, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _prep_sample(client, admin, oid, specimen="دم", accepted=True, reason=None):
    """سحب العيّنة ثم استلامها"""
    r = client.post(f"/lab-orders/{oid}/collect", headers=admin,
                    json={"specimen_type": specimen})
    assert r.status_code == 200, r.text
    return client.post(f"/lab-orders/{oid}/receive", headers=admin,
                       json={"accepted": accepted, "reason": reason})


# ================= الصلاحيات =================
def test_lab_tests_permissions(client, admin):
    assert client.get("/lab-tests/").status_code == 401
    _, _, h_rec = _register(client, prefix="lisr")
    # القراءة لأي مستخدم مسجّل
    assert client.get("/lab-tests/", headers=h_rec).status_code == 200
    # الكتابة (إضافة/تعديل/حذف) للمدير فقط
    body = {"code": "PERM" + uid()[:5].upper(), "name": "فحص صلاحيات"}
    assert client.post("/lab-tests/", headers=h_rec, json=body).status_code == 403
    assert client.put("/lab-tests/1", headers=h_rec, json={"price": 1}).status_code == 403
    assert client.delete("/lab-tests/1", headers=h_rec).status_code == 403


def test_lab_tests_crud_and_validation(client, admin):
    row = _mk_test(client, admin, fasting_hours=8, tube_type="سيرم")
    assert row["fasting_hours"] == 8 and row["tube_type"] == "سيرم"

    # رمز مكرر
    dup = client.post("/lab-tests/", headers=admin,
                      json={"code": row["code"], "name": "كرر"})
    assert dup.status_code == 409, dup.text
    # نطاق مقلوب
    bad = client.post("/lab-tests/", headers=admin,
                      json={"code": "BAD" + uid()[:5].upper(), "name": "خاطئ",
                            "ref_min": 10, "ref_max": 2})
    assert bad.status_code == 400 and "النطاق" in bad.json()["detail"]

    # تحديث جزئي + تحقق النطاق بعد التعديل
    upd = client.put(f"/lab-tests/{row['id']}", headers=admin, json={"price": 55.0})
    assert upd.status_code == 200 and upd.json()["price"] == 55.0
    assert client.put(f"/lab-tests/{row['id']}", headers=admin,
                      json={"ref_min": 30, "ref_max": 10}).status_code == 400
    assert client.put(f"/lab-tests/{row['id']}", headers=admin,
                      json={"code": row["code"]}).status_code == 200  # كوده الحالي مسموح

    # الفلاتر: بحث + تصنيف + المفعّلة فقط
    hits = client.get("/lab-tests/", headers=admin,
                      params={"search": row["code"]}).json()
    assert any(t["id"] == row["id"] for t in hits)
    labs = client.get("/lab-tests/", headers=admin,
                      params={"category": "lab"}).json()
    assert all(t["category"] == "lab" for t in labs)
    assert client.get("/lab-tests/", headers=admin,
                      params={"category": "xray"}).status_code == 400
    client.put(f"/lab-tests/{row['id']}", headers=admin, json={"active": False})
    active = client.get("/lab-tests/", headers=admin,
                        params={"active_only": True}).json()
    assert not any(t["id"] == row["id"] for t in active)

    # الحذف
    assert client.delete(f"/lab-tests/{row['id']}", headers=admin).status_code == 204
    assert client.get(f"/lab-tests/{row['id']}", headers=admin).status_code in (404, 405)


def test_lab_order_inherits_catalog(client, admin):
    cat = _mk_test(client, admin, price=90.0, ref_min=4.0, ref_max=11.0)
    pat = _mk_patient(client, admin)
    order = _mk_order(client, admin, cat, pat)
    assert order["price"] == 90.0
    assert order["specimen_type"] == "دم" and order["unit"] == "g/dL"
    assert order["ref_min"] == 4.0 and order["ref_max"] == 11.0
    assert order["priority"] == "routine" and order["sample_status"] == "none"

    # دليل غير موجود
    r = client.post("/lab-orders/", headers=admin, json={
        "patient_id": pat["id"], "test_name": "بحث بلا دليل", "lab_test_id": 999999})
    assert r.status_code == 404 and "الدليل" in r.json()["detail"]


# ================= سحب العيّنة والباركود =================
def test_sample_collection_workflow(client, admin):
    cat = _mk_test(client, admin)
    pat = _mk_patient(client, admin)
    order = _mk_order(client, admin, cat, pat)
    oid = order["id"]

    # لا نتيجة قبل سحب العيّنة واستلامها
    early = client.post(f"/lab-orders/{oid}/result", headers=admin,
                        json={"result": "14", "value": 14})
    assert early.status_code == 400 and "العيّنة" in early.json()["detail"]

    got = client.post(f"/lab-orders/{oid}/collect", headers=admin,
                      json={"specimen_type": "دم طرفية"}).json()
    assert got["sample_status"] == "collected"
    assert got["status"] == "in_progress"          # من «مسجّل» إلى «قيد التنفيذ»
    assert got["barcode"] and got["collected_at"] and got["collected_by"]

    # سحب ثانٍ مرفوض
    again = client.post(f"/lab-orders/{oid}/collect", headers=admin,
                        json={"specimen_type": "دم"})
    assert again.status_code == 409

    # الاستلام
    rec = client.post(f"/lab-orders/{oid}/receive", headers=admin,
                      json={"accepted": True})
    assert rec.status_code == 200
    assert rec.json()["sample_status"] == "received" and rec.json()["received_at"]

    # استلام بلا عيّنة مسحوبة
    fresh = _mk_order(client, admin, _mk_test(client, admin), _mk_patient(client, admin))
    assert client.post(f"/lab-orders/{fresh['id']}/receive", headers=admin,
                       json={"accepted": True}).status_code == 400


def test_sample_rejection_records_reason(client, admin):
    cat = _mk_test(client, admin)
    pat = _mk_patient(client, admin)
    oid = _mk_order(client, admin, cat, pat)["id"]
    client.post(f"/lab-orders/{oid}/collect", headers=admin,
                json={"specimen_type": "بول"})
    rec = client.post(f"/lab-orders/{oid}/receive", headers=admin,
                      json={"accepted": False, "reason": "كمية غير كافية"})
    assert rec.status_code == 200
    body = rec.json()
    assert body["sample_status"] == "rejected"
    assert "كمية غير كافية" in body["notes"]


def test_sample_label_pdf(client, admin):
    cat = _mk_test(client, admin)
    pat = _mk_patient(client, admin)
    oid = _mk_order(client, admin, cat, pat)["id"]

    # بلا باركود ⇒ 400
    r = client.get(f"/lab-orders/{oid}/label", headers=admin)
    assert r.status_code == 400

    client.post(f"/lab-orders/{oid}/collect", headers=admin,
                json={"specimen_type": "دم"})
    r = client.get(f"/lab-orders/{oid}/label?copies=3", headers=admin)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    # عدد نسخ خارج الحد المسموح
    assert client.get(f"/lab-orders/{oid}/label?copies=50", headers=admin).status_code == 422
    # بدون ترويسة ⇒ 401
    assert client.get(f"/lab-orders/{oid}/label").status_code == 401


# ================= إدخال النتيجة ونطاقاتها =================
def test_result_entry_flags(client, admin):
    cat = _mk_test(client, admin, ref_min=4.0, ref_max=11.0)

    def result_of(value):
        pat = _mk_patient(client, admin)
        oid = _mk_order(client, admin, cat, pat)["id"]
        _prep_sample(client, admin, oid)
        r = client.post(f"/lab-orders/{oid}/result", headers=admin,
                        json={"result": str(value), "value": value})
        assert r.status_code == 200, r.text
        return r.json()

    inside = result_of(6.0)
    assert not inside["abnormal"] and not inside["critical"]
    assert inside["status"] == "ready" and inside["result_at"]

    mild = result_of(12.5)          # خارج النطاق قليلًا
    assert mild["abnormal"] and not mild["critical"]

    extreme = result_of(1.0)        # أدنى من نصف الحد الأدنى ⇒ حرجة
    assert extreme["abnormal"] and extreme["critical"]

    # إشعار بالقيمة الحرجة
    notes = client.get("/notifications/", headers=admin).json()
    assert any("حرجة" in (n.get("title") or "") for n in notes)


def test_result_inherits_refs_and_unit(client, admin):
    cat = _mk_test(client, admin, ref_min=4.0, ref_max=11.0, unit="x10^3")
    pat = _mk_patient(client, admin)
    oid = _mk_order(client, admin, cat, pat)["id"]
    _prep_sample(client, admin, oid)
    j = client.post(f"/lab-orders/{oid}/result", headers=admin,
                    json={"result": "40", "value": 40}).json()
    assert j["unit"] == "x10^3"
    assert j["ref_min"] == 4.0 and j["ref_max"] == 11.0
    assert j["abnormal"] and j["critical"]      # 40 > 1.5×11 ⇒ حرجة


# ================= الاعتماد والتوقيع =================
def test_verify_requires_result_and_role(client, admin):
    cat = _mk_test(client, admin)
    pat = _mk_patient(client, admin)
    oid = _mk_order(client, admin, cat, pat)["id"]

    # بلا نتيجة ⇒ 400
    r = client.post(f"/lab-orders/{oid}/verify", headers=admin, json={})
    assert r.status_code == 400

    _prep_sample(client, admin, oid)
    client.post(f"/lab-orders/{oid}/result", headers=admin,
                json={"result": "14", "value": 14})

    # مستخدم غير مدير/طبيب ⇒ 403
    _, _, h_rec = _register(client, prefix="liss")
    r = client.post(f"/lab-orders/{oid}/verify", headers=h_rec, json={})
    assert r.status_code == 403

    # الاعتماد يوقّع ويحوّل إلى «مراجَعة»
    r = client.post(f"/lab-orders/{oid}/verify", headers=admin,
                    json={"note": "مراجعة الاستشاري"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "reviewed"
    assert body["verified_by"] and body["verified_at"]

    # نتيجة معتمدة لا تُعدَّل
    r = client.post(f"/lab-orders/{oid}/result", headers=admin,
                    json={"result": "15", "value": 15})
    assert r.status_code == 400


def test_lab_order_new_filters(client, admin):
    cat = _mk_test(client, admin, ref_min=4.0, ref_max=11.0)
    pat = _mk_patient(client, admin)
    stat = _mk_order(client, admin, cat, pat, priority="stat")
    assert stat["priority"] == "stat"
    _prep_sample(client, admin, stat["id"])
    client.post(f"/lab-orders/{stat['id']}/result", headers=admin,
                json={"result": "1", "value": 1})
    plain = _mk_order(client, admin, cat, pat)

    stat_rows = client.get("/lab-orders/", headers=admin,
                           params={"priority": "stat"}).json()
    assert all(o["priority"] == "stat" for o in stat_rows)
    assert any(o["id"] == stat["id"] for o in stat_rows)

    abn = client.get("/lab-orders/", headers=admin,
                     params={"abnormal": True}).json()
    assert all(o["abnormal"] for o in abn)
    assert any(o["id"] == stat["id"] for o in abn)
    assert not any(o["id"] == plain["id"] for o in abn)

    received = client.get("/lab-orders/", headers=admin,
                          params={"sample_status": "received"}).json()
    assert any(o["id"] == stat["id"] for o in received)

    assert client.get("/lab-orders/", headers=admin,
                      params={"priority": "urgent"}).status_code == 400
    assert client.get("/lab-orders/", headers=admin,
                      params={"sample_status": "lost"}).status_code == 400


def test_lab_ui_markers(client):
    """علامات الواجهة: شاشة المختبر تبويبية (LIS/RIS/مشترك) ودوالها معرَّفة."""
    js = client.get("/app.js").text
    for marker in ("LAB_TAB", "LAB_TABS", "setLabTab", "lab-tests",
                   "collect", "receive", "verify", "/label"):
        assert marker in js, f"علامة مفقودة في app.js: {marker}"
