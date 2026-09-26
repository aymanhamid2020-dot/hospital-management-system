"""اختبارات الإحصائيات المشتركة (TAT, Top Tests, Revenue, Delivery)"""
import uuid
from datetime import datetime, timedelta
from conftest import client, admin


def test_tat_stats(client, admin):
    """متوسط زمن الإنجاز (TAT)"""
    r = client.get("/shared/stats/tat", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert "count" in data
    assert "avg_hours" in data
    assert "median_hours" in data


def test_top_tests(client, admin):
    """أكثر الفحوصات طلبًا"""
    r = client.get("/shared/stats/top-tests", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_revenue_stats(client, admin):
    """إيرادات المختبر والأشعة"""
    r = client.get("/shared/stats/revenue", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert "total_revenue" in data
    assert "by_type" in data
    assert "by_status" in data


def test_delivery_stats(client, admin):
    """إحصائيات التسليم"""
    r = client.get("/shared/stats/delivery", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert "total_delivered" in data
    assert "by_channel" in data


def test_deliver_lab_order(client, admin):
    """تسليم النتيجة للمريض"""
    # إنشاء فحص، مريض، طلب
    test_payload = {
        "code": f"TST-{uuid.uuid4().hex[:6].upper()}",
        "name": "فحص تسليم",
        "category": "lab",
        "price": 50.0,
        "fasting_hours": 0,
        "tube_type": "EDTA",
        "specimen_type": "دم",
        "unit": "g/dL",
        "ref_min": 10.0,
        "ref_max": 20.0
    }
    r = client.post("/lab-tests/", headers=admin, json=test_payload)
    assert r.status_code == 201
    test = r.json()

    patient_payload = {
        "full_name": f"مريض تسليم {uuid.uuid4().hex[:5]}",
        "gender": "ذكر",
        "phone": f"055{uuid.uuid4().hex[:7]}",
        "date_of_birth": "1990-01-01",
        "email": f"del{uuid.uuid4().hex[:6]}@example.com",
        "blood_type": "O+"
    }
    r = client.post("/patients/", headers=admin, json=patient_payload)
    assert r.status_code in (200, 201)
    patient = r.json()

    order_payload = {
        "patient_id": patient["id"],
        "test_name": test["name"],
        "lab_test_id": test["id"]
    }
    r = client.post("/lab-orders/", headers=admin, json=order_payload)
    assert r.status_code == 200
    order = r.json()

    # سحب واستلام العينة
    r = client.post(f"/lab-orders/{order['id']}/collect", headers=admin,
                    json={"specimen_type": "دم"})
    assert r.status_code == 200
    r = client.post(f"/lab-orders/{order['id']}/receive", headers=admin,
                    json={"accepted": True})
    assert r.status_code == 200

    # إدخال نتيجة
    r = client.post(f"/lab-orders/{order['id']}/result", headers=admin,
                    json={"result": "12.5", "value": 12.5})
    assert r.status_code == 200

    # تسليم النتيجة
    r = client.post(f"/lab-orders/{order['id']}/deliver", headers=admin,
                    json={"note": "pdf"})
    assert r.status_code == 200
    delivered = r.json()
    assert delivered["delivered_at"] is not None
    assert delivered["delivered_by"] is not None
    assert delivered["delivery_channel"] == "pdf"

    # محاولة تسليم مجدد ⇒ 409
    r2 = client.post(f"/lab-orders/{order['id']}/deliver", headers=admin,
                     json={"note": "pdf"})
    assert r2.status_code == 409