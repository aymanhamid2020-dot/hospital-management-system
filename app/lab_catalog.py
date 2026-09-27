"""كتالوج الفحوصات المخبرية والأشعة — يُزرع أول تشغيل وبطريقة idempotent.

الدليل فارغ أصلًا (لا شيء يزرعه)، فيعرض النظام «الدليل فارغ» مهما بلغ
تطوره. هذا الوحدة تملأه بكتالوج مصنَّف: التصنيف ``specimen_group`` هو ما
يبني منه شاشة الطبيب أقسام الاختيار (الدم · السيرم · الهرمونات · البول ·
البراز · الزرع · المسوحات · الأشعة…)، و``category`` يبقى ``lab`` أو
``radiology`` لتفعيل مسار LIS أو RIS.

كل سطر: ``(code, name, group, price, unit, ref_min, ref_max)`` — ونوع
العينة والأنبوب يُشتقّان من المجموعة فلا يتكرر ١٨٠ مرة في الملف.
"""
from sqlalchemy.orm import Session

from app.models import LabTest, TestType

# — تجميعات الأشعة: تُصنَّف radiology لتمشي في مسار RIS —
RADIOLOGY_GROUPS = ("xray", "ct", "mri", "ultrasound")

_SPECIMEN_BY_GROUP = {
    "blood": "دم كامل", "serum": "دم — سيرم", "hormones": "دم — سيرم",
    "coagulation": "دم — بلازما", "serology": "دم — سيرم",
    "urine": "بول", "stool": "براز", "culture": "حسب الطلب",
    "swab": "مسحة", "other": "حسب الطلب",
    "xray": "", "ct": "", "mri": "", "ultrasound": "",
}

_TUBE_BY_GROUP = {
    "blood": "EDTA (بنفسجي)", "serum": "سيرم (أحمر)", "hormones": "سيرم (أحمر)",
    "coagulation": "سيترات (أزرق)", "serology": "سيرم (أحمر)",
    "urine": "وعاء تحليل", "stool": "وعاء تحليل", "culture": "مِسبار زرع",
    "swab": "مِسبار مسحة", "other": "حسب الطلب",
    "xray": "", "ct": "", "mri": "", "ultrasound": "",
}

# صيام مطلوب لبعض الفحوصات (ساعات)
_FASTING = {"FBS", "HbA1c", "GTT", "LIPID", "INS", "CPT", "LIPASE", "AMY"}

# =========================================================================
# الدم وخلاياه (CBC ومشتقاتها)
# =========================================================================
BLOOD = [
    ("CBC", "صورة الدم الكاملة (CBC)", "blood", 45, "", None, None),
    ("ESR", "سرعة ترسيب الدم (ESR)", "blood", 20, "mm/h", None, None),
    ("BG-RH", "زمرة الدم وعامل الريص (ABO & Rh)", "blood", 15, "", None, None),
    ("RETIC", "عدد كرات الدم المهدّبة (Reticulocyte)", "blood", 35, "%", 0.5, 2.5),
    ("SMEAR", "مسمار دم محيطي (Peripheral Smear)", "blood", 40, "", None, None),
    ("MALAR", "بحث عن ملاريا (Malaria)", "blood", 30, "", None, None),
    ("HBE", "تخطيط الهيموغلوبين (Hb Electrophoresis)", "blood", 120, "", None, None),
    ("G6PD", "خميرة جلوكوز-٦-فوسفات الديهيدروجيناز", "blood", 55, "U/gHb", 7, 20.5),
    ("HAPTO", "الهابتوجلوبين (Haptoglobin)", "blood", 70, "mg/dL", 30, 200),
    ("LDH", "لاكتات الديهيدروجيناز (LDH)", "blood", 45, "U/L", 135, 225),
    ("COOMBS", "اختبار كومبس المباشر", "blood", 40, "", None, None),
    ("BLD-CUL", "زرع دم (Blood Culture)", "culture", 150, "", None, None),
    ("HCT", "الهيماتوكريت (HCT)", "blood", 20, "%", 36, 46),
    ("HGB", "الهيموغلوبين (Hb)", "blood", 20, "g/dL", 12, 17),
    ("PLT", "الصفائح الدموية (Platelets)", "blood", 25, "×10³/µL", 150, 450),
    ("WBC", "كريات الدم البيضاء (WBC)", "blood", 25, "×10³/µL", 4, 11),
]

# =========================================================================
# كيمياء الدم (سكر · وظائف · معادن · إنزيمات)
# =========================================================================
SERUM = [
    ("FBS", "سكر صائم (FBS)", "serum", 15, "mg/dL", 70, 100),
    ("RBS", "سكر عشوائي (RBS)", "serum", 12, "mg/dL", 70, 140),
    ("HbA1c", "الهيموغلوبين السكري (HbA1c)", "serum", 55, "%", 4, 5.6),
    ("GTT", "منحنى تحمل الجلوكوز (OGTT)", "serum", 70, "mg/dL", None, None),
    ("UREA", "اليوريا في الدم (BUN)", "serum", 18, "mg/dL", 7, 20),
    ("CREAT", "الكرياتينين (Creatinine)", "serum", 18, "mg/dL", 0.7, 1.2),
    ("EGFR", "معدل الترشيح الكبيبي المقدَّر (eGFR)", "serum", 45, "mL/min", 90, 120),
    ("URIC", "حمض اليوريك (Uric Acid)", "serum", 20, "mg/dL", 3.5, 7.2),
    ("LIPID", "بروفايل دهون الدم (Lipid Profile)", "serum", 75, "mg/dL", None, None),
    ("CHOL", "الكوليسترول الكلي", "serum", 30, "mg/dL", 0, 200),
    ("HDL", "الكوليسترول عالي الكثافة (HDL)", "serum", 35, "mg/dL", 40, 60),
    ("LDL", "الكوليسترول منخفض الكثافة (LDL)", "serum", 40, "mg/dL", 0, 100),
    ("TG", "الدهون الثلاثية (Triglycerides)", "serum", 35, "mg/dL", 0, 150),
    ("TBIL", "البيليروبين الكلي", "serum", 25, "mg/dL", 0.2, 1.2),
    ("DBIL", "البيليروبين المباشر", "serum", 25, "mg/dL", 0, 0.3),
    ("ALT", "أنزيم الكبد ALT (SGPT)", "serum", 25, "U/L", 7, 45),
    ("AST", "أنزيم الكبد AST (SGOT)", "serum", 25, "U/L", 10, 40),
    ("ALP", "الفوسفاتيز القاعدي (ALP)", "serum", 30, "U/L", 40, 129),
    ("GGT", "جاما جلوتاميل (GGT)", "serum", 30, "U/L", 8, 61),
    ("ALB", "الألبومين (Albumin)", "serum", 25, "g/dL", 3.5, 5.2),
    ("TPROT", "البروتين الكلي (Total Protein)", "serum", 25, "g/dL", 6, 8.3),
    ("GLOB", "الغلوبيولين (Globulin)", "serum", 30, "g/dL", 2, 3.5),
    ("NA", "الصوديوم (Sodium)", "serum", 20, "mmol/L", 135, 145),
    ("K", "البوتاسيوم (Potassium)", "serum", 20, "mmol/L", 3.5, 5.1),
    ("CL", "الكلوريد (Chloride)", "serum", 20, "mmol/L", 98, 107),
    ("HCO3", "البيكربونات (Bicarbonate)", "serum", 30, "mmol/L", 22, 29),
    ("CA", "الكالسيوم الكلي", "serum", 22, "mg/dL", 8.6, 10.2),
    ("IONCA", "الكالسيوم المتأين", "serum", 40, "mg/dL", 4.6, 5.3),
    ("PHOS", "الفوسفور", "serum", 22, "mg/dL", 2.5, 4.5),
    ("MG", "المغنيسيوم", "serum", 30, "mg/dL", 1.7, 2.2),
    ("IRON", "الحديد في الدم (Serum Iron)", "serum", 40, "µg/dL", 60, 170),
    ("TIBC", "سعة ارتباط الحديد الكلية", "serum", 45, "µg/dL", 250, 450),
    ("FERR", "الفيريتين (Ferritin)", "serum", 60, "ng/mL", 30, 300),
    ("AMY", "الأميليز (Amylase)", "serum", 35, "U/L", 28, 100),
    ("LIPASE", "الليباز (Lipase)", "serum", 40, "U/L", 10, 140),
    ("CRP", "بروتين سي التفاعلي (CRP)", "serum", 35, "mg/L", 0, 6),
    ("HSCRP", "بروتين سي التفاعلي شديد الحساسية", "serum", 70, "mg/L", 0, 3),
    ("PCT", "البروكالسيتونين (Procalcitonin)", "serum", 180, "ng/mL", 0, 0.5),
    ("VITD", "فيتامين د (25-OH)", "serum", 90, "ng/mL", 30, 100),
    ("B12", "فيتامين ب١٢", "serum", 80, "pg/mL", 200, 900),
    ("FOL", "حمض الفوليك", "serum", 75, "ng/mL", 3, 17),
    ("HOMOC", "الهوموسستئين", "serum", 95, "µmol/L", 5, 15),
    ("CK", "كرياتين كيناز (CK)", "serum", 40, "U/L", 30, 200),
    ("CKMB", "كرياتين كيناز MB", "serum", 55, "ng/mL", 0, 25),
    ("TROP", "تروبونين I (Troponin I)", "serum", 130, "ng/mL", 0, 0.04),
    ("BNP", "الببتيد البالي (BNP)", "serum", 160, "pg/mL", 0, 100),
    ("DDIM", "دي-دايمر (D-Dimer)", "serum", 110, "µg/mL", 0, 0.5),
    ("LACT", "اللاكتات (Lactate)", "serum", 55, "mmol/L", 0.5, 2),
    ("NH3", "الأمونيا (Ammonia)", "serum", 70, "µmol/L", 15, 45),
    ("KET", "الأسيتون/الكيتونات", "serum", 30, "mmol/L", 0, 0.6),
    ("TIRONE", "سيولة الدم — التحويل", "serum", 20, "µm", 100, 230),
    ("VITB6", "فيتامين ب٦", "serum", 90, "ng/mL", 5, 30),
    ("SELE", "السيلينيوم", "serum", 110, "µg/L", 70, 150),
]

# =========================================================================
# الهرمونات
# =========================================================================
HORMONES = [
    ("TSH", "هرمون تحفيز الغدة الدرقية (TSH)", "hormones", 45, "µIU/mL", 0.4, 4),
    ("FT3", "هرمون درق حر (Free T3)", "hormones", 55, "pg/mL", 2.3, 4.2),
    ("FT4", "هرمون درق حر (Free T4)", "hormones", 55, "ng/dL", 0.8, 1.8),
    ("T3", "هرمون درق كلي (Total T3)", "hormones", 50, "ng/dL", 80, 200),
    ("T4", "هرمون درق كلي (Total T4)", "hormones", 50, "µg/dL", 5, 12),
    ("ANTI-TPO", "أضداد بيروكسيديز الدرق (Anti-TPO)", "hormones", 95, "IU/mL", 0, 35),
    ("LH", "الهرمون المجهّز (LH)", "hormones", 55, "mIU/mL", 1.7, 8.6),
    ("FSH", "الهرمون المنبّه للجريب (FSH)", "hormones", 55, "mIU/mL", 1.5, 12.4),
    ("PRL", "البرولاكتين (Prolactin)", "hormones", 60, "ng/mL", 3, 25),
    ("TESTO", "التستوستيرون الكلي", "hormones", 70, "ng/dL", 300, 1000),
    ("FTST", "التستوستيرون الحر", "hormones", 110, "pg/mL", 5, 21),
    ("E2", "الإستراديول (Estradiol)", "hormones", 75, "pg/mL", 15, 350),
    ("PROG", "البروجستيرون (Progesterone)", "hormones", 70, "ng/mL", 0.2, 25),
    ("AMH", "هرمون المكافحة المضاد للمولود (AMH)", "hormones", 220, "ng/mL", 0.5, 4),
    ("CORT", "الكورتيزول الصائم", "hormones", 65, "µg/dL", 5, 25),
    ("ACTH", "هرمون القشرة الكظرية (ACTH)", "hormones", 130, "pg/mL", 10, 60),
    ("INS", "الأنسولين الصائم", "hormones", 85, "µIU/mL", 2, 25),
    ("CPEP", "الببتيد C (C-Peptide)", "hormones", 90, "ng/mL", 0.8, 3.9),
    ("PTH", "هرمون جارات الدرق (PTH)", "hormones", 100, "pg/mL", 15, 65),
    ("BHCG", "هرمون الحمل الكمي (β-hCG)", "hormones", 60, "mIU/mL", 0, 5),
    ("DHEA", "د一二-سولفات (DHEA-S)", "hormones", 95, "µg/dL", 35, 490),
    ("ALDO", "الألدوستيرون (Aldosterone)", "hormones", 150, "ng/dL", 3, 16),
    ("RENIN", "الرينين البلازمي", "hormones", 160, "ng/mL/h", 0.2, 1.6),
    ("GH", "هرمون النمو (GH)", "hormones", 120, "ng/mL", 0, 5),
    ("IGF1", "عامل نمو شبيه بالأنسولين (IGF-1)", "hormones", 140, "ng/mL", 90, 360),
    ("TESTOST-SP", "الهرمون المحفز للحويصلات (AMH بديل)", "hormones", 0, "", None, None),
]

# =========================================================================
# التخثر
# =========================================================================
COAG = [
    ("PT", "البروثرومبين (PT)", "coagulation", 35, "ثانية", 11, 13.5),
    ("INR", "النسبة المعيارية الدولية (INR)", "coagulation", 40, "", 0.8, 1.2),
    ("APTT", "البروثرومبين الجزئي (aPTT)", "coagulation", 35, "ثانية", 25, 35),
    ("FIB", "الفيبرينوجين (Fibrinogen)", "coagulation", 55, "mg/dL", 200, 400),
    ("BT", "زمن النزف (Bleeding Time)", "coagulation", 25, "دقيقة", 1, 6),
    ("CTIME", "زمن التخثر (Clotting Time)", "coagulation", 25, "دقيقة", 4, 10),
    ("F8", "عامل التخثر الثامن (Factor VIII)", "coagulation", 150, "%", 50, 150),
    ("DD-DUP", "دي-دايمر كمي", "coagulation", 130, "µg/mL", 0, 0.5),
]

# =========================================================================
# البول
# =========================================================================
URINE = [
    ("UR-RT", "تحليل بول شامل (Routine)", "urine", 25, "", None, None),
    ("UR-MIC", "فحص بول مجهر (Microscopy)", "urine", 30, "", None, None),
    ("UR-CUL", "زرع بول (Urine Culture)", "urine", 130, "CFU/mL", None, None),
    ("UR-PREG", "فحص حمل بالبول", "urine", 20, "", None, None),
    ("UR-24P", "بروتين بول ٢٤ ساعة", "urine", 65, "mg/24h", 0, 150),
    ("UR-ALB", "الألبومين/الكرياتينين في البول (ACR)", "urine", 70, "mg/g", 0, 30),
    ("UR-CRE", "كرياتينين البول", "urine", 45, "mg/dL", None, None),
    ("UR-URI", "حمض اليوريك في البول", "urine", 50, "mg/24h", 250, 750),
    ("UR-ELEC", "إلكتروليدات البول", "urine", 85, "mmol/L", None, None),
    ("UR-OSM", "-osmolality البول", "urine", 90, "mOsm/kg", 500, 800),
    ("UR-DRUG", "فحص تعاطي المخدرات", "urine", 150, "", None, None),
    ("UR-KET", "كيتونات البول", "urine", 20, "", None, None),
    ("UR-GLU", "سكر البول", "urine", 18, "", None, None),
    ("UR-BIL", "بيليروبين البول", "urine", 18, "", None, None),
    ("UR-UBG", "يروبيلينوجين البول", "urine", 18, "", None, None),
    ("UR-NIT", "النيترات البولي", "urine", 15, "", None, None),
    ("UR-LEU", "كريات بيضاء بالبول", "urine", 15, "", None, None),
    ("UR-24U", "يوريا البول ٢٤ ساعة", "urine", 70, "g/24h", 6, 17),
]

# =========================================================================
# البراز
# =========================================================================
STOOL = [
    ("ST-RT", "تحليل براز شامل (Routine)", "stool", 30, "", None, None),
    ("ST-OB", "الدم الخفي في البراز (FOBT)", "stool", 40, "", None, None),
    ("ST-CUL", "زرع براز (Stool Culture)", "stool", 130, "", None, None),
    ("ST-OP", "بحث الطفيليات والبويضات", "stool", 55, "", None, None),
    ("ST-CAL", "كالبروتكتين البراز", "stool", 145, "µg/g", 0, 50),
    ("ST-RED", "مواد مختزلة (Reducing Substances)", "stool", 45, "", None, None),
    ("ST-FAT", "دهون البراز (Steatorrhea)", "stool", 65, "g/24h", 0, 7),
    ("ST-HP", "مولد ضد هلوباكتر في البراز", "stool", 95, "", None, None),
    ("ST-CRYP", "الكريبتوسبوريديوم", "stool", 85, "", None, None),
    ("ST-GIARD", "الجيرديا لامبليا", "stool", 85, "", None, None),
]

# =========================================================================
# الزرع والحساسية
# =========================================================================
CULTURE = [
    ("THRT-CUL", "زرع حلق (Throat Culture)", "culture", 120, "", None, None),
    ("WND-CUL", "زرع جرح (Wound Culture)", "culture", 130, "", None, None),
    ("AFB", "لبّات حامضية مقاومة (Sputum AFB)", "culture", 95, "", None, None),
    ("MRSA", "بحث عن ميثيسيلين مقاوم (MRSA)", "culture", 140, "", None, None),
    ("AST-SENS", "مزرعة حساسية المضادات الحيوية", "culture", 110, "", None, None),
    ("STAPH-CUL", "زرع ميثيك حساس", "culture", 135, "", None, None),
    ("CAND", "زرع فطريات", "culture", 140, "", None, None),
]

# =========================================================================
# المسوحات
# =========================================================================
SWAB = [
    ("NP-PCR", "مسحة أنف حلق — بوليميراز (PCR)", "swab", 175, "", None, None),
    ("FLU-PCR", "مسحة حلق — إنفلونزا/كوفيد", "swab", 190, "", None, None),
    ("VAG-SW", "مسحة مهبل (Vaginal Swab)", "swab", 90, "", None, None),
    ("EYE-SW", "مسحة عين", "swab", 85, "", None, None),
    ("URETH-SW", "مسحة مجرى بولي", "swab", 95, "", None, None),
    ("STREP-A", "مسحة حلق — المكورات العقدية أ", "swab", 70, "", None, None),
    ("WOUND-SW", "مسحة جرح سطحية", "swab", 85, "", None, None),
]

# =========================================================================
# المناعة والسيروولوجيا
# =========================================================================
SEROLOGY = [
    ("HIV", "فيروس العوز المناعي (HIV Ag/Ab)", "serology", 90, "", None, None),
    ("HBsAg", "مضد سطحي لالتهاب الكبد ب", "serology", 55, "", None, None),
    ("HBsAB", "ضد سطحي لالتهاب الكبد ب (مناعة)", "serology", 65, "mIU/mL", 10, None),
    ("HCV", "فيروس التهاب الكبد ج", "serology", 85, "", None, None),
    ("VDRL", "VDRL/RPR — الزهري", "serology", 45, "", None, None),
    ("TPHA", "TPHA — تأكيد الزهري", "serology", 60, "", None, None),
    ("DEN-NS1", "뎅ي — ضد NS1", "serology", 95, "", None, None),
    ("DEN-IGM", "뎅ي — IgM", "serology", 95, "", None, None),
    ("WIDAL", "فيدال (التيفوئيد)", "serology", 50, "", None, None),
    ("BRU", "بروسيلا (Brucella)", "serology", 65, "", None, None),
    ("TOXO-G", "توكسوبلازما IgG (Toxoplasma)", "serology", 75, "IU/mL", None, None),
    ("TOXO-M", "توكسوبلازما IgM (Toxoplasma)", "serology", 75, "", None, None),
    ("RUB-G", "الحصبة الألمانية IgG", "serology", 75, "IU/mL", 10, None),
    ("RUB-M", "الحصبة الألمانية IgM", "serology", 75, "", None, None),
    ("CMV-G", "سيتوميغالوفيروس IgG", "serology", 75, "AU/mL", None, None),
    ("CMV-M", "سيتوميغالوفيروس IgM", "serology", 75, "", None, None),
    ("HSV12", "فيروس الهربس البسيط ١/٢", "serology", 90, "", None, None),
    ("ANA", "الأضداد النووية (ANA)", "serology", 120, "", None, None),
    ("RF", "العامل الرثوي (RF)", "serology", 60, "IU/mL", 0, 20),
    ("ASO", "مضادات الستربتوليسين O", "serology", 65, "IU/mL", 0, 200),
    ("ANTI-CCP", "أضداد ببتيد سيستئين", "serology", 165, "U/mL", 0, 20),
]

# =========================================================================
# سوائل الجسم وغيرها
# =========================================================================
OTHER = [
    ("SP-RT", "تحليل بلغم (Sputum Routine)", "other", 35, "", None, None),
    ("SEMEN", "تحليل السائل المنوي", "other", 160, "", None, None),
    ("CSF", "تحليل السائل الشوكي (CSF)", "other", 190, "", None, None),
    ("SYNOV", "تحليل سائل المفاصل", "other", 150, "", None, None),
    ("PLEUR", "تحليل سائل الجنب", "other", 150, "", None, None),
    ("HP-BLOOD", "هلوباكتر بيلوري — دم", "serology", 75, "", None, None),
    ("URIC-24", "حمض اليوريك ٢٤ ساعة", "other", 75, "mg/24h", 250, 750),
    ("PAP", "مسحة بابانيكولاو", "other", 120, "", None, None),
]

# =========================================================================
# الأشعة — أشعة سينية
# =========================================================================
XRAY = [
    ("XR-CHEST-PA", "أشعة صدر — أمامي (PA)", "xray", 90, "", None, None),
    ("XR-CHEST-LAT", "أشعة صدر — جانبي (Lateral)", "xray", 90, "", None, None),
    ("XR-CHEST-2V", "أشعة صدر — ظاهريان (PA + Lat)", "xray", 150, "", None, None),
    ("XR-SKULL", "أشعة جمجمة", "xray", 120, "", None, None),
    ("XR-SINUS", "أشعة جيوب الأنف", "xray", 130, "", None, None),
    ("XR-NECK", "أشعة رقبة — أنسجة رخوة", "xray", 120, "", None, None),
    ("XR-CSPINE", "أشعة عمود عنقي", "xray", 130, "", None, None),
    ("XR-TSPINE", "أشعة عمود صدري", "xray", 130, "", None, None),
    ("XR-LSPINE", "أشعة عمود قطني", "xray", 130, "", None, None),
    ("XR-LSPINE-SO", "أشعة عمود قطني — انحناء", "xray", 150, "", None, None),
    ("XR-ABD", "أشعة بطن — قائمة", "xray", 110, "", None, None),
    ("XR-ABD-SER", "أشعة بطن — ساكنة", "xray", 150, "", None, None),
    ("XR-PELVIS", "أشعة حوض", "xray", 130, "", None, None),
    ("XR-HIP", "أشعة مفصل الورك", "xray", 130, "", None, None),
    ("XR-KNEE", "أشعة ركبة", "xray", 120, "", None, None),
    ("XR-KNEE-SO", "أشعة ركبة — وضع خاص", "xray", 150, "", None, None),
    ("XR-ANKLE", "أشعة كاحل", "xray", 120, "", None, None),
    ("XR-FOOT", "أشعة قدم", "xray", 120, "", None, None),
    ("XR-HEEL", "أشعة كعب", "xray", 120, "", None, None),
    ("XR-SHOULDER", "أشعة كتف", "xray", 120, "", None, None),
    ("XR-HUMERUS", "أشعة عضد", "xray", 120, "", None, None),
    ("XR-ELBOW", "أشعة مرفق", "xray", 120, "", None, None),
    ("XR-WRIST", "أشعة رسغ", "xray", 120, "", None, None),
    ("XR-HAND", "أشعة يد", "xray", 120, "", None, None),
    ("XR-FINGERS", "أشعة أصابع", "xray", 110, "", None, None),
    ("XR-PELVIS-WIDE", "أشعة حوض — سعة فتحة", "xray", 150, "", None, None),
    ("XR-LEG", "أشعة ساق", "xray", 130, "", None, None),
    ("XR-TIBIA", "أشعة قصبة", "xray", 130, "", None, None),
    ("XR-CHEST-PED", "أشعة صدر — أطفال", "xray", 90, "", None, None),
    ("XR-BONE-AGE", "أشعة نضج عظمي (Age)", "xray", 180, "", None, None),
    ("XR-PTB", "أشعة صدر — مراقبة السل", "xray", 90, "", None, None),
    ("XR-MASTOID", "أشعة خشائية", "xray", 160, "", None, None),
    ("XR-MANDIBLE", "أشعة فك", "xray", 130, "", None, None),
    ("XR-TEMP", "أشعة صدغين", "xray", 175, "", None, None),
    ("XR-CLAVICLE", "أشعة ترقوة", "xray", 120, "", None, None),
    ("XR-RIBS", "أشعة ضلع", "xray", 130, "", None, None),
    ("XR-SCAPULA", "أشعة لوح الكتف", "xray", 130, "", None, None),
]

# =========================================================================
# الأشعة المقطعية (CT)
# =========================================================================
CT = [
    ("CT-HEAD-NC", "أشعة مقطعية رأس — بدون تباين", "ct", 450, "", None, None),
    ("CT-HEAD-C", "أشعة مقطعية رأس — بتباين", "ct", 650, "", None, None),
    ("CT-STROKE", "بروتوكول جلطة (CT Angio Head)", "ct", 750, "", None, None),
    ("CT-SINUS", "أشعة مقطعية جيوب أنف", "ct", 480, "", None, None),
    ("CT-MASTOID", "أشعة مقطعية خشائية", "ct", 520, "", None, None),
    ("CT-ORBIT", "أشعة مقطعية مدار عين", "ct", 550, "", None, None),
    ("CT-CSPINE", "أشعة مقطعية عمود عنقي", "ct", 600, "", None, None),
    ("CT-LSPINE", "أشعة مقطعية عمود قطني", "ct", 600, "", None, None),
    ("CT-CHEST", "أشعة مقطعية صدر", "ct", 550, "", None, None),
    ("CT-CHEST-HR", "أشعة مقطعية صدر — عالية الدقة", "ct", 650, "", None, None),
    ("CT-ABD", "أشعة مقطعية بطن", "ct", 550, "", None, None),
    ("CT-ABD-PELVIS", "أشعة مقطعية بطن وحوض", "ct", 650, "", None, None),
    ("CT-PELVIS", "أشعة مقطعية حوض", "ct", 520, "", None, None),
    ("CT-UROGRAM", "أشعة مقطعية مسالك بولية (CT Urogram)", "ct", 700, "", None, None),
    ("CT-KUB", "أشعة مقطعية كلية ومسالك", "ct", 550, "", None, None),
    ("CT-AORTA", "أشعة مقطعية شريان أورطي", "ct", 800, "", None, None),
    ("CT-CORONARY", "تصوير شرايا قلب (CT Calcium Score)", "ct", 950, "", None, None),
    ("CT-CTA-CHEST", "أشعة مقطعية شريان رئوي", "ct", 850, "", None, None),
    ("CT-NECK-SOFT", "أشعة مقطعية أنسجة رقبة", "ct", 550, "", None, None),
    ("CT-JAW", "أشعة مقطعية فك", "ct", 500, "", None, None),
    ("CT-DENTAL", "أشعة مقطعية أسنان (Panorama)", "ct", 450, "", None, None),
    ("CT-KNEE", "أشعة مقطعية ركبة", "ct", 600, "", None, None),
    ("CT-ANKLE", "أشعة مقطعية كاحل", "ct", 600, "", None, None),
    ("CT-SHOULDER", "أشعة مقطعية كتف", "ct", 600, "", None, None),
    ("CT-WHOLE-BODY", "أشعة مقطعية جسم كامل", "ct", 1100, "", None, None),
    ("CT-TRAUMA", "بروتوكول إصابات (Trauma CT)", "ct", 1200, "", None, None),
]

# =========================================================================
# الرنين المغناطيسي (MRI)
# =========================================================================
MRI = [
    ("MR-BRAIN", "رنين مغناطيسي دماغ — بدون تباين", "mri", 1100, "", None, None),
    ("MR-BRAIN-C", "رنين مغناطيسي دماغ — بتباين", "mri", 1500, "", None, None),
    ("MR-EPI", "رنين صرع (EEG-MRI)", "mri", 1450, "", None, None),
    ("MR-IAC", "رنين قنوات أذن داخلية", "mri", 1250, "", None, None),
    ("MR-SPINE-C", "رنين عمود عنقي", "mri", 1150, "", None, None),
    ("MR-SPINE-T", "رنين عمود صدري", "mri", 1150, "", None, None),
    ("MR-SPINE-L", "رنين عمود قطني", "mri", 1150, "", None, None),
    ("MR-SACRUM", "رنين عجزي عنقي", "mri", 1150, "", None, None),
    ("MR-KNEE", "رنين ركبة", "mri", 1100, "", None, None),
    ("MR-SHOULDER", "رنين كتف", "mri", 1100, "", None, None),
    ("MR-HIP", "رنين ورك", "mri", 1100, "", None, None),
    ("MR-BRAIN-DWI", "رنين دماغ — انتشار (DWI)", "mri", 1300, "", None, None),
    ("MRCP", "رنين قنوات صفراوية (MRCP)", "mri", 1400, "", None, None),
    ("MR-PELVIS-F", "رنين حوض أنثوي", "mri", 1200, "", None, None),
    ("MR-PELVIS-M", "رنين حوض ذكوري", "mri", 1200, "", None, None),
    ("MR-PROSTATE", "رنين بروستات", "mri", 1500, "", None, None),
    ("MR-FOOT", "رنين قدم/كاحل", "mri", 1100, "", None, None),
    ("MR-ELBOW", "رنين مرفق", "mri", 1100, "", None, None),
    ("MR-WRIST", "رنين رسغ", "mri", 1100, "", None, None),
    ("MR-NECK", "رنين أنسجة رقبة", "mri", 1200, "", None, None),
    ("MR-CARDIAC", "رنين قلب", "mri", 1800, "", None, None),
    ("MR-WHOLE-BODY", "رنين جسم كامل", "mri", 2200, "", None, None),
]

# =========================================================================
# السوبراؤند والدوبلر
# =========================================================================
ULTRASOUND = [
    ("US-ABD", "سوبراؤند بطن كامل", "ultrasound", 180, "", None, None),
    ("US-ABD-UP", "سوبراؤند بطن علوي", "ultrasound", 160, "", None, None),
    ("US-PELVIS-TA", "سوبراؤند حوض عبر البطن", "ultrasound", 150, "", None, None),
    ("US-PELVIS-TV", "سوبراؤند حوض عن طريق المهبل", "ultrasound", 220, "", None, None),
    ("US-OB1", "سوبراؤند حمل — توقيت", "ultrasound", 200, "", None, None),
    ("US-OB2", "سوبراؤند حمل — نمو (Third Trimester)", "ultrasound", 230, "", None, None),
    ("US-OB-DOP", "دوبلر حمل — سُمك الوعاء", "ultrasound", 280, "", None, None),
    ("US-TVT", "سوبراؤند مثانة وبقيّة بول", "ultrasound", 170, "", None, None),
    ("US-THYROID", "سوبراؤند غدة درقية", "ultrasound", 180, "", None, None),
    ("US-THY-DOP", "دوبلر غدة درقية", "ultrasound", 260, "", None, None),
    ("US-BREAST", "سوبراؤند ثدي", "ultrasound", 190, "", None, None),
    ("US-SCROTUM", "سوبراؤند قضيب/خصية", "ultrasound", 190, "", None, None),
    ("US-SCRO-DOP", "دوبلر خصية", "ultrasound", 270, "", None, None),
    ("US-RENAL", "سوبراؤند كلية ومسالك", "ultrasound", 175, "", None, None),
    ("US-RENAL-DOP", "دوبلر شريان كلوي", "ultrasound", 300, "", None, None),
    ("US-LIVER", "سوبراؤند كبد + صفرا", "ultrasound", 175, "", None, None),
    ("US-LIVER-E", "إيكو كبد (Elastography)", "ultrasound", 380, "", None, None),
    ("US-GALL", "سوبراؤند مثانة صفراوية", "ultrasound", 175, "", None, None),
    ("US-SPLEEN", "سوبراؤند طحال", "ultrasound", 175, "", None, None),
    ("US-PANCREAS", "سوبراؤند بنكرياس", "ultrasound", 175, "", None, None),
    ("US-URINARY", "سوبراؤند مثانة ومسالك", "ultrasound", 175, "", None, None),
    ("US-PROSTATE", "سوبراؤند بروستات", "ultrasound", 190, "", None, None),
    ("US-CAROTID", "دوبلر شرايا رقبية", "ultrasound", 320, "", None, None),
    ("US-ABD-DOP", "دوبلر بطن (Aorta & IVC)", "ultrasound", 330, "", None, None),
    ("US-LOWER-DOP", "دوبلر أطراف سفلية", "ultrasound", 340, "", None, None),
    ("US-UPPER-DOP", "دوبلر أطراف علوية", "ultrasound", 340, "", None, None),
    ("US-MSK", "سوبراؤند عضلات ومفاصل", "ultrasound", 250, "", None, None),
    ("US-PILO", "سوبراؤند كيس شعر", "ultrasound", 180, "", None, None),
    ("US-EYE", "سوبراؤند عين", "ultrasound", 230, "", None, None),
    ("US-NEONATE", "سوبراؤند رضع — صورة دماغية", "ultrasound", 260, "", None, None),
    ("US-HIPS", "سوبراؤند ورك رضع", "ultrasound", 240, "", None, None),
]

GROUPS = (BLOOD, SERUM, HORMONES, COAG, URINE, STOOL, CULTURE, SWAB,
          SEROLOGY, OTHER, XRAY, CT, MRI, ULTRASOUND)


def _rows():
    """كل الصفوف جاهزة للبذر: التصنيف والعينة والأنبوب مشتقّة من المجموعة."""
    for group_rows in GROUPS:
        for code, name, group, price, unit, lo, hi in group_rows:
            yield {
                "code": code,
                "name": name,
                "category": (TestType.RADIOLOGY if group in RADIOLOGY_GROUPS
                             else TestType.LAB),
                "specimen_group": group,
                "specimen_type": _SPECIMEN_BY_GROUP.get(group, ""),
                "tube_type": _TUBE_BY_GROUP.get(group, ""),
                "price": price,
                "unit": unit or None,
                "ref_min": lo,
                "ref_max": hi,
                "fasting_hours": 8 if code in _FASTING else 0,
                "active": True,
            }


def seed_lab_catalog(db: Session) -> int:
    """يزرع الكتالوج المصنَّف ما لم يكن موجودًا — idempotent.

    لا يمسّ ما أضافه المدير بنفسه: كل صف يُضاف فقط إن خلا رمزه من
    الدليل، ويُفعَّل ما كان معطّلًا ولم يُسنَد له طلبات بعد. يرجع عدد ما
    أُضيف.
    """
    existing = {t.code for t in db.query(LabTest.code).all()}
    added = 0
    for row in _rows():
        if row["code"] in existing:
            continue
        db.add(LabTest(**row))
        added += 1
    if added:
        db.commit()
    return added


def catalog_size() -> int:
    """عدد الصفوف التي سيبذرها الدليل — للاختبارات والتوثيق."""
    return sum(1 for _ in _rows())
