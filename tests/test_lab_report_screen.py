"""شاشة إدخال النتيجة على هيئة تقرير الفحص.

الشاشة تحمل ما تحمله ورقة التقرير: بيانات المريض ورقم ملفه، بيانات الفحص
من الدليل (الرمز/المجموعة/الأنبوب/الصيام/حالته مفعّلًا أو موقوفًا)، النطاق
المرجعي، قراءة القيمة فيه لحظيًّا، ثم ورقة PDF بعد الحفظ.
"""
from pathlib import Path

from test_lab_lis import _mk_order, _mk_patient, _mk_test, _prep_sample
from test_api import uid


def _ready_order(client, admin, **cat_kw):
    """فحص + مريض + طلب عيّنته مستلمة — جاهز لإدخال النتيجة."""
    cat = _mk_test(client, admin, **cat_kw)
    pat = _mk_patient(client, admin)
    oid = _mk_order(client, admin, cat, pat)["id"]
    _prep_sample(client, admin, oid)
    return cat, pat, oid


# ================= بطاقة الفحص في الاستجابة =================
def test_order_carries_catalog_for_report(client, admin):
    cat, pat, oid = _ready_order(client, admin, ref_min=4.0, ref_max=11.0,
                                 specimen_group="دم كامل", fasting_hours=4)

    rows = client.get("/lab-orders/", headers=admin).json()
    row = next(o for o in rows if o["id"] == oid)
    c = row["catalog"]
    assert c is not None, "الطلب لا يحمل دليل الفحوصات — لا تقرير بلا رمز ومجموعة"
    assert c["code"] == cat["code"]
    assert c["specimen_group"] == "دم كامل"
    assert c["fasting_hours"] == 4 and c["tube_type"] == "EDTA"
    assert c["active"] is True                      # حالة الاختبار في الدليل
    assert c["ref_min"] == 4.0 and c["ref_max"] == 11.0
    assert c["unit"] == "g/dL"
    # رقم الملف يصعد مع الفحص حتى يعرف الطبيب أي مريض يقرأ
    assert row["patient"]["file_no"] == pat["file_no"]

    one = client.get(f"/lab-orders/{oid}", headers=admin).json()
    assert one["catalog"]["code"] == cat["code"]

    # طلب بلا ربط بالدليل ⇒ catalog = null بدل أن يفشل التحقّق
    plain = client.post("/lab-orders/", headers=admin, json={
        "patient_id": pat["id"], "test_name": "أشعة صدر"})
    assert plain.status_code == 200, plain.text
    assert plain.json()["catalog"] is None


def test_deactivated_test_shows_passive(client, admin):
    cat = _mk_test(client, admin, active=False)
    pat = _mk_patient(client, admin)
    oid = _mk_order(client, admin, cat, pat)["id"]
    row = next(o for o in client.get("/lab-orders/", headers=admin).json()
               if o["id"] == oid)
    assert row["catalog"]["active"] is False        # موقوف · passive


# ================= القيمة تبقى في التقرير =================
def test_result_stores_value_for_reopening(client, admin):
    cat, pat, oid = _ready_order(client, admin, ref_min=4.0, ref_max=11.0)
    j = client.post(f"/lab-orders/{oid}/result", headers=admin,
                    json={"result": "12.5", "value": 12.5}).json()
    assert j["value"] == 12.5
    assert j["abnormal"] and not j["critical"]

    # إعادة فتح الإدخال تجد القيمة الرقمية نفسها — لا تُستخرج من النص
    again = client.get(f"/lab-orders/{oid}", headers=admin).json()
    assert again["value"] == 12.5
    assert again["result"] == "12.5"

    # مسح القيمة (فحص نوعي) يعيد الحالة إلى «بلا نطاق»
    j = client.post(f"/lab-orders/{oid}/result", headers=admin,
                    json={"result": "سلبي", "value": None}).json()
    assert j["value"] is None and not j["abnormal"] and not j["critical"]


# ================= ورقة التقرير =================
def test_result_pdf_is_a_full_report(client, admin):
    cat, pat, oid = _ready_order(client, admin, ref_min=4.0, ref_max=11.0)
    client.post(f"/lab-orders/{oid}/result", headers=admin,
                json={"result": "14", "value": 14})

    ar = client.get(f"/lab-orders/{oid}/pdf", headers=admin)
    assert ar.status_code == 200 and ar.content[:5] == b"%PDF-", ar.status_code
    en = client.get(f"/lab-orders/{oid}/pdf", headers=admin,
                    params={"lang": "en"})
    assert en.status_code == 200 and en.content[:5] == b"%PDF-", en.status_code
    # عربية غير سليمة ⇒ 400 قبل انتهاء اللغة المدعومة
    assert client.get(f"/lab-orders/{oid}/pdf", headers=admin,
                      params={"lang": "zz"}).status_code == 400


def test_result_pdf_source_carry_range_and_flags():
    """بنود التقرير نفسها موجودة في مولّد الورقة (ar ومنفّذها en)."""
    root = Path(__file__).resolve().parent.parent
    src = (root / "app" / "pdf_utils.py").read_text(encoding="utf-8")
    for marker in ("def _lab_flag_ar(", "def _lab_flag_en(",
                   '"النطاق المرجعي"', '"القيمة المُدخلة"', '"حالة النتيجة"',
                   '"Value"', '"Reference range"', '"Interpretation"',
                   '"File #"', "file_no"):
        assert marker in src, f"بند تقرير مفقود من pdf_utils.py: {marker}"


# ================= مؤشرات الواجهة =================
def test_lab_report_ui_markers():
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    css = (root / "static" / "app.css").read_text(encoding="utf-8")
    for marker in ("function labSheetHTML(", "function labInterpHTML(",
                   "function labRangeBar(", "function labFlags(",
                   "function labReportPreview(", "function enterLabResult(",
                   "function labInterpLive(", "function labResultCell(",
                   "حالة الاختبار في الدليل", "مفعّل · active",
                   "موقوف · passive", "معاينة تقرير الفحص", "m-interp",
                   "lab-critical", "lab-high", "lab-normal", 'bdi dir="ltr"'):
        assert marker in js, f"علامة مفقودة في app.js: {marker}"
    # النطاق لا يُحاط بـ esc وإلا انقلب النطاق المعروض إلى «17 – 12»
    assert "esc(labRangeLabel(" not in js
    for marker in (".lab-sheet {", ".lab-bar-zone", ".lab-report-result",
                   ".lab-signs", ".lab-qual", ".pill.lab-high",
                   ".pill.lab-critical", ".lab-bar-dot.lab-high"):
        assert marker in css, f"قاعدة مفقودة في app.css: {marker}"
