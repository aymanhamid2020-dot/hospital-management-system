"""اختبارات نظام التصميم الموحّد للطباعة (`app.print_kit`)."""
import pytest

PRIMARY_HEX = "#0f4c5c"

from app.print_kit import (
    BRAND, CONTENT_W, DANGER, PAGE, PRIMARY, PRINT_CSS, SUCCESS, Doc, ar,
    bars_html, foot_html, grid_html, head_html, ltr_html, money, page_html,
    sign_html, tiles_html,
)


def _doc(**kw) -> Doc:
    return Doc("اختبار", **kw)


# --------------------------------------------------------------------- أساسيات
def test_ar_reshapes_arabic_and_keeps_latin():
    out = ar("الإجمالي 100")
    assert "100" in out
    assert out != "الإجمالي 100"           # الحروف العربية أُعيد ترتيبها
    assert ar("Total 100") == "Total 100"  # اللاتيني لا يُمس


def test_money_formats_two_decimals_with_separators():
    assert money(0) == "0.00 \u0631.\u0633"      # العملة الافتراضية
    assert money(1234.5).startswith("1,234.50")
    assert money(None) == "0.00 \u0631.\u0633"
    assert money(10, "$") == "10.00 $"


def test_colors_are_three_channel_tuples():
    for name, val in (("PRIMARY", PRIMARY), ("DANGER", DANGER),
                      ("SUCCESS", SUCCESS)):
        assert len(val) == 3, name
        assert all(0 <= c <= 255 for c in val), name


def test_page_geometry_fits_a4():
    assert PAGE["w"] == pytest.approx(210, abs=0.5)
    assert PAGE["h"] == pytest.approx(297, abs=0.5)
    assert PAGE["mx"] > 0
    assert CONTENT_W == pytest.approx(PAGE["w"] - 2 * PAGE["mx"], abs=0.01)


# ----------------------------------------------------------------- توليد PDF
def test_output_returns_valid_pdf_bytes():
    data = _doc().output()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 900


def test_output_is_idempotent_and_does_not_grow():
    """استدعاء output() مرتين يجب ألا يضيف ترويسة/تذييلًا مكررًا."""
    d = _doc()
    first, second = d.output(), d.output()
    assert abs(len(first) - len(second)) < 40


def test_arabic_report_renders():
    d = _doc()
    d.section("توزيع الحالات")
    d.kv_grid([("المريض", "أحمد الشمسان"), ("رقم الملف", "77")])
    d.stat_tiles([("إجمالي", "148,500.00 ر.س")])
    d.table(["الحالة", "العدد"], [["مكتملة", "142"], ["معلقة", "26"]],
            totals=["الإجمالي", "194"])
    d.bars([("طبيب", 512), ("ممرض", 431)])
    d.note("تُراجع الأرقام قبل الاعتماد.")
    d.signatures()
    d.footer()
    assert d.output().startswith(b"%PDF-")


def test_table_with_no_rows_still_renders():
    d = _doc()
    d.table(["الحالة", "العدد"], [])
    d.footer()
    assert d.output().startswith(b"%PDF-")


def test_long_table_and_overflow_paginate():
    d = _doc()
    d.table(["م", "البيان"], [[str(i), f"سطر {i}" * 3] for i in range(90)])
    for _ in range(200):
        d.space(9)
    d.footer()
    assert d.output().startswith(b"%PDF-")


def test_stat_tiles_normalize_money():
    d = _doc()
    d.stat_tiles([("إجمالي", 148500.0), ("بانتظار", 0), ("متأخر", None)])
    d.footer()
    assert d.output().startswith(b"%PDF-")


def test_tone_marks_sensitive_status_without_raising():
    d = _doc()
    d.table(["الحالة", "العدد"],
            [["مكتملة", "1"], ["معلقة", "2"], ["متعثر", "3"]], tone_col=0)
    d.footer()
    assert d.output().startswith(b"%PDF-")


def test_paragraph_and_note_tolerate_long_arabic_text():
    d = _doc()
    d.paragraph("نص عربي طويل جدًا " * 60)
    d.note("ملاحظة " * 40)
    d.footer()
    assert d.output().startswith(b"%PDF-")


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_rtl_and_ltr_both_produce_pdf(lang):
    d = _doc(lang=lang)
    d.section("Section" if lang == "en" else "قسم")
    d.table(["A", "B"], [["1", "2"]])
    d.footer()
    assert d.output().startswith(b"%PDF-")


# ------------------------------------------------------------------ HTML/CSS
def test_print_css_has_no_unresolved_token_or_escaped_percent():
    assert "<<" not in PRINT_CSS and ">>" not in PRINT_CSS
    assert "%%" not in PRINT_CSS   # هروب %-formatting متبقٍّ كان يعطّل العرض
    assert "width: 100%" in PRINT_CSS


def test_print_css_preserves_colors_and_hides_chrome():
    assert "-webkit-print-color-adjust: exact" in PRINT_CSS
    assert "print-color-adjust: exact" in PRINT_CSS
    assert ".pk-actions { display: none; }" in PRINT_CSS  # الزر لا يُطبع


def test_print_css_defines_brand_variables():
    for var in ("--primary", "--accent", "--ink", "--muted", "--line",
                "--ok", "--danger", "--surface"):
        assert var in PRINT_CSS, var


def test_page_html_is_complete_document_with_direction():
    html = page_html("تقرير", "<p>محتوى</p>", "ar")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert 'dir="rtl"' in html and 'lang="ar"' in html
    assert PRIMARY_HEX in html         # CSS المشترك مدمج داخلًا
    assert "<p>محتوى</p>" in html
    en = page_html("Report", "", "en")
    assert 'lang="en"' in en and 'dir="ltr"' in en


def test_head_html_escapes_title_and_carries_identity():
    html = head_html("<script>x</script>", "ar", kind="تقرير", number="#7")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert BRAND["name_ar"] in html
    assert "#7" in html
    assert "pk-kind" in html


def test_head_html_subtitle_html_is_trusted_markup():
    """`subtitle_html` وسم موثوق (شارة حالة) يُدرَج كما هو، بخلاف subtitle."""
    html = head_html("t", "en", subtitle_html='<span class="badge ok">Paid</span>')
    assert '<span class="badge ok">Paid</span>' in html
    assert "Paid&lt;/span&gt;" not in html


def test_head_html_plain_subtitle_is_escaped():
    html = head_html("t", "en", subtitle="<b>bold</b>")
    assert "<b>bold</b>" not in html and "&lt;b&gt;" in html


def test_ltr_html_isolates_bidi_numbers():
    out = ltr_html("2026-09-27 14:32")
    assert 'dir="ltr"' in out and "unicode-bidi:isolate" in out
    assert "2026-09-27 14:32" in out


def test_grid_html_escapes_values():
    html = grid_html([("المريض", '<img src=x onerror="alert(1)">')])
    assert "<img" not in html and "&lt;img" in html


def test_tiles_html_accepts_two_or_three_elements():
    assert "pk-tile" in tiles_html([("عنوان", "قيمة")])
    assert 'class="pk-tile ok"' in tiles_html([("عنوان", "قيمة", "ok")])
    assert 'class="pk-tile danger"' in tiles_html([("عنوان", "قيمة", "danger")])


def test_bars_html_escapes_labels_and_survives_zero():
    html = bars_html([("جيد", 0), ("<script>", 5), ("ممتاز", 0)])
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "0%" in html            # القسمة على صفر لا تُنتج NaN


def test_bars_html_with_empty_items():
    assert isinstance(bars_html([]), str)


def test_sign_and_foot_html():
    sg = sign_html("أ", "ب")
    assert 'class="pk-sign"' in sg and "أ" in sg and "ب" in sg
    assert "pk-foot" in foot_html("ملاحظة", "ar")
    assert 'dir="ltr"' in foot_html("x", "en")

