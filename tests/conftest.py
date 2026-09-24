"""إعدادات اختبار pytest — قاعدة بيانات منفصلة عن الإنتاج."""
import os
import tempfile

# ضبط قاعدة بيانات الاختبار قبل استيراد التطبيق
_TEST_DB = os.path.join(tempfile.gettempdir(), "hms_test.db")
if os.path.exists(_TEST_DB):
    try:
        os.remove(_TEST_DB)
    except OSError:
        pass
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

import pytest
from fastapi.testclient import TestClient

from main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """عميل اختبار يشغّل دورة حياة التطبيق (إنشاء الجداول + بذر admin)."""
    with TestClient(app) as c:
        yield c


def login(client, username: str, password: str) -> dict:
    """تسجيل الدخول وإرجاع ترويسة Authorization."""
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "admin", "admin123")
