"""تصدير/استيراد CSV للبيانات الأساسية — الأصناف والموردون والأقسام
والمستودعات والأدوية: تصدير بقالب موحّد، قالب جاهز، ودمج (upsert) بأمانة.
"""
import uuid

from conftest import login


def uid() -> str:
    return uuid.uuid4().hex[:6]


def _csv(rows: list) -> bytes:
    """ملف CSV بترميز utf-8 (بلا BOM) كما ينتجه Excel بترميز عربي."""
    return "\n".join(",".join(str(c) for c in row) for row in rows).encode("utf-8")


def _text(res) -> str:
    return res.content.decode("utf-8-sig")


def test_resources_listing(client, admin):
    """قائمة الموارد تغذّي أزرار الواجهة: 5 موارد بعناوين عربية ومفتاح تفرّد."""
    r = client.get("/exchange/resources", headers=admin)
    assert r.status_code == 200, r.text
    keys = [x["key"] for x in r.json()]
    assert set(keys) == {"items", "medications", "vendors", "departments", "warehouses"}
    items = next(x for x in r.json() if x["key"] == "items")
    assert "الكود" in items["headers"] and items["unique"] == "code"
    assert client.get("/exchange/resources").status_code == 401


def test_export_items_csv_with_bom_and_arabic_headers(client, admin):
    """التصدير يفتح عربيًا في Excel (BOM) ويحمل صف الصنف المنشأ."""
    code = f"EX{uuid.uuid4().hex[:6]}"
    client.post("/general-stock/", headers=admin, json={
        "code": code, "name": "صنف تصدير", "unit": "علبة", "unit_cost": 9.5,
        "min_quantity": 4, "reorder_point": 12, "max_quantity": 40,
        "storage_condition": "ثلاجة"})

    r = client.get("/exchange/items/export.csv", headers=admin)
    assert r.status_code == 200
    assert r.content[:3] == "﻿".encode("utf-8")   # BOM
    assert "text/csv" in r.headers["content-type"]
    head, *body = _text(r).splitlines()
    for col in ("الكود", "اسم الصنف", "نقطة إعادة الطلب", "الحد الأقصى",
                "الاسم العلمي", "شروط التخزين"):
        assert col in head
    row = next(line for line in body if code in line)
    assert "ثلاجة" in row and "12" in row and "40" in row
    assert client.get("/exchange/items/export.csv").status_code == 401


def test_template_csv_has_header_and_sample(client, admin):
    """القالب يهيّئ الترويسة + صف مثال يطابق أعمدة المورد."""
    r = client.get("/exchange/vendors/template.csv", headers=admin)
    assert r.status_code == 200
    head, sample = _text(r).splitlines()[:2]
    assert head.split(",")[0] == "الرمز"
    assert sample.split(",")[0] == "V-001"
    # القالب يُستورد مباشرة بلا أخطاء (صف المثال صالح)
    imp = client.post("/exchange/vendors/import", headers=admin, files={
        "file": ("t.csv", r.content, "text/csv")})
    assert imp.status_code == 200, imp.text
    assert imp.json()["created"] == 1 and imp.json()["errors"] == []


def test_import_items_upserts_and_reports_errors(client, admin):
    """الدمج: الجديد يُضاف، الموجود يُحدَّث، والصف السيّئ لا يوقف الدفعة."""
    code = f"IM{uuid.uuid4().hex[:6]}"
    csv = _csv([
        ["الكود", "اسم الصنف", "الوحدة", "الكمية", "حد الأمان", "تكلفة الوحدة"],
        [code, "مستلزم جديد", "علبة", "30", "10", "7.25"],
        [f"IM{uuid.uuid4().hex[:6]}", "مستلزم خطأ", "علبة", "غير رقم", "5", "3"],
        ["", "بلا كود", "علبة", "5", "1", "2"],
    ])
    r = client.post("/exchange/items/import", headers=admin,
                    files={"file": ("items.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1 and body["skipped"] == 2
    assert {e["row"] for e in body["errors"]} == {3, 4}

    row = next(i for i in client.get("/general-stock/", headers=admin).json()
               if i["code"] == code)
    assert row["name"] == "مستلزم جديد" and row["unit_cost"] == 7.25
    assert row["quantity"] == 30 and row["min_quantity"] == 10

    # إعادة استيراد الملف نفسه ⇒ تحديث لا تكرار (الدمج طالما كان على المفتاح)
    again = client.post("/exchange/items/import", headers=admin, files={
        "file": ("items.csv", csv, "text/csv")})
    assert again.status_code == 200
    assert again.json()["created"] == 0 and again.json()["updated"] == 1
    codes = [i["code"] for i in client.get("/general-stock/", headers=admin).json()]
    assert codes.count(code) == 1


def test_import_accepts_english_headers_and_cp1256(client, admin):
    """العناوين الإنجليزية وترميز cp1256 (ملف قديم من Excel) يُقبلان أيضًا."""
    code = f"EN{uuid.uuid4().hex[:6]}"
    csv = _csv([["code", "name", "unit", "quantity", "unit_cost"],
               [code, "English header item", "pcs", "5", "2.5"]])
    r = client.post("/exchange/items/import", headers=admin, files={
        "file": ("x.csv", csv.decode().encode("cp1256"), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    row = next(i for i in client.get("/general-stock/", headers=admin).json()
               if i["code"] == code)
    assert row["name"] == "English header item" and row["unit"] == "pcs"


def test_import_validates_file_and_permissions(client, admin):
    """مورد مجهول · ملف فارغ · بلا عمود معروف · بلا عمود المفتاح · من غير مدير."""
    r = client.get("/exchange/nope/export.csv", headers=admin)
    assert r.status_code == 404 and "غير مدعوم" in r.json()["detail"]

    empty = client.post("/exchange/items/import", headers=admin,
                        files={"file": ("e.csv", b"", "text/csv")})
    assert empty.status_code == 400 and "فارغ" in empty.json()["detail"]

    unknown = _csv([["لا يعرف", "أ"], ["x", "y"]])
    r = client.post("/exchange/items/import", headers=admin,
                    files={"file": ("u.csv", unknown, "text/csv")})
    assert r.status_code == 400 and "عمود معروف" in r.json()["detail"]

    no_key = _csv([["اسم الصنف", "الوحدة"], ["بلا كود", "علبة"]])
    r = client.post("/exchange/items/import", headers=admin,
                    files={"file": ("k.csv", no_key, "text/csv")})
    assert r.status_code == 400 and "عمود المفتاح" in r.json()["detail"]

    # الصلاحيات: بلا توكن 401 · غير المدير 403 على الاستيراد
    uname = f"ex{uid()}"
    created = client.post("/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "full_name": "موظف",
        "role": "موظف استقبال", "password": "Passw0rd!"})
    rec = login(client, created.json()["username"], "Passw0rd!")
    payload = {"file": ("i.csv", _csv([["الكود", "اسم الصنف"],
                                       [f"Z{uid()}", "ممنوع"]]), "text/csv")}
    assert client.post("/exchange/items/import", files=payload).status_code == 401
    assert client.post("/exchange/items/import", headers=rec,
                       files=payload).status_code == 403
    # أما التصدير فمتاح لكل مسجّل
    assert client.get("/exchange/items/export.csv", headers=rec).status_code == 200


def test_roundtrip_export_then_import_is_idempotent(client, admin):
    """تصدير ثم استيراد الملف نفسه لا يغيّر شيئًا ولا يكرّر."""
    for key, path in (("vendors", "/accounts/ledger/vendors"),
                      ("departments", "/departments/")):
        code = f"RT{uuid.uuid4().hex[:6]}"
        body = ({"code": code, "name": f"مورد {code}", "phone": "0500000000"}
                if key == "vendors" else {"name": f"قسم {code}", "floor": "الأول"})
        assert client.post(path, headers=admin, json=body).status_code in (200, 201)

        exported = client.get(f"/exchange/{key}/export.csv", headers=admin)
        assert exported.status_code == 200
        r = client.post(f"/exchange/{key}/import", headers=admin, files={
            "file": (f"{key}.csv", exported.content, "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 0
        assert r.json()["updated"] >= 1 and r.json()["errors"] == []

    # المستودعات تُدمج بالأسماء (ولا يتكرر الافتراضي)
    r = client.get("/exchange/warehouses/export.csv", headers=admin)
    assert r.status_code == 200 and "الاسم" in _text(r).splitlines()[0]
    back = client.post("/exchange/warehouses/import", headers=admin, files={
        "file": ("w.csv", r.content, "text/csv")})
    assert back.status_code == 200 and back.json()["created"] == 0
