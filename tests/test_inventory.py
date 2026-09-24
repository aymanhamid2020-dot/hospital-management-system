"""اختبارات قسم المخزون — القيم والحالة والفلاتر والتوريد والجرد والحركات."""
from datetime import datetime, timedelta

from test_api import uid
from test_advanced import _register


def _mk_med(client, admin, **kw):
    """إنشاء دواء فريد وإرجاعه"""
    payload = {
        "code": "INV" + uid()[:6].upper(),
        "name": "دواء مخزون " + uid()[:4],
        "quantity": 10, "unit": "علبة", "price": 5.0, "min_quantity": 5,
    }
    payload.update(kw)
    r = client.post("/medications/", headers=admin, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _find(items, med_id):
    return next(x for x in items if x["id"] == med_id)


# ================= الصلاحيات =================
def test_inventory_requires_token(client):
    for path in ("/inventory/", "/inventory/summary", "/inventory/movements"):
        assert client.get(path).status_code == 401, path
    assert client.post("/inventory/1/restock", json={"quantity": 1}).status_code == 401
    assert client.put("/inventory/1/adjust", json={"quantity": 1}).status_code == 401


def test_inventory_write_requires_admin(client, admin):
    _, _, h_rec = _register(client, prefix="invs")
    med = _mk_med(client, admin)
    # القراءة مسموحة لأي مستخدم مسجّل
    for path in ("/inventory/", "/inventory/summary", "/inventory/movements"):
        assert client.get(path, headers=h_rec).status_code == 200, path
    # الكتابة للمدير فقط
    r = client.post(f"/inventory/{med['id']}/restock", headers=h_rec, json={"quantity": 5})
    assert r.status_code == 403, r.text
    r = client.put(f"/inventory/{med['id']}/adjust", headers=h_rec, json={"quantity": 5})
    assert r.status_code == 403, r.text


# ================= القيم والحالة =================
def test_inventory_values_and_statuses(client, admin):
    ok_med = _mk_med(client, admin, quantity=10, price=4.5, min_quantity=5)
    low_med = _mk_med(client, admin, quantity=3, price=2.0, min_quantity=5)
    out_med = _mk_med(client, admin, quantity=0, price=9.0, min_quantity=5)
    expired_med = _mk_med(
        client, admin, quantity=7, price=3.0, min_quantity=5,
        expiry_date=(datetime.now() - timedelta(days=1)).isoformat())
    expiring_med = _mk_med(
        client, admin, quantity=7, price=3.0, min_quantity=5,
        expiry_date=(datetime.now() + timedelta(days=10)).isoformat())

    items = client.get("/inventory/", headers=admin).json()

    a = _find(items, ok_med["id"])
    assert a["status"] == "ok" and a["value"] == 45.0 and a["days_to_expiry"] is None

    b = _find(items, low_med["id"])
    assert b["status"] == "low" and b["value"] == 6.0

    c_ = _find(items, out_med["id"])
    assert c_["status"] == "out" and c_["value"] == 0.0

    d = _find(items, expired_med["id"])
    assert d["status"] == "expired" and d["days_to_expiry"] < 0

    e = _find(items, expiring_med["id"])
    assert e["status"] == "expiring" and 0 <= e["days_to_expiry"] <= 10


def test_inventory_summary_counts(client, admin):
    _mk_med(client, admin, quantity=20, price=10.0, min_quantity=5)
    s = client.get("/inventory/summary", headers=admin).json()
    for key in ("items", "units", "total_value", "low", "out",
                "expired", "expiring", "expiring_days"):
        assert key in s, key
    assert s["items"] >= 1 and s["units"] >= 20
    assert s["total_value"] >= 200.0
    assert s["expiring_days"] == 30


# ================= الفلاتر =================
def test_inventory_filters(client, admin):
    med = _mk_med(client, admin, name="فلتر خاص " + uid()[:6],
                  quantity=2, price=1.0, min_quantity=5)
    items = client.get("/inventory/", headers=admin,
                       params={"search": med["code"]}).json()
    assert [x["id"] for x in items] == [med["id"]]
    assert items[0]["status"] == "low"

    # فلتر حالة + فحص مطابقة كل النتائج
    low_only = client.get("/inventory/", headers=admin, params={"status": "low"}).json()
    assert med["id"] in [x["id"] for x in low_only]
    assert all(x["status"] == "low" for x in low_only)

    # فلاتر خاطئة => 400
    r = client.get("/inventory/", headers=admin, params={"status": "bogus"})
    assert r.status_code == 400, r.text
    r = client.get("/inventory/", headers=admin, params={"expiring_days": -1})
    assert r.status_code == 400, r.text
    r = client.get("/inventory/summary", headers=admin, params={"expiring_days": 999})
    assert r.status_code == 400, r.text
    r = client.get("/inventory/movements", headers=admin, params={"type": "bogus"})
    assert r.status_code == 400, r.text
    r = client.get("/inventory/movements", headers=admin, params={"limit": 0})
    assert r.status_code == 422, r.text


# ================= التوريد والجرد =================
def test_inventory_restock(client, admin):
    med = _mk_med(client, admin, quantity=10, price=2.0, min_quantity=5)
    r = client.post(f"/inventory/{med['id']}/restock", headers=admin,
                    json={"quantity": 15, "note": "توريد تجريبي"})
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 25

    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"]}).json()
    assert mv and mv[0]["type"] == "in"
    assert mv[0]["change"] == 15 and mv[0]["quantity_after"] == 25
    assert mv[0]["note"] == "توريد تجريبي" and mv[0]["made_by"] == "admin"
    assert mv[0]["medication_name"] == med["name"]

    # تحقق متسلسل: الرصيد بعد كل حركة يساوي الكمية الحالية
    assert client.get(f"/inventory/", headers=admin,
                      params={"search": med["code"]}).json()[0]["quantity"] == 25

    # أخطاء متوقعة
    r = client.post(f"/inventory/{med['id']}/restock", headers=admin, json={"quantity": 0})
    assert r.status_code == 422, r.text
    r = client.post(f"/inventory/{med['id']}/restock", headers=admin, json={"quantity": -3})
    assert r.status_code == 422, r.text
    r = client.post("/inventory/999999/restock", headers=admin, json={"quantity": 5})
    assert r.status_code == 404, r.text


def test_inventory_adjust(client, admin):
    med = _mk_med(client, admin, quantity=10, price=1.0, min_quantity=5)
    r = client.put(f"/inventory/{med['id']}/adjust", headers=admin,
                   json={"quantity": 4, "note": "جرد مخزن"})
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 4

    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"], "type": "adjust"}).json()
    assert mv and mv[0]["change"] == -6 and mv[0]["quantity_after"] == 4
    assert mv[0]["note"] == "جرد مخزن"

    # جرد يزيد الكمية => change موجب
    r = client.put(f"/inventory/{med['id']}/adjust", headers=admin, json={"quantity": 9})
    assert r.json()["quantity"] == 9
    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"], "type": "adjust"}).json()
    assert mv[0]["change"] == 5 and mv[0]["quantity_after"] == 9

    # أخطاء متوقعة
    r = client.put(f"/inventory/{med['id']}/adjust", headers=admin, json={"quantity": -1})
    assert r.status_code == 422, r.text
    r = client.put("/inventory/999999/adjust", headers=admin, json={"quantity": 1})
    assert r.status_code == 404, r.text


# ================= ربط حركات الصيدلية =================
def test_inventory_tracks_pharmacy_operations(client, admin):
    med = _mk_med(client, admin, quantity=20, price=2.5, min_quantity=5)
    r = client.get("/inventory/movements", headers=admin,
                   params={"medication_id": med["id"], "type": "in"}).json()
    assert r and r[0]["change"] == 20 and r[0]["quantity_after"] == 20
    assert "رصيد افتتاحي" in r[0]["note"]

    # صرف => حركة out بكمية سالبة
    pat = client.post("/patients/", headers=admin, json={
        "full_name": "مريض المخزون " + uid()[:5],
        "date_of_birth": "1995-02-02", "gender": "ذكر",
        "phone": "05" + uid()[:8], "email": f"inv_{uid()}@test.com"}).json()
    d = client.post("/dispenses/", headers=admin, json={
        "medication_id": med["id"], "patient_id": pat["id"], "quantity": 6}).json()
    assert d["quantity"] == 6

    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"], "type": "out"}).json()
    assert mv and mv[0]["type"] == "out"
    assert mv[0]["change"] == -6 and mv[0]["quantity_after"] == 14
    assert pat["full_name"] in mv[0]["note"]

    # تعديل كمية عبر PUT /medications => حركة مسجّلة
    r = client.put(f"/medications/{med['id']}", headers=admin, json={"quantity": 30})
    assert r.status_code == 200 and r.json()["quantity"] == 30
    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"]}).json()
    assert any(x["change"] == 16 and x["quantity_after"] == 30 for x in mv)

    # حذف دواء يحذف حركاته (CASCADE)
    assert client.delete(f"/medications/{med['id']}", headers=admin).status_code == 204
    mv = client.get("/inventory/movements", headers=admin,
                    params={"medication_id": med["id"]}).json()
    assert mv == []


# ================= ملصقات الباركود PDF =================
def test_inventory_labels_pdf(client, admin):
    """ملصقات الباركود: مصادقة/صلاحية + PDF + تحقق ids (400/404)."""
    med = _mk_med(client, admin)

    # بلا توكن => 401 · موظف عادي => 403
    assert client.get("/inventory/labels").status_code == 401
    _, _, h_rec = _register(client, prefix="lblrec")
    assert client.get("/inventory/labels", headers=h_rec).status_code == 403

    # ids فارغة => كل الأدوية (PDF باسم med_labels.pdf)
    r = client.get("/inventory/labels", headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF", r.status_code
    assert "med_labels.pdf" in r.headers.get("content-disposition", "")

    # دواء واحد
    r = client.get("/inventory/labels", headers=admin,
                   params={"ids": str(med["id"])})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"

    # ids غير رقمية => 400
    r = client.get("/inventory/labels", headers=admin, params={"ids": "abc"})
    assert r.status_code == 400 and "ids" in r.json()["detail"]

    # معرّف مجهول => 404
    r = client.get("/inventory/labels", headers=admin,
                   params={"ids": "99999999"})
    assert r.status_code == 404 and "لا يوجد دواء بالمعرف" in r.json()["detail"]


# ================= مؤشرات الواجهة =================
def test_inventory_ui_markers(client):
    ui = client.get("/ui/").text + client.get("/ui/app.js").text
    assert 'data-view="inventory"' in ui
    assert "async inventory(main)" in ui
    assert "inventory: 'المخزون'" in ui
    assert "'📦 المخزون': '📦 Inventory'" in ui
    assert "/inventory/summary" in ui
    assert "/inventory/movements" in ui
    assert "function adjustStock(" in ui
    assert "loadInventory()" in ui and "clearInv()" in ui
    # التوريد يمر عبر محور المخزون الجديد
    assert "'/inventory/' + id + '/restock'" in ui
    # ملصقات الباركود (المخزون + الصيدلية)
    assert "/inventory/labels" in ui
    assert "ملصقات الكل" in ui
    assert "label_${m.code}.pdf" in ui
    assert "'🏷️ ملصق': '🏷️ Label'" in ui
    # الكاش رُفع إلى v5 (شل مجزّأ: الصفحة + app.css + app.js + manifest + الأيقونة)
    sw = client.get("/ui/sw.js").text
    assert "hms-shell-v5" in sw
    assert "/ui/app.js" in sw and "/ui/app.css" in sw
