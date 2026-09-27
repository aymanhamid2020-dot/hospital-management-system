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


# ================= توثيق OpenAPI للحذف =================
def test_delete_user_documented_in_openapi(client):
    """مخطط الوثائق يشرح كل ردود الحذف بأمثلة عربية — لا زر بلا توثيق."""
    spec = client.get("/api/openapi.json").json()
    op = spec["paths"]["/auth/users/{user_id}"]["delete"]
    assert set(op["responses"]) >= {"204", "400", "401", "403", "404"}

    ex400 = op["responses"]["400"]["content"]["application/json"]["examples"]
    assert ex400["self"]["value"]["detail"] == "لا يمكنك حذف حسابك"
    assert ex400["last-admin"]["value"]["detail"] == "لا يمكن حذف آخر مدير نشط في النظام"
    ex403 = op["responses"]["403"]["content"]["application/json"]["example"]
    assert ex403["detail"] == "هذه العملية تتطلب صلاحية المدير العام"
    ex404 = op["responses"]["404"]["content"]["application/json"]["example"]
    assert ex404["detail"] == "المستخدم غير موجود"
    ex401 = op["responses"]["401"]["content"]["application/json"]["example"]
    assert "تسجيل الدخول" in ex401["detail"]
    # 204 استجابة بلا محتوى: لا يُختلق لها JSON
    assert "content" not in op["responses"]["204"]
    assert op["responses"]["204"]["description"].strip()
    assert op["summary"] == "حذف مستخدم"
    # والوصف يشرح ضمان المراجع
    assert "SET NULL" in (op.get("description") or "")


# ================= الأدوار المعطّلة (is_active) =================
def test_inactive_role_is_server_tracked_and_ui_filtered(client, admin):
    """الخادم يُرجع `is_active` ويقبل تعطيل دور، والواجهة لا تعرضه في قوائم الإسناد."""
    js = client.get("/app.js").text
    assert "is_active !== false" in js, "شاشة المستخدمين لا تفرز الأدوار المعطّلة"
    assert "⛔" in js, "لا وسم لدور معطّل في القائمة"

    created = client.post("/permissions/roles", headers=admin,
                          json={"name_ar": "دور مؤقت للتعطيل"}).json()
    assert created["is_active"] is True

    off = client.put(f"/permissions/roles/{created['id']}", headers=admin,
                     json={"is_active": False})
    assert off.status_code == 200, off.text
    assert off.json()["is_active"] is False

    row = next(r for r in client.get("/permissions/roles", headers=admin).json()
               if r["id"] == created["id"])
    assert row["is_active"] is False
    assert row["users_count"] == 0 and row["can_delete"] is True

    # تنظيف: حذف الدور المؤقت بعد تعطيله (بلا مستخدمين فيُقبل)
    assert client.delete(f"/permissions/roles/{created['id']}",
                         headers=admin).status_code == 204


# ================= ربط شاشتي الأدوار والمستخدمين =================
def test_roles_and_users_screens_are_cross_linked(client):
    """زر «مستخدموه» في جدول الأدوار يفتح شاشة المستخدمين مُصفّاة على الدور نفسه."""
    js = client.get("/app.js").text
    assert "function rbRoleUsers(key)" in js
    assert "USR.filter = key" in js
    assert 'onclick="rbRoleUsers(this.dataset.key)"' in js, "زر الصف غير موجود"
    assert "function clearRoleFilter()" in js and "USR.filter = ''" in js
    assert "shown = USR.filter ?" in js, "الفلتر لا يُطبَّق على الصفوف"
    assert "navigate('permissions')" in js, "لا زر العودة من شاشة المستخدمين للأدوار"


# ================= أداة تنظيف حسابات الاختبار =================
def test_cleanup_tool_collects_only_test_accounts():
    """الأداة تلتقط بصمات الاختبار وحدها ولا تمسّ النظام أو الحسابات الحقيقية."""
    from cleanup_temp_users import collect_temp_users

    rows = [
        {"id": 1, "username": "admin"},
        {"id": 2, "username": "demo_doc1"},
        {"id": 3, "username": "dr_ahmed"},
        {"id": 4, "username": "uadmABC"},
        {"id": 5, "username": "recph_P123"},
        {"id": 6, "username": "livedel2_9"},
        {"id": 7, "username": "cash_fff"},
        {"id": 8, "username": "delA_77"},
        {"id": 9, "username": "off4WC2H"},       # بصمة الدور المعطّل (TAG = 5 رموز)
        {"id": 10, "username": "offline_manager"},  # حساب حقيقي محتمل: لا يُلتقط
    ]
    got = {v["username"] for v in collect_temp_users(rows)}
    assert got == {"uadmABC", "recph_P123", "livedel2_9", "cash_fff",
                   "delA_77", "off4WC2H"}
    assert all(v["id"] for v in collect_temp_users(rows)), "المعرّف مطلوب للحذف"

    # محميّ حتى لو طابقت بصمة صريحة
    assert collect_temp_users([{"id": 1, "username": "admin"}],
                              patterns=(r"^adm",)) == []
    # بصم مخصّصة بديلة
    only = collect_temp_users(rows, patterns=(r"^dr_",))
    assert {v["username"] for v in only} == {"dr_ahmed"}
