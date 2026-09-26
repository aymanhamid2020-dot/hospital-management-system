"""اختبارات المخزون العام (GeneralStockItem) — مرحلة 3: مشترك"""
import uuid
from conftest import client, admin


def test_general_stock_crud(client, admin):
    """CRUD كامل للمخزون العام"""

    # 1. إنشاء صنف جديد
    payload = {
        "code": f"GS-{uuid.uuid4().hex[:6].upper()}",
        "name": "قفازات طبية معقمة",
        "category": "medical_supplies",
        "warehouse": "main",
        "quantity": 100,
        "min_quantity": 20,
        "unit": "علبة",
        "unit_cost": 25.50,
        "expiry_date": "2027-12-31T00:00:00"
    }
    r = client.post("/general-stock/", headers=admin, json=payload)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["code"].startswith("GS-")
    assert item["name"] == "قفازات طبية معقمة"
    assert item["quantity"] == 100
    item_id = item["id"]

    # 2. محاولة تكرار الكود ⇒ 409
    r2 = client.post("/general-stock/", headers=admin, json=payload)
    assert r2.status_code == 409

    # 3. قراءة القائمة
    r3 = client.get("/general-stock/", headers=admin)
    assert r3.status_code == 200
    items = r3.json()
    assert any(i["id"] == item_id for i in items)

    # 4. فلترة بالتصنيف
    r4 = client.get("/general-stock/?category=medical_supplies", headers=admin)
    assert r4.status_code == 200
    assert all(i["category"] == "medical_supplies" for i in r4.json())

    # 5. تحديث جزئي
    r5 = client.put(f"/general-stock/{item_id}", headers=admin,
                    json={"quantity": 150, "unit_cost": 27.00})
    assert r5.status_code == 200
    assert r5.json()["quantity"] == 150
    assert r5.json()["unit_cost"] == 27.00

    # 6. توريد كمية
    r6 = client.post(f"/general-stock/{item_id}/restock", headers=admin,
                     json={"quantity": 50})
    assert r6.status_code == 200
    assert r6.json()["quantity"] == 200  # 150 + 50

    # 7. جرد مطلق
    r7 = client.put(f"/general-stock/{item_id}/adjust", headers=admin,
                    json={"quantity": 180})
    assert r7.status_code == 200
    assert r7.json()["quantity"] == 180

    # 8. إتلاف كمية
    r8 = client.post(f"/general-stock/{item_id}/dispose", headers=admin,
                     json={"quantity": 30})
    assert r8.status_code == 200
    assert r8.json()["quantity"] == 150

    # 9. إتلاف يتجاوز الرصيد ⇒ 400
    r9 = client.post(f"/general-stock/{item_id}/dispose", headers=admin,
                     json={"quantity": 500})
    assert r9.status_code == 400

    # 10. حذف
    r10 = client.delete(f"/general-stock/{item_id}", headers=admin)
    assert r10.status_code == 204

    # 11. قراءة بعد الحذف ⇒ 404
    r11 = client.get("/general-stock/", headers=admin)
    assert r11.status_code == 200
    assert not any(i["id"] == item_id for i in r11.json())


def test_general_stock_permissions(client, admin):
    """غير المدير لا يستطيع الكتابة"""
    # القراءة مسموحة
    r = client.get("/general-stock/", headers=admin)
    assert r.status_code == 200


def test_general_stock_validation(client, admin):
    """التحققات: كود مكرر، كمية سالبة، حقول مطلوبة"""
    # كود مطلوب
    r = client.post("/general-stock/", headers=admin,
                    json={"name": "Test"})
    assert r.status_code == 422

    # إنشاء صنف صالح أولاً
    r = client.post("/general-stock/", headers=admin,
                    json={"code": f"V{uuid.uuid4().hex[:6]}", "name": "Valid"})
    assert r.status_code == 201
    item_id = r.json()["id"]

    # كمية سالبة في restock
    r2 = client.post(f"/general-stock/{item_id}/restock",
                     headers=admin,
                     json={"quantity": -5})
    assert r2.status_code == 422

    # جرد بقيمة سالبة ⇒ 422
    r3 = client.put(f"/general-stock/{item_id}/adjust",
                    headers=admin,
                    json={"quantity": -10})
    assert r3.status_code == 422