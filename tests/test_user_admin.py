"""إدارة المستخدمين: قسم القائمة الجديد، ربط شاشة المستخدمين بمواصفة الأدوار،
وحذف حساب — مع ضمان ألّا يترك حذفًا صفوفًا يتيمة (فحص المراجع)."""
from conftest import login
from test_advanced import _register


def _sidebar(client) -> str:
    """محتوى القائمة الجانبية فقط — حتى لا تُخلط ببقية الصفحة."""
    html = client.get("/").text
    start = html.index('<nav class="sidebar"')
    return html[start:html.index("</nav>", start)]


# ================= قسم القائمة الجديد =================
def test_sidebar_user_management_group(client):
    """قسم «إدارة المستخدمين» يضم الشاشتين ويُخرجهما من مجموعتهما السابقة."""
    nav = _sidebar(client)
    i_hr = nav.index("الموارد البشرية والإدارة")
    i_group = nav.index("إدارة المستخدمين")
    i_next = nav.index("النظام والحوكمة", i_group)
    assert i_hr < i_group < i_next, "القسم الجديد مكانه بين الموارد البشرية والنظام"

    section = nav[i_group:i_next]
    assert 'data-view="permissions"' in section, "الأدوار والصلاحيات داخل القسم الجديد"
    assert 'data-view="users"' in section, "المستخدمون داخل القسم الجديد"

    old = nav[i_hr:i_group]
    assert 'data-view="permissions"' not in old, "خرجت من مجموعتها القديمة"
    assert 'data-view="users"' not in old, "خرجت من مجموعتها القديمة"


# ================= ربط شاشة المستخدمين بأدوار RBAC =================
def test_users_screen_is_bound_to_rbac_roles(client, admin):
    """الشاشة تقرأ الأدوار من /permissions/roles — لا قائمة ثابتة بثلاثة."""
    js = client.get("/app.js").text
    assert "['admin', 'مدير النظام'], ['doctor', 'طبيب']" not in js, \
        "القائمة الثابتة القديمة ما زالت موجودة"
    assert "api('/permissions/roles')" in js, "لا يوجد ربط بمواصفة الأدوار"
    assert "async function deleteUser(id)" in js and "deleteUser(${u.id})" in js

    roles = client.get("/permissions/roles", headers=admin).json()
    assert len(roles) >= 10, f"عدد الأدوار {len(roles)} — كان متوقعًا 10 أدوار نظامية"
    assert {r["key"] for r in roles} >= {"admin", "doctor", "receptionist", "nurse"}


# ================= حذف الحساب =================
def test_delete_user_validation_and_success(client, admin):
    """401 لغير المسجّل، 403 لغير المدير، 400 للذات، 404 للمعدوم، 204 للنجاح."""
    u, user_id, headers = _register(client, prefix="delA")

    assert client.delete(f"/auth/users/{user_id}").status_code == 401
    assert client.delete(f"/auth/users/{user_id}", headers=headers).status_code == 403
    assert client.delete("/auth/users/99999999", headers=admin).status_code == 404

    admin_id = next(x["id"] for x in client.get("/auth/users", headers=admin).json()
                    if x["username"] == "admin")
    self_block = client.delete(f"/auth/users/{admin_id}", headers=admin)
    assert self_block.status_code == 400
    assert "حسابك" in self_block.json()["detail"]

    r = client.delete(f"/auth/users/{user_id}", headers=admin)
    assert r.status_code == 204, r.text
    assert all(x["id"] != user_id
               for x in client.get("/auth/users", headers=admin).json())
    # اسم المستخدم لم يعد صالحًا للدخول
    assert client.post("/auth/login", json={"username": u, "password": "secret123"}).status_code != 200


def test_delete_user_keeps_referential_integrity(client, admin):
    """استثناء صلاحية (NOT NULL) وسجل تدقيق مرتبط ⇒ حذف بلا500 وبلا صف يتيم."""
    from app.database import SessionLocal
    from app.models import AuditLog, User, UserPermission

    u, user_id, _ = _register(client, prefix="delB")

    # استثناء فردي على مستوى المستخدم — عموده NOT NULL
    r = client.put(f"/permissions/users/{user_id}/access", headers=admin,
                   json=[{"permission": "patients.view", "effect": "deny"}])
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        db.add(AuditLog(user_id=user_id, username=u, method="GET",
                        path="/", status_code=200))
        db.commit()
        assert db.query(UserPermission).filter_by(user_id=user_id).count() == 1
    finally:
        db.close()

    r = client.delete(f"/auth/users/{user_id}", headers=admin)
    assert r.status_code == 204, r.text

    db = SessionLocal()
    try:
        assert db.query(User).filter_by(id=user_id).first() is None
        assert db.query(UserPermission).filter_by(user_id=user_id).count() == 0
        assert db.query(AuditLog).filter_by(user_id=user_id).first() is None, \
            "يجب أن يُؤمَّر سجل التدقيق user_id = NULL بدل بقاء مرجع مكسور"
    finally:
        db.close()


def test_delete_user_drops_permission_overrides(client, admin):
    """الحذف يزيل استثناءات المستخدم معه — لا يبقى استثناء لحساب غير موجود."""
    from app.database import SessionLocal
    from app.models import UserPermission

    _, user_id, _ = _register(client, prefix="delC")
    client.put(f"/permissions/users/{user_id}/access", headers=admin,
               json=[{"permission": "patients.view", "effect": "allow"}])

    db = SessionLocal()
    try:
        assert db.query(UserPermission).filter_by(user_id=user_id).count() == 1
    finally:
        db.close()

    assert client.delete(f"/auth/users/{user_id}", headers=admin).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(UserPermission).filter_by(user_id=user_id).count() == 0
    finally:
        db.close()
