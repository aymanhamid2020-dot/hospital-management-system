"""حسابات بوابة المريض — الإنشاء وإعادة التعيين والتعطيل والحذف (للمدير).

الحساب يربط سجل مريض واحدًا ولا يُنشأ ذاتيًا: المدير فقط هو من يمنح
الوصول، فلا يستطيع أحد انتحال سجل مريض ببياناته.
"""
import uuid

from conftest import login


def uid():
    return uuid.uuid4().hex[:8]


def _mk_patient(client, admin):
    r = client.post("/patients/", headers=admin, json={
        "full_name": "مريض بوابة " + uid(), "date_of_birth": "1990-01-01",
        "gender": "ذكر", "phone": "0555000" + uid()[:4],
        "email": f"pp_{uid()}@test.com"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_portal_account_admin_lifecycle(client, admin):
    """الإنشاء ثم الدخول ثم إعادة التعيين ثم التعطيل ثم الحذف."""
    pid = _mk_patient(client, admin)
    uname = "portal_" + uid()

    r = client.post("/patient-portal/accounts", headers=admin, json={
        "patient_id": pid, "username": uname, "password": "PortalPass123!"})
    assert r.status_code == 201, r.text
    body = r.json()
    acc_id = body["id"]
    assert body["patient_name"], body
    assert "password" not in body and "hashed_password" not in body
    assert body["is_active"] is True

    # تكرار لنفس المريض أو لاسم المستخدم ⇒ 400 ؛ مريض غير موجود ⇒ 404
    assert client.post("/patient-portal/accounts", headers=admin, json={
        "patient_id": pid, "username": "other_" + uid(),
        "password": "PortalPass123!"}).status_code == 400
    assert client.post("/patient-portal/accounts", headers=admin, json={
        "patient_id": pid, "username": uname,
        "password": "PortalPass123!"}).status_code == 400
    assert client.post("/patient-portal/accounts", headers=admin, json={
        "patient_id": 999999, "username": "x_" + uid(),
        "password": "PortalPass123!"}).status_code == 404

    # كلمة مرور قصيرة أو اسم مستخدم قصير ⇒ 422
    assert client.post("/patient-portal/accounts", headers=admin, json={
        "patient_id": pid, "username": "z_" + uid(),
        "password": "short"}).status_code == 422
    assert client.post("/patient-portal/accounts", headers=admin, json={
        "patient_id": pid, "username": "ab",
        "password": "PortalPass123!"}).status_code == 422

    # الدخول يعمل بكلمة المرور الأصلية
    assert client.post("/patient-portal/login", json={
        "username": uname, "password": "PortalPass123!"}).status_code == 200

    # إعادة التعيين: القديمة تفشل والجديدة تنجح
    assert client.put(f"/patient-portal/accounts/{acc_id}/password", headers=admin,
                      json={"password": "NewPass456!"}).status_code == 200
    assert client.post("/patient-portal/login", json={
        "username": uname, "password": "PortalPass123!"}).status_code == 401
    assert client.post("/patient-portal/login", json={
        "username": uname, "password": "NewPass456!"}).status_code == 200

    # التعطيل يمنع الدخول فورًا
    assert client.patch(f"/patient-portal/accounts/{acc_id}", headers=admin,
                        json={"is_active": False}).status_code == 200
    assert client.post("/patient-portal/login", json={
        "username": uname, "password": "NewPass456!"}).status_code == 401

    # القائمة تُظهر اسم المريض وآخر دخول ولا تُظهر كلمة المرور
    rows = client.get("/patient-portal/accounts", headers=admin).json()
    row = next(x for x in rows if x["id"] == acc_id)
    assert row["patient_name"] and row["last_login_at"] is not None
    assert "password" not in row and "hashed_password" not in row

    # الحذف يمحو الحساب فقط ولا يمسّ سجل المريض
    assert client.delete(f"/patient-portal/accounts/{acc_id}", headers=admin).status_code == 204
    # القاعدة مشتركة بين الملفات ⇒ نتحقق من اختفاء حسابنا لا من فراغ القائمة
    assert acc_id not in [x["id"] for x in
                          client.get("/patient-portal/accounts", headers=admin).json()]
    assert client.get(f"/patients/{pid}", headers=admin).status_code == 200
    assert client.delete(f"/patient-portal/accounts/{acc_id}", headers=admin).status_code == 404


def test_portal_accounts_admin_only(client, admin):
    """بلا توكن 401 · موظف غير مدير 403 — فلا يطّلع على حسابات المرضى."""
    assert client.get("/patient-portal/accounts").status_code == 401
    uname = "rec_" + uid()
    r = client.post("/auth/register", json={
        "username": uname, "email": f"{uname}@test.com",
        "full_name": "موظف استقبال", "role": "موظف استقبال",
        "password": "Passw0rd!"})
    rec = login(client, r.json()["username"], "Passw0rd!")
    pid = _mk_patient(client, admin)
    assert client.get("/patient-portal/accounts", headers=rec).status_code == 403
    assert client.post("/patient-portal/accounts", headers=rec, json={
        "patient_id": pid, "username": "hack_" + uid(),
        "password": "PortalPass123!"}).status_code == 403
    assert client.patch("/patient-portal/accounts/1", headers=rec,
                        json={"is_active": False}).status_code == 403
    assert client.put("/patient-portal/accounts/1/password", headers=rec,
                      json={"password": "PortalPass123!"}).status_code == 403
    assert client.delete("/patient-portal/accounts/1", headers=rec).status_code == 403
