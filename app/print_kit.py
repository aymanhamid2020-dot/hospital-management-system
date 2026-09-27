"""نظام تصميم المستندات المطبوعة — مصدر واحد للعلامة البصرية.

**لماذا هذا الملف؟** كان لكل مستند PDF/HTML رسمه الخاص بألوانه وإحداثياته،
فتشتّتت الهوية وتكرّر الكود 38 مرة. هنا **الشكل واحد** يُطبَّق على مسارين
للتوليد: PDF عبر fpdf2 وHTML عبر CSS، بنفس الألوان والوحدات والتدرّج.

مكوّناته:
- `TOKENS` ألوانBrand وسُلَّم خطوط و`rhythm` إيقاع مسافات.
- `Doc` غلاف PDF مُعلَّم الهوية: ترويسة، شارة نوع المستند، رقم وتاريخ،
  تذييل بترقيم صفحات، ومكوّنات: section/kv_grid/table/stat_tiles/bars.
- `PRINT_CSS` و`head_block`/`tiles_html`… لمقطوعات HTML بنفس هوية الـ PDF.
"""
from datetime import datetime
from io import BytesIO

from fpdf import FPDF

# ===== 1) رموز التصميم (Brand tokens) =====
# لوحة طبية هادئة: أزرق بترولي عميق + تركوازي — لا الأزرق الافتراضي.
# اللوحة: مصدر واحد — استوردها من `pdf_utils`
# (الوحة المشتركة أسفل من احتياج الوحدة ولا ازدواج
# للون في المستندات القديمة).
from app.pdf_utils import (ACCENT, DARK, GRAY, GREEN, LIGHT_BG,  # noqa: E402
                            PRIMARY, RED)

INK = DARK              # نص أساسي
MUTED = GRAY            # نص ثانوي
SURFACE = LIGHT_BG      # خلفية ناعمة
BAND = (222, 235, 239)  # شريط رأس الجدول
LINE = (203, 216, 221)  # خطوط فاصلة
WHITE = (255, 255, 255)
SUCCESS = GREEN
WARNING = (183, 121, 31)
DANGER = RED

# السلّم الطباعي: كل الأحجام مشتقّة من هذا السلّم (لا أرقام متفرّقة)
TYPE = {"doc": 19, "h1": 15, "h2": 12.5, "body": 10.5, "small": 9, "micro": 7.5}

# إيقاع المسافات (mm) — كل الفجوات مضاعفات له ⇒ إيقاع بصري ثابت
R = {"xs": 1.6, "sm": 3, "md": 5, "lg": 8, "xl": 12}

# هويّة المؤسسة (قابلة للتجاوز من البيئة)
BRAND = {
    "name_ar": "مستشفى و مركز صحي",
    "name_en": "Hospital & Medical Center",
    "tag_ar": "نظام إدارة المستشفيات والعيادات",
    "tag_en": "Hospital & Clinics Management System",
    "contact_ar": "الهاتف: ٠٥٠٠٠٠٠٠٠٠  ·  البريد: info@hospital.example",
    "contact_en": "Tel: 0500000000  ·  Email: info@hospital.example",
    "document_note_ar": "مستند مولّد إلكترونيًا — نظام إدارة المستشفيات والعيادات",
    "document_note_en": "Computer-generated document — HMS",
}

# هندسة الصفحة (A4 = 210×297mm)
PAGE = {"w": 210.0, "h": 297.0, "mx": 14.0, "top": 46.0, "bottom": 20.0}
CONTENT_W = PAGE["w"] - 2 * PAGE["mx"]


def ar(text) -> str:
    """تشكيل وعكس اتجاه النص العربي (مُستورد من pdf_utils لتفادي الدورة)."""
    from app.pdf_utils import ar as _ar
    return _ar(text)


def money(value, currency: str = None, lang: str = "ar") -> str:
    """تنسيق نقدي موحّد: 1,250.00 ر.ي.

    يتولى من صندورة العملة تماماً — الرمز يتبع من
    العملة الأساسية (الريال اليمني افتراضًا) وليس مثبّتًا.
    """
    from app.currency import format_money
    return format_money(value, currency, lang=lang)


def _env(key: str, default: str) -> str:
    import os
    return os.environ.get(key, default)




def _rrect(pdf, x, y, w, h, r, style="F"):
    """مستطيل بزوايا دائرية — متوافق مع كل إصدارات fpdf2.

    fpdf2 2.7+ وحّدها في `rect(..., round_corners=True)`، بينما الإصدارات
    الأقدم توفّر `rounded_rect`. طبقة توافق واحدة بدل تفرّق في كل مستند.
    """
    fn = getattr(pdf, "rounded_rect", None)
    if fn is not None:
        return fn(x, y, w, h, r, style)
    return pdf.rect(x, y, w, h, style, round_corners=True, corner_radius=r)


# ===== 2) غلاف المستند (PDF) =====
def draw_pdf_header(pdf, title: str, lang: str = "ar", kind: str = "",
                    number: str = "", subtitle: str = "", compact: bool = False,
                    font: str = "pk") -> float:
    """يرسم ترويسة الهوية الموحّدة ويُرجع `y` بداية المحتوى.

    دالة مستقلة (لا method) حتى يرثها `pdf_utils.ArabicPDF`، فيأخذ كل
    المستندات الـ 38 — الحالية والقديمة — هوية واحدة بلا ازدواج للكود.
    """
    rtl = lang != "en"
    p = pdf
    band_h = 26 if compact else 34
    p.set_fill_color(*PRIMARY)
    p.rect(0, 0, PAGE["w"], band_h, "F")
    p.set_fill_color(*ACCENT)
    p.rect(0, band_h, PAGE["w"], 1.4, "F")

    # كتلة الهوية داخل الشريط: شعار + اسم الجهة (بلا تجاوز للحدود)
    logo = 13.0
    p.set_fill_color(*ACCENT)
    _rrect(p, PAGE["mx"], 6.5, logo, logo, 3.2, "F")
    p.set_fill_color(*WHITE)
    p.rect(PAGE["mx"] + 5.1, 8.6, 2.8, 8.8, "F")
    p.rect(PAGE["mx"] + 2.2, 11.5, 8.6, 2.8, "F")

    name = BRAND["name_ar"] if rtl else BRAND["name_en"]
    tag = BRAND["tag_ar"] if rtl else BRAND["tag_en"]
    contact = BRAND["contact_ar"] if rtl else BRAND["contact_en"]
    block_x = PAGE["mx"] + logo + 4
    block_w = 96.0
    y0 = 7.2 if not compact else 8.0
    # كل سطر يُثبَّت عند x: `cell` يُقدّم المؤشر بعد كل نداء
    p.set_xy(block_x, y0)
    p.set_font(font, "B", 12 if not compact else 11)
    p.set_text_color(*WHITE)
    p.cell(block_w, 6, ar(name), align="L")
    p.set_xy(block_x, y0 + 6)
    p.set_font(font, "", 7.2)
    p.set_text_color(198, 221, 228)
    p.cell(block_w, 4.4, ar(tag), align="L")
    if not compact:
        p.set_xy(block_x, y0 + 10.6)
        p.set_font(font, "", 6.4)
        p.set_text_color(165, 197, 206)
        p.cell(block_w, 4.2, ar(contact), align="L")

    # العنوان **أسفل الشريط** على خلفية بيضاء (داخله كان داكنًا على غامق)
    y = band_h + R["lg"]
    p.set_xy(PAGE["mx"], y)
    p.set_font(font, "B", TYPE["h1"] if not compact else 14)
    p.set_text_color(*INK)
    p.cell(CONTENT_W - 34, 8, ar(title), align="R" if rtl else "L")
    if kind:                          # شارة النوع على الطرف المقابل
        kw = p.get_string_width(ar(kind)) + 5
        p.set_fill_color(*ACCENT)
        _rrect(p, PAGE["mx"], y + 0.4, kw, 5.6, 1.6, "F")
        p.set_xy(PAGE["mx"], y + 1.7)
        p.set_font(font, "B", 8.2)
        p.set_text_color(*WHITE)
        p.cell(kw, 4, ar(kind), align="C")

    # سطر الميتا: الرقم + التاريخ (محاذاة عكسية للاتجاه)
    p.set_xy(PAGE["mx"], y + 8.6)
    p.set_font(font, "", TYPE["micro"])
    p.set_text_color(*MUTED)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta = (f"{ar('رقم')}: {ar(str(number))}   " if number else "")
    meta += f"{ar('تاريخ الإصدار')}: {stamp}"
    p.cell(CONTENT_W, 4.6, meta, align="R" if rtl else "L")
    bottom = y + 13.4
    if subtitle:
        p.set_xy(PAGE["mx"], bottom)
        p.set_font(font, "", TYPE["small"])
        p.set_text_color(*PRIMARY)
        p.cell(CONTENT_W, 4.6, ar(subtitle), align="R" if rtl else "L")
        bottom += 5.4
    p.set_draw_color(*LINE)
    p.set_line_width(0.25)
    p.line(PAGE["mx"], bottom, PAGE["w"] - PAGE["mx"], bottom)
    return bottom + R["md"]


def draw_pdf_footer(pdf, lang: str = "ar", font: str = "pk",
                    note: str = "", title: str = "") -> None:
    """تذييل موحّد: خط فاصل + نسبة المستند + عنوان + «صفحة س/ص».

    corner بزوايا: النسبة في الوسط، والعنوان و«صفحة س/ص» في الطرفين —
    لفصل التذييل عن المحتوى حتى في المستندات الطويلة. `{nb}` يُستبدل
    تلقائيًا بعد `alias_nb_pages()`.
    """
    rtl = lang != "en"
    p = pdf
    p.set_y(-PAGE["bottom"] + 8)
    p.set_draw_color(*LINE)
    p.set_line_width(0.2)
    p.line(PAGE["mx"], p.get_y(), PAGE["w"] - PAGE["mx"], p.get_y())
    p.set_y(p.get_y() + 1.6)
    p.set_font(font, "", TYPE["micro"])
    p.set_text_color(*MUTED)
    p.set_xy(PAGE["mx"], p.get_y())
    p.cell(CONTENT_W, 4, ar(note or (BRAND["document_note_ar"] if rtl
                                    else BRAND["document_note_en"])),
           align="C")
    pages = f"{p.page_no()}/{{nb}}"
    base = p.get_y() + 4.2
    if rtl:
        p.set_xy(PAGE["mx"], base)
        p.cell(CONTENT_W, 4, f"{ar('صفحة')} {pages}", align="R")
        p.set_xy(PAGE["mx"], base)
        p.cell(CONTENT_W, 4, ar(title), align="L")
    else:
        p.set_xy(PAGE["mx"], base)
        p.cell(CONTENT_W, 4, title, align="L")
        p.set_xy(PAGE["mx"], base)
        p.cell(CONTENT_W, 4, f"Page {pages}", align="R")


class Doc:
    """مستند PDF مُعلَّم الهوية بمكوّنات جاهزة.

    الاستخدام:
        d = Doc("فاتورة", kind="فاتورة", number=f"INV-{inv.id}")
        d.kv_grid([("المريض", name), ("التاريخ", today)], cols=2)
        d.table(["البند", "المبلغ"], rows, money_cols=[1])
        d.stat_tiles([("إجمالي", money(total))])
    """

    def __init__(self, title: str, lang: str = "ar", kind: str = "",
                 number: str = "", subtitle: str = "", compact: bool = False):
        from app.pdf_utils import FONT_REGULAR, FONT_BOLD

        if not FONT_REGULAR:
            raise RuntimeError(
                "لم يُعثر على خط عربي: ثبّت Arial أو fonts-dejavu-core "
                "أو حدّد HMS_FONT_REGULAR")
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.lang = lang if lang in ("ar", "en") else "ar"
        self.rtl = self.lang == "ar"
        self.kind = kind
        self.number = str(number or "")
        self.subtitle = subtitle
        self.title = title
        self._bytes = None      # ناتج PDF المخزّن (idempotent)
        self._footed = False
        self.compact = compact          # إيصالات: ترويسة أصغر ومساحة أضيق
        self.pdf.add_font("pk", "", FONT_REGULAR)
        self.pdf.add_font("pk", "B", FONT_BOLD or FONT_REGULAR)
        self.pdf.set_auto_page_break(True, margin=PAGE["bottom"])
        self.pdf.alias_nb_pages()
        self._add_page()

    # ---------- ترويسة وتذييل ----------
    def _add_page(self):
        self.pdf.add_page()
        self.pdf.set_margins(PAGE["mx"], PAGE["top"], PAGE["mx"])
        self.pdf.set_auto_page_break(True, margin=PAGE["bottom"])
        self._draw_header()

    def _draw_header(self):
        self._body_top = draw_pdf_header(
            self.pdf, self.title, self.lang, self.kind, self.number,
            self.subtitle, self.compact, font="pk")
        self.pdf.set_y(self._body_top)

    def _chip(self, text: str, color=ACCENT, size: float = 8.2):
        """شارة صغيرة ملوّنة (نوع المستند / حالة)."""
        p = self.pdf
        w = p.get_string_width(ar(text)) + 5
        x = PAGE["mx"] if self.rtl else PAGE["w"] - PAGE["mx"] - w
        y = p.get_y() - 0.4
        p.set_fill_color(*color)
        _rrect(p, x, y, w, 5.6, 1.6, "F")
        p.set_xy(x, y + 1.25)
        p.set_font("pk", "B", size)
        p.set_text_color(*WHITE)
        p.cell(w, 4, ar(text), align="C")
        p.set_xy(PAGE["mx"], y + 6.4)

    def footer(self):
        """تذييل واحد — نفس الدالة `draw_pdf_footer`."""
        if self._footed:
            return                       # تذييل واحد لكل صفحة (تعيدة)
        draw_pdf_footer(self.pdf, self.lang, "pk", title=self.title)
        self._footed = True

    def space(self, h_mm: float):
        """مسافة رأسية ضمن الإيقاع."""
        self.pdf.ln(h_mm)

    def ensure(self, h_mm: float):
        """قفز صفحة إن لم يتبقَّ ارتفاع كافٍ (يمنع الأيتام أسفل الصفحة)."""
        p = self.pdf
        if p.get_y() + h_mm > PAGE["h"] - PAGE["bottom"]:
            self._add_page()

    def section(self, title: str, note: str = ""):
        """عنوان قسم: شريط لوني + خط فاصل — يفصل المحتوى بصريًا.

        الملاحظة في **سطر مستقل** أسفل العنوان (كانت تتراكب معه).
        """
        p = self.pdf
        self.ensure(16)
        self.space(R["sm"])
        y = p.get_y()
        p.set_fill_color(*SURFACE)
        p.rect(PAGE["mx"], y - 1, CONTENT_W, 8.4, "F")
        p.set_fill_color(*ACCENT)
        bar_x = (PAGE["w"] - PAGE["mx"] - 1.8) if self.rtl else PAGE["mx"]
        p.rect(bar_x, y - 1, 1.8, 8.4, "F")
        p.set_xy(PAGE["mx"] + 2.4, y + 0.6)
        p.set_font("pk", "B", TYPE["h2"])
        p.set_text_color(*PRIMARY)
        p.cell(CONTENT_W - 4.8, 6, ar(title), align="R" if self.rtl else "L")
        p.set_y(y + 9.2)
        if note:
            p.set_font("pk", "", TYPE["small"])
            p.set_text_color(*MUTED)
            p.set_xy(PAGE["mx"] + 2.4, p.get_y())
            p.cell(CONTENT_W - 4.8, 4.8, ar(note), align="R" if self.rtl else "L")
            p.set_y(p.get_y() + 5.4)

    def kv_grid(self, pairs, cols: int = 2):
        """شبكة (تسمية: قيمة) — بديل مصفّ عن تكرار kv_row.

        التسمية أعلى والقيمة أسفلها داخل الخانة نفسها (كانا متراكبين).
        """
        p = self.pdf
        pairs = list(pairs or [])
        if not pairs:
            return
        col_w = CONTENT_W / cols
        row_h = 10.0
        for start in range(0, len(pairs), cols):
            chunk = pairs[start:start + cols]
            self.ensure(row_h)
            top = p.get_y()
            for i, item in enumerate(chunk):
                label, value = item[0], (item[1] if len(item) > 1 else "")
                x = (PAGE["w"] - PAGE["mx"] - (i + 1) * col_w) if self.rtl \
                    else PAGE["mx"] + i * col_w
                p.set_draw_color(*LINE)
                p.set_line_width(0.15)
                p.rect(x + 0.6, top, col_w - 1.2, row_h - 1.4)
                p.set_xy(x + 2.6, top + 1.2)
                p.set_font("pk", "", TYPE["micro"])
                p.set_text_color(*MUTED)
                p.cell(col_w - 5.2, 3.8, ar(label), align="R" if self.rtl else "L")
                p.set_xy(x + 2.6, top + 5.0)
                p.set_font("pk", "B", TYPE["body"])
                p.set_text_color(*INK)
                p.cell(col_w - 5.2, 4.6, ar(value), align="R" if self.rtl else "L")
            p.set_y(top + row_h)

    def stat_tiles(self, tiles, color=PRIMARY):
        """بطاقات مؤشرات (KPI) — تجعل التقارير تُقرأ في ثانية."""
        p = self.pdf
        tiles = list(tiles or [])
        if not tiles:
            return
        n = len(tiles)
        gap = 2.5
        w = (CONTENT_W - gap * (n - 1)) / n
        h = 15.5
        self.ensure(h + 4)
        y = p.get_y()
        for i, tile in enumerate(tiles):
            label, value = tile[0], tile[1]
            tone = tile[2] if len(tile) > 2 else color
            x = (PAGE["w"] - PAGE["mx"] - (i + 1) * w - i * gap) if self.rtl \
                else PAGE["mx"] + i * (w + gap)
            p.set_fill_color(*SURFACE)
            _rrect(p, x, y, w, h, 2, "F")
            p.set_fill_color(*tone)
            p.rect(x, y, 1.5, h, "F")
            p.set_xy(x + 3, y + 2.4)
            p.set_font("pk", "", TYPE["micro"])
            p.set_text_color(*MUTED)
            p.cell(w - 5, 4, ar(label), align="R" if self.rtl else "L")
            p.set_xy(x + 3, y + 6.6)
            p.set_font("pk", "B", 13)
            p.set_text_color(*tone)
            p.cell(w - 5, 7, ar(value), align="R" if self.rtl else "L")
        p.set_y(y + h + R["sm"])

    def note(self, text: str, kind: str = "muted"):
        """تذييل ملاحظة/إشعار بلون دلالي."""
        p = self.pdf
        tones = {"muted": MUTED, "ok": SUCCESS, "warn": WARNING, "danger": DANGER}
        tone = tones.get(kind, MUTED)
        self.ensure(12)
        y = p.get_y()
        h = 8.4 if len(str(text)) < 90 else 12.6
        p.set_fill_color(*SURFACE)
        p.rect(PAGE["mx"], y, CONTENT_W, h, "F")
        p.set_fill_color(*tone)
        p.rect((PAGE["w"] - PAGE["mx"] - 1.6) if self.rtl else PAGE["mx"],
               y, 1.6, h, "F")
        p.set_xy(PAGE["mx"] + 2.6, y + 2.2)
        p.set_font("pk", "", TYPE["small"])
        p.set_text_color(*INK)
        p.multi_cell(CONTENT_W - 5, 4.6, ar(text), align="R" if self.rtl else "L")
        p.set_y(y + h + R["sm"])

    def paragraph(self, text: str, size: float = None, color=INK, bold=False):
        p = self.pdf
        p.set_font("pk", "B" if bold else "", size or TYPE["body"])
        p.set_text_color(*color)
        p.multi_cell(0, 6, ar(text), align="R" if self.rtl else "L")
        p.ln(1)

    def signatures(self, left: str = "توقيع المحاسب", right: str = "توقيع المسؤول"):
        """سطرا توقيع — للإيصالات والفواتير."""
        p = self.pdf
        self.space(R["xl"])
        self.ensure(18)
        y = p.get_y()
        half = CONTENT_W / 2
        for i, label in enumerate((left, right)):
            x = (PAGE["w"] - PAGE["mx"] - (i + 1) * half) if self.rtl \
                else PAGE["mx"] + i * half
            p.set_draw_color(*MUTED)
            p.set_line_width(0.2)
            p.line(x + 6, y, x + half - 6, y)
            p.set_xy(x, y + 1.6)
            p.set_font("pk", "", TYPE["small"])
            p.set_text_color(*MUTED)
            p.cell(half, 4.5, ar(label), align="C")
        p.set_y(y + 8)

    def output(self) -> bytes:
        """يُعيد المستند كـ PDF (مرة واحدة) — النداءات التالية تعيد نفس البايتات."""
        if self._bytes is None:
            self.pdf.set_auto_page_break(False)
            self.footer()
            self._bytes = bytes(self.pdf.output())
        return self._bytes


    # ---------- الجداول والرسوم ----------
    def table(self, headers, rows, aligns=None, money_cols=(), widths=None,
              totals=None, row_h: float = 7.2, head_h: float = 8.2,
              tone_col: int = None):
        """جدول نظيف: رأس ملوّن يتكرر عبر الصفحات، صفوف متبادلة، صف إجمالي.

        - `aligns`: محاذاة كل عمود "L"/"C"/"R" (افتراضي: يمين للعربية).
        - `money_cols`: أعمدة نقدية تُنسَّق بفواصل الآلاف.
        - `widths`: نسب أعمدة (تجمع 1).
        - `totals`: صف ملخّص يُلوَّن بلون الهوية.
        - `tone_col`: عمود قيمته تحدّد لون الصف (تنبيهohlص).
        """
        p = self.pdf
        n = len(headers)
        if not n:
            return
        aligns = list(aligns or ["R" if self.rtl else "L"] * n)
        if widths is None:
            first = 1.9 if n <= 4 else 1.5
            widths = [first] + [1.0] * (n - 1)
        total_w = sum(widths)
        widths = [CONTENT_W * w / total_w for w in widths]
        money_cols = set(money_cols or ())

        def draw_head(y0: float):
            """رأس الجدول عند ارتفاع مُحدَّد. (يجب تثبيت y: `set_xy` يغيّر get_y)"""
            p.set_fill_color(*PRIMARY)
            p.rect(PAGE["mx"], y0, CONTENT_W, head_h, "F")
            for i, htxt in enumerate(headers):
                x = (PAGE["w"] - PAGE["mx"] - sum(widths[:i + 1])) if self.rtl \
                    else PAGE["mx"] + sum(widths[:i])
                p.set_xy(x + 1.6, y0 + 2.4)
                p.set_font("pk", "B", TYPE["small"])
                p.set_text_color(*WHITE)
                p.cell(widths[i] - 3.2, 4.6, ar(htxt), align=aligns[i])

        self.ensure(head_h + row_h)
        y = p.get_y()
        draw_head(y)
        p.set_y(y + head_h)
        for idx, row in enumerate(rows):
            self.ensure(row_h + 2)
            y = p.get_y()          # ارتفاع الصف يُثبَّت قبل رسم خلاياه
            if idx % 2 == 1:
                p.set_fill_color(248, 250, 251)
                p.rect(PAGE["mx"], y, CONTENT_W, row_h, "F")
            for i, cell in enumerate(row[:n]):
                x = (PAGE["w"] - PAGE["mx"] - sum(widths[:i + 1])) if self.rtl \
                    else PAGE["mx"] + sum(widths[:i])
                txt = ar(cell)
                if i in money_cols:
                    try:
                        txt = ar(f"{float(str(cell).replace(',', '')):,.2f}")
                    except (TypeError, ValueError):
                        pass
                p.set_xy(x + 1.6, y + 2.1)
                p.set_font("pk", "", TYPE["small"])
                color = INK
                if tone_col is not None and i == tone_col:
                    raw = str(cell).lower()
                    color = (DANGER if raw in ("danger", "متعثر", "متأخر")
                             else SUCCESS if raw in ("ok", "مقبوض", "مكتمل")
                             else WARNING if raw in ("warn", "جزئي")
                             else INK)
                p.set_text_color(*color)
                p.cell(widths[i] - 3.2, 4.4, txt, align=aligns[i])
            p.set_draw_color(*LINE)
            p.set_line_width(0.1)
            p.line(PAGE["mx"], y + row_h, PAGE["w"] - PAGE["mx"], y + row_h)
            p.set_y(y + row_h)
        if totals:
            self.ensure(row_h + 3)
            y = p.get_y()
            p.set_fill_color(*BAND)
            p.rect(PAGE["mx"], y, CONTENT_W, row_h + 1.2, "F")
            for i, cell in enumerate(totals[:n]):
                x = (PAGE["w"] - PAGE["mx"] - sum(widths[:i + 1])) if self.rtl \
                    else PAGE["mx"] + sum(widths[:i])
                txt = ar(cell)
                if i in money_cols:
                    try:
                        txt = ar(f"{float(str(cell).replace(',', '')):,.2f}")
                    except (TypeError, ValueError):
                        pass
                p.set_xy(x + 1.6, y + 2.6)
                p.set_font("pk", "B", TYPE["small"])
                p.set_text_color(*PRIMARY)
                p.cell(widths[i] - 3.2, 4.6, txt, align=aligns[i])
            p.set_y(y + row_h + 1.2)
        self.space(R["sm"])

    def bars(self, items, unit: str = "", color=ACCENT, max_rows: int = 8):
        """أشرطة أفقية بسيطة — يحوّل الأرقام إلى صورة تُقرأ في ثانية.

        الهندسة تتبع اتجاه المستند: في العربية الشريط ينمو **من اليمين
        لليسار** والمسار والتعبئة يبدأان من نفس الحافة (كانا يفترقان).
        """
        p = self.pdf
        items = [i for i in (items or []) if i][:]
        if not items:
            return
        items = sorted(items, key=lambda kv: float(kv[1] or 0), reverse=True)[:max_rows]
        top = max((float(v or 0) for _k, v in items), default=1) or 1
        label_w, value_w = 44.0, 20.0
        track_x = PAGE["mx"] + label_w + 3
        bar_w = CONTENT_W - label_w - value_w - 6
        for label, value in items:
            self.ensure(9)
            y = p.get_y()
            # التسمية على جهة البداية
            p.set_font("pk", "", TYPE["small"])
            p.set_text_color(*INK)
            p.set_xy((PAGE["w"] - PAGE["mx"] - label_w) if self.rtl
                     else PAGE["mx"], y + 1.2)
            p.cell(label_w, 4.6, ar(label), align="R" if self.rtl else "L")
            # المسار والتعبئة من نفس الحافة
            frac = max(0.02, min(1.0, float(value or 0) / top))
            p.set_fill_color(*SURFACE)
            _rrect(p, track_x, y + 1.4, bar_w, 4.4, 1.2, "F")
            fill_x = (track_x + bar_w - bar_w * frac) if self.rtl else track_x
            p.set_fill_color(*color)
            _rrect(p, fill_x, y + 1.4, bar_w * frac, 4.4, 1.2, "F")
            # القيمة على الطرف المقابل
            p.set_xy(PAGE["mx"] if self.rtl
                     else PAGE["w"] - PAGE["mx"] - value_w, y + 1.2)
            p.set_font("pk", "B", TYPE["small"])
            p.set_text_color(*PRIMARY)
            p.cell(value_w, 4.6, ar(f"{float(value or 0):,.0f}{unit}"),
                   align="L" if self.rtl else "R")
            p.set_y(y + 7.6)
        self.space(R["xs"])



# ===== 3) نفس الهوية لمقطوعات HTML (الطباعة من المتصفح) =====
# نفس رموز العلامة أعلاه مترجمة إلى CSS: ما تراه في PDF تراه في المتصفح.
CSS_TOKENS = {"ink": "#%02x%02x%02x" % INK, "muted": "#%02x%02x%02x" % MUTED,
              "primary": "#%02x%02x%02x" % PRIMARY,
              "accent": "#%02x%02x%02x" % ACCENT,
              "surface": "#%02x%02x%02x" % SURFACE,
              "band": "#%02x%02x%02x" % BAND, "line": "#%02x%02x%02x" % LINE,
              "ok": "#%02x%02x%02x" % SUCCESS, "warn": "#%02x%02x%02x" % WARNING,
              "danger": "#%02x%02x%02x" % DANGER}

PRINT_CSS = """
:root {
  --ink: <<ink>>; --muted: <<muted>>; --primary: <<primary>>; --accent: <<accent>>;
  --surface: <<surface>>; --band: <<band>>; --line: <<line>>;
  --ok: <<ok>>; --warn: <<warn>>; --danger: <<danger>>;
  --r: 10px; --r-sm: 6px;
}
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Arial, sans-serif; margin: 0;
       background: #eef2f5; color: var(--ink);
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.sheet { background: #fff; max-width: 860px; margin: 24px auto; padding: 0;
         border-radius: var(--r); box-shadow: 0 10px 34px rgba(16,42,67,.13);
         overflow: hidden; }

/* ---------- الترويسة الموحّدة (نفس هوية الـ PDF) ---------- */
.pk-head { background: var(--primary); color: #fff; padding: 20px 26px 18px;
           display: flex; align-items: flex-start; gap: 16px;
           border-bottom: 3px solid var(--accent); }
.pk-mark { width: 46px; height: 46px; border-radius: 11px;
           background: var(--accent); display: grid; place-items: center; flex: none; }
.pk-mark::before { content: ''; width: 22px; height: 22px; position: relative;
                   background:
                     linear-gradient(#fff, #fff) center/8px 100% no-repeat,
                     linear-gradient(#fff, #fff) center/100% 8px no-repeat;
                   border-radius: 2px; }
.pk-org { flex: 1; }
.pk-org b { display: block; font-size: 17px; letter-spacing: .2px; }
.pk-org span { font-size: 11.5px; opacity: .82; }
.pk-org small { display: block; font-size: 10.5px; opacity: .7; margin-top: 3px; }
.pk-docinfo { text-align: end; }
.pk-docinfo h1 { margin: 0; font-size: 20px; font-weight: 700; }
.pk-meta { font-size: 10.5px; opacity: .78; margin-top: 4px; }
.pk-kind { display: inline-block; margin-top: 7px; padding: 3px 11px;
           border-radius: 999px; background: var(--accent); color: #fff;
           font-size: 10.5px; font-weight: 700; letter-spacing: .3px; }

/* ---------- الأقسام والجداول ---------- */
.pk-body { padding: 22px 26px 8px; }
.pk-section { margin: 20px 0 10px; background: var(--surface);
              border-inline-start: 4px solid var(--accent);
              border-radius: var(--r-sm); padding: 9px 13px;
              color: var(--primary); font-weight: 700; font-size: 13.5px; }
.pk-section:first-child { margin-top: 0; }
.pk-grid { display: grid; gap: 8px; }
.pk-grid.c2 { grid-template-columns: 1fr 1fr; }
.pk-grid.c3 { grid-template-columns: repeat(3, 1fr); }
.pk-field { border: 1px solid var(--line); border-radius: var(--r-sm);
           padding: 7px 11px; background: #fff; }
.pk-field i { display: block; font-style: normal; font-size: 10.5px;
              color: var(--muted); margin-bottom: 2px; }
.pk-field b { font-size: 12.5px; }
table { width: 100%; border-collapse: separate; border-spacing: 0;
        font-size: 12px; margin-top: 4px; }
th { background: var(--primary); color: #fff; font-weight: 700; padding: 9px;
     text-align: start; }
th:first-child { border-start-start-radius: var(--r-sm); }
th:last-child { border-start-end-radius: var(--r-sm); }
td { padding: 8px 9px; border-bottom: 1px solid var(--line); }
tbody tr:nth-child(even) { background: #f8fafb; }
tfoot td { background: var(--band); color: var(--primary); font-weight: 700;
           border-bottom: none; }

/* ---------- بطاقات المؤشرات والملاحظات ---------- */
.pk-tiles { display: flex; flex-wrap: wrap; gap: 9px; margin: 6px 0 4px; }
.pk-tile { flex: 1 1 150px; }
.pk-tile { background: var(--surface); border-radius: var(--r-sm);
           border-inline-start: 4px solid var(--primary); padding: 10px 12px; }
.pk-tile i { display: block; font-style: normal; font-size: 10.5px;
             color: var(--muted); }
.pk-tile b { font-size: 16px; }
.pk-tile.ok { border-color: var(--ok); } .pk-tile.ok b { color: var(--ok); }
.pk-tile.warn { border-color: var(--warn); } .pk-tile.warn b { color: var(--warn); }
.pk-tile.danger { border-color: var(--danger); }
.pk-tile.danger b { color: var(--danger); }
.pk-note { background: var(--surface); border-inline-start: 4px solid var(--muted);
           border-radius: var(--r-sm); padding: 10px 13px; font-size: 12px;
           color: var(--ink); margin-top: 10px; }
.pk-note.ok { border-color: var(--ok); }
.pk-note.warn { border-color: var(--warn); }
.pk-note.danger { border-color: var(--danger); }
.badge { display: inline-block; padding: 3px 11px; border-radius: 999px;
         font-size: 11px; font-weight: 700; }
.badge.paid, .badge.ok { background: #e6f4ec; color: #1b8a5a; }
.badge.partial, .badge.warn { background: #fdf3e2; color: #b7791f; }
.badge.unpaid, .badge.danger { background: #fdeceb; color: #c0392b; }

/* ---------- التذييل والتوقيع والرسوم ---------- */
.pk-sign { display: grid; grid-template-columns: 1fr 1fr; gap: 40px;
           margin: 34px 26px 0; }
.pk-sign div { border-top: 1px solid var(--muted); padding-top: 7px;
               text-align: center; font-size: 11.5px; color: var(--muted); }
.pk-foot { margin-top: 18px; padding: 14px 26px 18px;
           border-top: 1px solid var(--line);
           display: flex; justify-content: space-between; gap: 12px;
           font-size: 10.5px; color: var(--muted); }
.pk-bar { height: 7px; border-radius: 4px; background: var(--surface);
          overflow: hidden; margin-top: 4px; }
.pk-bar > i { display: block; height: 100%; background: var(--accent); }
.pk-bars { display: grid; gap: 7px; margin-top: 4px; }
.pk-bars .row { display: grid; grid-template-columns: 130px 1fr 62px;
                align-items: center; gap: 9px; font-size: 11.5px; }
.pk-actions { text-align: center; padding: 6px 26px 24px; }
.pk-actions button { background: var(--primary); color: #fff; border: 0;
                     padding: 11px 30px; border-radius: var(--r-sm);
                     font-size: 14px; cursor: pointer; font-weight: 600; }
.pk-actions button:hover { background: var(--accent); }

@media print {
  body { background: #fff; }
  .sheet { box-shadow: none; border-radius: 0; margin: 0; max-width: 100%; }
  .pk-actions { display: none; }
  @page { margin: 10mm; }
}
"""
for _k, _v in CSS_TOKENS.items():
    PRINT_CSS = PRINT_CSS.replace("<<" + _k + ">>", _v)


def ltr_html(value) -> str:
    """يعزل نصًا لاتينيًا (تاريخ/رقم) داخل سياق RTL حتى لا يُقلب ترتيبه.

    بدون هذا يظهر «2026-09-27 14:32» مقلوبًا: «14:32 2026-09-27».
    """
    import html as _h

    return f'<span dir="ltr" style="display:inline-block;unicode-bidi:isolate">' \
           f'{_h.escape(str(value))}</span>'


def head_html(title: str, lang: str = "ar", kind: str = "", number: str = "",
              subtitle: str = "", subtitle_html: str = "") -> str:
    """ترويسة HTML بنفس هوية الـ PDF (شعار + جهة + عنوان + رقم + تاريخ).

    `subtitle` نص يُهرَّب (escape)، و`subtitle_html` وسم موثوق (شارة حالة مثلًا)
    يُدرَج كما هو. التاريخ والقيم اللاتينية تُعزل بـ `ltr_html` حتى لا تنقلب.
    """
    import html as _h

    rtl = lang == "ar"
    org = BRAND["name_ar"] if rtl else BRAND["name_en"]
    tag = BRAND["tag_ar"] if rtl else BRAND["tag_en"]
    contact = BRAND["contact_ar"] if rtl else BRAND["contact_en"]
    stamp = ltr_html(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lnum = "رقم" if rtl else "No."
    ldate = "تاريخ الإصدار" if rtl else "Issued"
    sub = ""
    if subtitle_html:
        sub = f'<div class="pk-meta">{subtitle_html}</div>'
    elif subtitle:
        sub = f'<div class="pk-meta">{_h.escape(subtitle)}</div>'
    num = (f'<span>{_h.escape(lnum)} {_h.escape(str(number))} &nbsp;·&nbsp; '
           f'{_h.escape(ldate)} {stamp}</span>' if number
           else f'<span>{_h.escape(ldate)} {stamp}</span>')
    badge = f'<span class="pk-kind">{_h.escape(kind)}</span>' if kind else ""
    return f"""<header class="pk-head">
  <div class="pk-mark"></div>
  <div class="pk-org"><b>{_h.escape(org)}</b><span>{_h.escape(tag)}</span>
    <small>{_h.escape(contact)}</small></div>
  <div class="pk-docinfo"><h1>{_h.escape(title)}</h1>{sub}{num}{badge}</div>
</header>"""


def foot_html(note: str = "", lang: str = "ar") -> str:
    """تذييل HTML: ملاحظة + وسم مولّد إلكترونيًا (نص الـ PDF نفسه)."""
    import html as _h

    line = (f"{BRAND['tag_ar']} — مستند مولّد إلكترونيًا" if lang == "ar"
            else f"{BRAND['tag_en']} — computer-generated document")
    left = f'<div class="pk-note">{_h.escape(note)}</div>' if note else ""
    return f"""{left}
<footer class="pk-foot"><span>{_h.escape(line)}</span>
  <span>{ltr_html(datetime.now().strftime('%Y-%m-%d %H:%M'))}</span></footer>"""


def page_html(title: str, body: str, lang: str = "ar") -> str:
    """غلاف HTML كامل + زر طباعة، بنفس نظام التصميم."""
    import html as _h

    rtl = "rtl" if lang == "ar" else "ltr"
    btn = "🖨️ طباعة" if lang == "ar" else "🖨️ Print"
    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{rtl}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h.escape(title)}</title>
<style>{PRINT_CSS}</style>
</head>
<body>
<div class="sheet">
{body}
<div class="pk-actions"><button onclick="window.print()">{btn}</button></div>
</div>
</body>
</html>"""


def tiles_html(tiles) -> str:
    """بطاقات مؤشرات HTML — نفس مكوّن `Doc.stat_tiles`."""
    import html as _h

    out = [f'<div class="pk-tile {t[2] if len(t) > 2 else ""}">'
           f'<i>{_h.escape(str(t[0]))}</i><b>{_h.escape(str(t[1]))}</b></div>'
           for t in (tiles or [])]
    return f'<div class="pk-tiles">{"".join(out)}</div>'


def grid_html(pairs, cols: int = 2) -> str:
    """شبكة حقول HTML — نفس مكوّن `Doc.kv_grid`."""
    import html as _h

    items = "".join(
        f'<div class="pk-field"><i>{_h.escape(str(p[0]))}</i>'
        f'<b>{_h.escape(str(p[1]) if len(p) > 1 else "")}</b></div>'
        for p in (pairs or []))
    return f'<div class="pk-grid c{cols}">{items}</div>'


def bars_html(items, unit: str = "") -> str:
    """أشرطة HTML — نفس مكوّن `Doc.bars`."""
    import html as _h

    items = [i for i in (items or []) if i]
    if not items:
        return ""
    items = sorted(items, key=lambda kv: float(kv[1] or 0), reverse=True)[:8]
    top = max((float(v or 0) for _k, v in items), default=1) or 1
    rows = [f'<div class="row"><span>{_h.escape(str(label))}</span>'
            f'<div class="pk-bar"><i style="width:'
            f'{max(2, min(100, float(value or 0) / top * 100)):.0f}%"></i></div>'
            f'<b style="text-align:end">{float(value or 0):,.0f}'
            f'{_h.escape(unit)}</b></div>' for label, value in items]
    return f'<div class="pk-bars">{"".join(rows)}</div>'


def sign_html(left: str = "توقيع المحاسب", right: str = "توقيع المسؤول") -> str:
    import html as _h

    return (f'<div class="pk-sign"><div>{_h.escape(left)}</div>'
            f'<div>{_h.escape(right)}</div></div>')


