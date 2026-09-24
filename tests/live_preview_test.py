"""فحص مباشر لمعاينة المرفقات بعد الإصلاح."""
import base64
import io

import httpx

BASE = "http://127.0.0.1:8001"

tok = httpx.post(BASE + "/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
h = {"Authorization": "Bearer " + tok}

# رفع صورة PNG صغيرة (1x1)
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
files = {"file": ("xray.png", io.BytesIO(png), "image/png")}
r = httpx.post(BASE + "/attachments/", headers=h, data={"patient_id": "1"}, files=files)
att = r.json()
print("Upload png:", r.status_code, "id =", att["id"])

# معاينة — يجب أن تكون 200 بعد الإصلاح
r = httpx.get(f"{BASE}/attachments/{att['id']}/preview", headers=h)
print("Preview:", r.status_code, r.headers.get("content-type"),
      "| bytes:", len(r.content), "| PNG magic:", r.content[:4] == b"\x89PNG")
assert r.status_code == 200, "Preview failed!"

# تنزيل
r = httpx.get(f"{BASE}/attachments/{att['id']}/file", headers=h)
print("Download:", r.status_code, r.headers.get("content-disposition"))
assert r.status_code == 200

# تنظيف
r = httpx.delete(f"{BASE}/attachments/{att['id']}", headers=h)
print("Delete:", r.status_code)
print("PREVIEW FIXED OK")
