# -*- coding: utf-8 -*-
"""الصلاحيات والأدوار (RBAC): الكتالوج · الأدوار المخصّصة · المصفوفة ·
الاستثناءات الفردية · الحراسة على الخادم · هجرة أدوار النظام القديمة."""
import uuid

from conftest import login


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _register(client, role="receptionist", prefix="rb"):
    uname = f"{prefix}_{uid()}"
    r = client.post("/auth/register", json={
        "username": uname, "password": "Test@12345", "full_name": "مستخدم اختبار",
        "email": f"{uname}@hospital-demo.com", "role": role})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    return body, login(client, uname, "Test@12345")


def _create_role(client, admin, name, permissions=None, copy_from=None):
    payload = {"name_ar": name}
    if permissions is not None:
        payload["permissions"] = permissions
    if copy_from is not None:
        payload["copy_from"] = copy_from
    r = client.post("/permissions/roles", headers=admin, json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ===== الكتالوج =====
def test_catalog_is_seeded_and_grouped(client, admin):
    """كتالوج الصلاحيات مزروع ومجمّع حسب الوحدات، وكل مفتاح موحّد `module.action`."""
    catalog = client.get("/permissions/catalog", headers=admin).json()
    assert len(catalog) >= 30, "الكتالوج يحتوي القدرات الأساسية"
    assert all("." in p["key"] for p in catalog), "كل صلاحية بمفتاح module.action"
    assert {p["module"] for p in catalog} == set(
        client.get("/permissions/modules", headers=admin).json())
    assert any(p["key"] == "patients.edit" for p in catalog)
    assert any(p["is_sensitive"] for p in catalog), "توجد صلاحيات حسّاسة موسومة"
    roles = client.get("/permissions/roles", headers=admin).json()
    keys = {r["key"] for r in roles}
    assert {"admin", "doctor", "receptionist", "cashier", "accountant"} <= keys
    admin_role = next(r for r in roles if r["key"] == "admin")
    assert admin_role["is_super"] is True
    assert len(admin_role["permissions"]) == len(catalog)


def test_role_permissions_are_scoped_not_admin_or_nothing(client, admin):
    """الفرق الجوهري: دوران مختلفان صلاحياتهما مختلفة — لا «مدير أو لا شيء»."""
    roles = {r["key"]: r for r in client.get("/permissions/roles", headers=admin).json()}
    cashier = set(roles["cashier"]["permissions"])
    doctor = set(roles["doctor"]["permissions"])
    assert cashier and doctor
    assert cashier != doctor, "الأدوار لها صلاحيات مختلفة فعليًا"
    assert "sales.cashclose" in cashier and "sales.cashclose" not in doctor
    assert "records.edit" in doctor and "records.edit" not in cashier


# ===== الأدوار المخصّصة =====
def test_custom_role_created_and_used_by_user(client, admin):
    """دور مخصّص يُنشأ ويعمل فورًا: المستخدم يأخذ صلاحياته لا أكثر."""
    role = _create_role(client, admin, "مشرف وردية",
                        permissions=["sales.view", "sales.manage"])
    user, headers = _register(client, role=role["key"], prefix="sup")
    assert user["role"] == role["key"]
    assert set(user["permissions"]) == {"sales.view", "sales.manage"}
    my = client.get("/permissions/my", headers=headers).json()
    assert set(my["permissions"]) == {"sales.view", "sales.manage"}
    assert my["is_super"] is False


def test_role_copy_and_rename(client, admin):
    """نسخ دور ينقل صلاحياته كاملة، وأدوار النظام لا تُحذف."""
    roles = {r["key"]: r for r in client.get("/permissions/roles", headers=admin).json()}
    src = roles["accountant"]
    copy = client.post(f"/permissions/roles/{src['id']}/copy", headers=admin,
                       json={"name_ar": "محاسب-نسخة"}).json()
    assert set(copy["permissions"]) == set(src["permissions"])

    renamed = client.put(f"/permissions/roles/{copy['id']}", headers=admin,
                         json={"name_ar": "محاسب مكرّر", "description": "وصف"})
    assert renamed.status_code == 200 and renamed.json()["name_ar"] == "محاسب مكرّر"
    assert client.delete(f"/permissions/roles/{src['id']}", headers=admin).status_code == 400, \
        "دور النظام لا يُحذف"


def test_role_delete_guards(client, admin):
    """الدور المرتبط بمستخدم لا يُحذف، والدور الحر يُحذف."""
    role = _create_role(client, admin, "دور مشغول", permissions=["patients.view"])
    _register(client, role=role["key"], prefix="busy")
    busy = client.delete(f"/permissions/roles/{role['id']}", headers=admin)
    assert busy.status_code == 400 and "مستخدم" in busy.json()["detail"]

    free = _create_role(client, admin, "دور فريد")
    assert client.delete(f"/permissions/roles/{free['id']}", headers=admin).status_code == 204


def test_setting_role_permissions_replaces_and_validates(client, admin):
    """ضبط الصلاحيات استبدال كامل، ومفتاح مجهول مرفوض بلا تعديل جزئي."""
    role = _create_role(client, admin, "دور الضبط", permissions=["patients.view"])
    upd = client.put(f"/permissions/roles/{role['id']}/permissions", headers=admin,
                     json={"permissions": ["sales.view", "sales.manage", "reports.view"]})
    assert upd.status_code == 200
    assert set(upd.json()["permissions"]) == {"sales.view", "sales.manage", "reports.view"}

    bad = client.put(f"/permissions/roles/{role['id']}/permissions", headers=admin,
                     json={"permissions": ["sales.view", "not.a.permission"]})
    assert bad.status_code == 404
    assert set(client.get(f"/permissions/roles/{role['id']}",
                          headers=admin).json()["permissions"]) == {
        "sales.view", "sales.manage", "reports.view"}, "الفشل لم يغيّر شيئًا"


def test_super_role_cannot_be_downgraded(client, admin):
    """دور المدير العام يتجاوز كل شيء، ولا تنقض روابطه بمنحِه الصلاحيات."""
    roles = {r["key"]: r for r in client.get("/permissions/roles", headers=admin).json()}
    body = client.put(f"/permissions/roles/{roles['admin']['id']}/permissions",
                      headers=admin, json={"permissions": ["patients.view"]}).json()
    assert len(body["permissions"]) == len(client.get("/permissions/catalog",
                                                       headers=admin).json())


# ===== الاستثناءات الفردية =====
def test_user_override_deny_beats_role(client, admin):
    """«منع» يسحب صلاحية يمنحها الدور."""
    role = _create_role(client, admin, "كاشير-مقيد",
                        permissions=["sales.view", "sales.manage", "sales.discount"])
    user, headers = _register(client, role=role["key"], prefix="ov1")
    assert "sales.discount" in user["permissions"]

    r = client.put(f"/permissions/users/{user['id']}/access", headers=admin,
                   json=[{"permission": "sales.discount", "effect": "deny",
                          "note": "بدون صلاحية خصم"}])
    assert r.status_code == 200
    assert "sales.discount" not in r.json()["effective"]
    assert "sales.view" in r.json()["effective"], "بقية الدور لم تتأثر"
    assert set(client.get("/permissions/my", headers=headers).json()["permissions"]) == {
        "sales.view", "sales.manage"}


def test_user_override_allow_extends_role(client, admin):
    """«سماح» يعطي صلاحية خارج الدور — تخصيص دقيق بلا دور جديد."""
    role = _create_role(client, admin, "محاسب-محدود",
                        permissions=["accounting.view", "reports.view"])
    user, headers = _register(client, role=role["key"], prefix="ov2")
    assert "accounting.manage" not in user["permissions"]

    r = client.put(f"/permissions/users/{user['id']}/access", headers=admin,
                   json=[{"permission": "accounting.manage", "effect": "allow"}])
    assert "accounting.manage" in r.json()["effective"]
    assert "accounting.manage" in client.get(
        "/permissions/my", headers=headers).json()["permissions"]

    cleared = client.put(f"/permissions/users/{user['id']}/access", headers=admin, json=[])
    assert "accounting.manage" not in cleared.json()["effective"], "المسح يرجع للدور"
    assert cleared.json()["overrides"] == []


def test_user_access_reports_layers(client, admin):
    """واجهة الوصول تبيّن الطبقات الثلاث: الدور + الاستثناء + الفعلي."""
    role = _create_role(client, admin, "طبقات", permissions=["patients.view"])
    user, _ = _register(client, role=role["key"], prefix="lay")
    client.put(f"/permissions/users/{user['id']}/access", headers=admin,
               json=[{"permission": "patients.view", "effect": "deny"},
                     {"permission": "lab.view", "effect": "allow"}])
    acc = client.get(f"/permissions/users/{user['id']}/access", headers=admin).json()
    assert acc["role"] == role["key"] and acc["role_name"] == "طبقات"
    assert acc["role_permissions"] == ["patients.view"]
    assert len(acc["overrides"]) == 2
    assert acc["effective"] == ["lab.view"]


def test_invalid_override_rejected(client, admin):
    """effect غير معروف أو صلاحية مجهولة ⇒ رفض بلا تغيير."""
    user, _ = _register(client, prefix="bad")
    bad_effect = client.put(f"/permissions/users/{user['id']}/access", headers=admin,
                            json=[{"permission": "patients.view", "effect": "maybe"}])
    assert bad_effect.status_code == 400
    bad_key = client.put(f"/permissions/users/{user['id']}/access", headers=admin,
                         json=[{"permission": "nope.nope", "effect": "allow"}])
    assert bad_key.status_code == 404
    assert client.get(f"/permissions/users/{user['id']}/access",
                      headers=admin).json()["overrides"] == []


# ===== الحماية والحراسة =====
def test_roles_writing_requires_admin(client, admin):
    """القراءة للجميع، والكتابة للمدير العام فقط."""
    _, headers = _register(client, role="receptionist", prefix="guest")
    assert client.get("/permissions/catalog", headers=headers).status_code == 200
    assert client.get("/permissions/roles", headers=headers).status_code == 200
    assert client.post("/permissions/roles", headers=headers,
                       json={"name_ar": "ممنوع"}).status_code == 403
    roles = client.get("/permissions/roles", headers=admin).json()
    target = next(r for r in roles if r["key"] == "cashier")
    assert client.put(f"/permissions/roles/{target['id']}/permissions", headers=headers,
                      json={"permissions": []}).status_code == 403
    me = client.get("/auth/me", headers=headers).json()
    assert client.get(f"/permissions/users/{me['id']}/access",
                      headers=headers).status_code == 403


def test_register_cannot_self_escalate_to_admin(client, admin):
    """التسجيل العام لا يمنح دور المدير، ودور غير موجود مرفوض."""
    forged = client.post("/auth/register", json={
        "username": f"esc_{uid()}", "password": "Test@12345", "full_name": "متصعّد",
        "email": f"esc_{uid()}@hospital-demo.com", "role": "admin"})
    assert forged.status_code == 200
    assert forged.json()["role"] == "receptionist", "التسجيل العام لا يصعّد إلى مدير"

    unknown = client.post("/auth/register", json={
        "username": f"unk_{uid()}", "password": "Test@12345", "full_name": "مجهول",
        "email": f"unk_{uid()}@hospital-demo.com", "role": "دور_غير_موجود"})
    assert unknown.status_code == 400


def test_register_accepts_role_display_name(client, admin):
    """التسجيل يقبل اسم الدور العربي كما يظهر في الواجهة."""
    role = _create_role(client, admin, "دور بالاسم",
                        permissions=["patients.view", "lab.view"])
    user, _ = _register(client, role="دور بالاسم", prefix="byname")
    assert user["role"] == role["key"]


def test_check_endpoint_explains_denial(client, admin):
    """زر «لماذا لا أرى؟»: نقطة فحص تشرح المنع بدل رسالة عامة."""
    role = _create_role(client, admin, "محدود جدًا", permissions=["patients.view"])
    _, headers = _register(client, role=role["key"], prefix="chk")
    granted = client.get("/permissions/check?key=patients.view", headers=headers).json()
    denied = client.get("/permissions/check?key=sales.manage", headers=headers).json()
    assert granted["granted"] is True and granted["role"] == role["key"]
    assert denied["granted"] is False and denied["total"] == 1


# ===== هجرة الأدوار القديمة =====
def test_legacy_role_values_map_to_new_keys():
    """قيم enum القديمة (أسماء بحروف كبيرة) تُترجم بلا فقدان صلاحية للمدير."""
    from app.permissions import normalize_role_key as norm
    assert norm("ADMIN") == "admin", "اسم التعداد القديم يجب أن يبقى مديرًا"
    assert norm("DOCTOR") == "doctor"
    assert norm("RECEPTIONIST") == "receptionist"
    assert norm("admin") == "admin"
    assert norm("موظف استقبال") == "receptionist"
    assert norm("غير معروف") == "receptionist", "القيمة المجهولة: أقل صلاحية"
    assert norm("") == "receptionist"
    assert norm(None) == "receptionist"


