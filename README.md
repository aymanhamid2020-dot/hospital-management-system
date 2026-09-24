# نظام إدارة المستشفيات والعيادات 🏥

نظام متكامل مبني باستخدام **FastAPI** لإدارة المستشفيات والعيادات الطبية.

## المميزات

- 🖥️ **واجهة ويب كاملة (SPA)** على `/ui` — لوحة تحكم عربية مع تسجيل دخول وجداول ونماذج
- 📎 **المرفقات الطبية** — رفع صور الأشعة والتحاليل (حد 10MB) مع معاينة وتنزيل وحذف
- 📄 **توليد PDF عربي** — فواتير، سجلات طبية، **تقرير إحصائي** `/dashboard/report/pdf` (المدير: المستشفى كلها، الطبيب: مرضاه وأقسامه) + **تقارير متخصصة**: `/reports/lab/pdf` (المختبر) و`/reports/pharmacy/pdf` (الصيدلية) و`/reports/payroll/pdf` (الرواتب) — والكل يدعم **`lang=en`** بإصدار إنجليزي كامل
- 🖨️ طباعة الفواتير كصفحة HTML جاهزة للطباعة
- 🔐 **نظام مصادقة JWT** — تسجيل دخول، صلاحيات (مدير/طبيب/موظف)، حماية لكل الواجهات
- 🩺 **السجلات الطبية** — تشخيصات ووصفات، الطبيب يرى سجلات مرضاه فقط
- 👨‍⚕️ إدارة المرضى (بحث بالاسم/الهاتف/**الهوية الوطنية**) + **الهوية والتأمين على مستوى المريض**
- 🩺 إدارة الأطباء وتخصصاتهم وربطهم بالأقسام
- 📅 حجز المواعيد مع فلترة (تاريخ/حالة/طبيب) والتحقق من تعارض التوفر + **أزرار تأكيد/إتمام/إلغاء** من الواجهة + **🎫 طابور الوصول (Check-in)** برقم تسلسلي لليوم وبطاقة "في الخدمة الآن"
- 🔬 **المختبر والأشعة** — طلبات تحاليل/أشعة، حالات (مسجّل → قيد التنفيذ → جاهزة → مراجَعة)، إدخال النتيجة + **إشعار جاهزيتها**
- 💊 **الصيدلية** — مخزون أدوية بحد تنبيه، صرف للمريض (خصم آلي + **تنبيه مخزون منخفض**)، وسجل صرف
- 🛒 **المبيعات** (قائمة مستقلة) — سجل مبيعات الصرف مع **إجمالي/محصّل/متبقي** و**تسجيل دفعة** (نقدًا/بطاقة/تأمين، حالة `UNPAID → PARTIAL → PAID`) عبر **نافذة منبثقة** تعرض الإجمالي/المدفوع/المتبقي و**معاينة حيّة** للمتبقي بعد الدفع + زر **«سدّد الكل»** يسوّي كل العمليات غير المسددة دفعة واحدة + فلاتر (شهر/طريقة/حالة/مريض/اسم الصرف) + **منحنى الإيراد يومي/شهري** + زر **🧾 إيصال** يفتح إيصال الدفعة للطباعة
- 🧾 **الحسابات** (قائمة مستقلة) — الأرصدة والتقارير: **إجمالي/محصّل/متبقي** + ملخص مجمّع لكل طريقة دفع + **كشف حساب مريض** (مبيعات الصيدلية + الفواتير + الرصيد) بطباعة ar/en + جدول **«🧾 المدينون»** مرتب تنازليًا مع صف إجمالي وزر «كشف حساب» لكل مدين + **تصدير CSV/PDF** *(التصدير admin فقط)*
- 💵 **الرواتب** — قيود شهرية (أساسي + بدلات − استقطاعات = صافي) وصرف *(admin فقط)*
- 🧾 **سجل التدقيق** — يسجّل كل POST/PUT/PATCH/DELETE (المستخدم، المسار، الحالة) *(admin فقط)*
- 🔑 **تغيير كلمة المرور الذاتي** من الشريط العلوي للوحة التحكم
- 🏥 **إدارة الأقسام** (باطنية، جراحة، طوارئ...)
- 🛏️ **إدارة الأسرّة** مع حالات (متاح/مشغول/صيانة) وربطها بالمريض
- 👥 إدارة الموظفين
- 💳 نظام الفواتير — ربط بالمواعيد/السجلات + تسوية الدفع (نقدي/بطاقة/تأمين) + **بيانات وثائق التأمين** + **خصم ونسبة ضريبة وإجمالي محسوب + دفع جزئي** (حالة جزئية حتى اكتمال المبلغ)
- 📎 **المرفقات داخل السجلات الطبية** — عدّاد 📎 وقائمة منسدلة بمعاينة/تنزيل لكل سجل
- 🗃️ **بيانات تجريبية** — `python seed_demo.py` (أقسام/أطباء/مرضى/مواعيد/فواتير/مرفقات)
- 📄 **الملف الشامل للمريض PDF** — بيانات + سجلات + مواعيد + فواتير + مرفقات
- ⬆️⬇️ **تصدير/استيراد CSV** — المرضى (`/patients/export.csv` + `/patients/import`) والفواتير (`/invoices/export.csv`) — عربي بترميز Excel
- 🔄 **ترحيل خفيف للقاعدة** — إضافة الأعمدة الجديدة تلقائيًا عند الإقلاع (بدون حذف البيانات)
- 💾 **نسخ احتياطي** لقاعدة البيانات مع تنزيل النسخ (admin فقط)
- 📊 **لوحة تحكم وإحصائيات** مع مخطط أعمدة للحالات
- 🩺 **حالة النظام العامة** `/status` — JSON عام دون توكن للمراقبة: الإصدار، محرك القاعدة واتصالها، عدد السجلات
- 📊 **لوحة مراقبة مرئية** `/monitor` — صفحة خلوية (دون توكن) بأيقونات خضراء/حمراء للقاعدة والتذكيرات والنسخ التلقائي والمخزون المنخفض ونهاية الصلاحية وطلبات المختبر المعلّقة — تتحدث كل 15 ثانية
- ⚡ **إشعارات فورية اختيارية** — Telegram Bot و/أو `NOTIFY_WEBHOOK_URL` للتذكيرات و`low_stock` و`lab_result` (يفشل صامتًا ولا يعطل الطلب أبدًا)
- 💾 **نسخ احتياطي مجدول تلقائي** — نسخة متسقة يوميًا إلى `backups/auto_*.db` مع الاحتفاظ بآخر 7 نسخ (`BACKUP_INTERVAL_HOURS` / `BACKUP_RETENTION` — SQLite فقط)
- ⬇️ **تصدير CSV متخصص** — المختبر والصيدلية (مخزون أو سجل الصرف) والرواتب **وحركات الحسابات والمبيعات**، بترميز UTF-8 + BOM يفتح عربيًا في Excel
- 📈 **تحليل استخدام النظام** `/audit-logs/stats` — أكثر المستخدمين نشاطًا، أكثر المسارات طلبًا (مطبّعة `/:id`)، توزيع الطرق، الأخطاء الأخيرة، ومحاولات الدخول الفاشلة
- 📊 **منحنى الإيراد والمدينون** `/accounts/revenue` و `/accounts/debtors` — رسم بياني يومي/شهري للمبيعات مقابل المحصّل، وجدول مدينين مرتّب تنازليًا مع إجمالي المتبقي
- 🧾 **إيصال دفعة + كشف حساب مريض** — `/accounts/sales/{id}/receipt` (إيصال HTML جاهز للطباعة) و `/accounts/statement/{id}` + `/print` (مبيعات + فواتير + رصيد المريض) — كلاهما **عربي/إنجليزي** `?lang=ar|en` (لغة خاطئة ⇒ 400)
- 📦 **قسم المخزون** `/inventory` — شاشة مستقلة ببطاقات ملخّص (قيمة/أصناف/قطع/منخفض/نافد/قارب الانتهاء/منتهٍ) + جدول أصناف بفلاتر بحث وحالة ونافذة صلاحية + **دفتر حركات موحّد** (`stock_movements`: رصيد افتتاحي، صرف، توريد، جرد — بكمية موقّعة ورصيد بعد الحركة ومن قيدها) — القراءة لأي مستخدم مسجّل، **التوريد/الجرد للمدير فقط** (كمية ≤ 0 ⇒ 422 · صنف غير موجود ⇒ 404 · فلتر خاطئ ⇒ 400)
- 📅 **تنبيهات نهاية الصلاحية** — `/status` يضيف `expired_meds` و`expiring_meds` (30 يومًا) وبطاقة «نهاية الصلاحية» في `/monitor`
- 🧪 **اختبارات آلية pytest** (116 اختبارًا) — `python -m pytest`
- 🔐 **حماية الدخول** — قفل مؤقت بعد 5 محاولات فاشلة (429، نافذة 15 دقيقة — `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES`) + **حد لكل IP** (`AUTH_IP_FAIL_MAX` / `AUTH_IP_WINDOW_MINUTES`) + **قوّة كلمة المرور** (8 أحرف فأكثر + حرف + رقم) عند التسجيل والتغيير
- 🌐 **واجهة إنجليزية** — زر `🌐` يبدّل عربي ⇄ English (RTL ⇄ LTR) ويحفظ الاختيار في المتصفح — قوائم وعناوين وجداول ورسائل مترجمة
- 📱 **PWA** — `manifest.json` + أيقونة + عامل خدمة `sw.js` (قشرة التطبيق والطابور في الكاش — يعمل دون اتصال بعد أول زيارة) — **الشبكة أولًا** لملفات `/ui/` فلا يعرض المتصفح واجهة قديمة، + ترويسة `Cache-Control: no-cache` من الخادم
- 🖥️ **نسخة سطح مكتب** — `build_desktop.bat` تُنتج `dist\HospitalMS.exe` (خادم محلي + يفتح المتصفح + SQLite بجانب الملف)
- 🔥 **اختبار حمل وأداء** — `python tests/load_test.py` (متزامن × طلبات، زمن متوسط/p50/p95، حكم آلي PASS/FAIL)
- 🔔 **الإشعارات** — جرس غير المقروءة + صفحة إشعارات (تذكير/مواعيد)
- ✉️ **بريد التأكيد والتذكير** — SMTP عبر `.env` أو وضع outbox تجريبي
- 🐳 **Docker** — Dockerfile + docker-compose (SQLite أو PostgreSQL)
- 🔗 علاقات حقيقية (Foreign Keys) مع حذف تتابعي (Cascade)
- 🇬🇧 **تقارير PDF إنجليزية** — `lang=en` على تقارير لوحة التحكم والمختبر والصيدلية والرواتب **والحسابات** (عناوين وتذييل و`SAR` بالإنجليزية) — الواجهة ترسل لغتها تلقائيًا مع كل تنزيل
- ♻️ **استعادة نسخة احتياطية من الواجهة** — زر ♻️ بجانب كل نسخة SQLite: يتحقق سلامة الملف (`sqlite_master` + `quick_check`) ثم يصنع نسخة أمان إلزامية قبل الاستبدال عبر `sqlite3 backup`
- 📅 **تقويم المواعيد الشهري** — شبكة أسبوعية داخل شاشة المواعيد بألوان حسب الحالة + تنقّل بين الشهور + عدّاد `+N` (يبدأ الأحد، شهور و weekdays عربي/إنجليزي حسب اللغة)
- 👤 **إدارة المستخدمين من الواجهة** — شاشة `المستخدمون` (admin): إنشاء حساب بصلاحية، تغيير الصلاحية من القائمة، تفعيل/تعطيل — بحارس «آخر مدير نشط» ومنع تغيير الذات
- 🔐 **حماية دخول على مستوى IP** — `AUTH_IP_FAIL_MAX` (افتراضي 30/15 دقيقة، `0` يُعطل) تمنع تدوير أسماء المستخدمين من نفس العنوان (429 مع رسالة مميّزة)، + قسم «🔒 محاولات الدخول الفاشلة» في تحليل التدقيق (إجمالي/آخر 24 ساعة/آخر 5)

## المتطلبات

- Python 3.10+
- pip

## التثبيت

```bash
# تثبيت الاعتماديات
pip install -r requirements.txt

# نسخ ملف البيئة (اختياري)
copy .env.example .env
```

## حساب المدير الافتراضي

يُنشأ تلقائياً عند أول تشغيل:

| الحقل | القيمة |
|-------|--------|
| username | `admin` |
| password | `admin123` |

> ⚠️ غيّر كلمة المرور هذه في بيئة الإنتاج.

## حسابات تجريبية (بعد `python seed_demo.py`)

| الدور | username | password |
|-------|----------|----------|
| طبيب | `demo_doc1` … `demo_doc6` | `demo12345` |
| مدير | `admin` | `admin123` |
| طبيب (البيانات الأساسية) | `drsara` | `sara12345` |
| استقبال (البيانات الأساسية) | `reception1` | `rec12345` |

## التشغيل

```bash
python -m uvicorn main:app --reload
```

## النشر بـ Docker

### بناء الصورة وتشغيلها

```bash
docker build -t hms-hospital .
docker run -d --name hospital -p 8000:8000 hms-hospital
# ثم افتح: http://127.0.0.1:8000/ui
```

فحص الصحة:

```bash
curl http://127.0.0.1:8000/health
# {"status":"healthy","service":"hospital-management-system",...}
```

> أول تشغيل يُنشئ قاعدة `hospital.db` داخل الحاوية **ويبذر حساب المدير تلقائيًا** (`admin` / `admin123`).

### docker compose (موصى به للإنتاج)

```bash
docker compose up -d app      # التطبيق فقط — SQLite على volume مسمّى
docker compose ps             # الحالة
docker compose logs -f app    # متابعة السجلات
docker compose down           # ⏹ إيقاف مع بقاء البيانات (volumes مسماة)
docker compose down -v        # ⛔ حذف البيانات نهائيًا
```

- البيانات تنجو من `down`: `hospital_data` (قاعدة البيانات) و`hospital_uploads` و`hospital_backups` و`hospital_outbox`.
- خدمة `db` (PostgreSQL 16) **اختيارية**؛ تشغيل كامل مُتحقق منه (فحوص حيّة على PostgreSQL):
  `docker compose -f docker-compose.yml -f docker-compose.pg.yml up -d --build`
  — يضبط `DATABASE_URL=postgresql://hospital:hospital_pass@db:5432/hospital` وينتظر جاهزية القاعدة (`pg_isready`) قبل إقلاع التطبيق عبر `docker-compose.pg.yml`، ويرحّل الجداول والأعمدة الجديدة تلقائيًا عند أول تشغيل؛ التنظيف: `docker compose -f docker-compose.yml -f docker-compose.pg.yml down -v`.
  > النسخ الاحتياطي من الواجهة خاص بـSQLite — على PostgreSQL استخدم `pg_dump` (المسار محمي برسالة خطأ واضحة عند عدم الدعم).
- متغيرات أخرى عبر `.env` (**القالب جاهز: انسخ `.env.example` إلى `.env`**) — `SECRET_KEY` (إلزامي، أُنشئ لك قيمة عشوائية محلية)، `MAIL_ENABLED`، `SMTP_*`، `REMINDER_INTERVAL_MINUTES`... — قراءة التطبيق عبر python-dotenv وقراءة compose لاستبدال `${...}` من الملف نفسه.
- خطوط الـPDF: arial على ويندوز وDejaVu داخل الحاوية (كشف تلقائي)؛ للتجاوز حدّد `HMS_FONT_REGULAR` و`HMS_FONT_BOLD`.

### متطلبات Windows

- Docker Desktop يحتاج **WSL2**؛ إن تعطّل المحرّك:
  `wsl --install --no-distribution` (مرفوعًا) ثم **إعادة تشغيل الجهاز** لتفعيل VirtualMachinePlatform.

### نقل الصورة إلى خادم آخر (بدون إنترنت)

```powershell
docker save -o dist\hms-hospital.tar hms-hospital:test hms-hospital:latest   # عندك
docker load -i hms-hospital.tar                                              # على الخادم
```

### النشر خطوة بخطوة (خادم إنتاج — بدون إنترنت)

1. **النقل**: صدّر الصورة كما بالأعلى وانسخ `dist\hms-hospital.tar` إلى الخادم (فلاشة/SCP).
2. **التحميل**: `docker load -i hms-hospital.tar`.
3. **الإعداد**: انسخ القالب وعوّض القيم:
   `cp .env.example .env` ثم ضع `SECRET_KEY` عشوائيًا قويًا (إلزامي):
   `python -c "import secrets; print(secrets.token_urlsafe(48))"` — **ولنشر إنتاجي كامل**
   (SMTP فعلي + CORS مقيّد على نطاقك + جلسات120 دقيقة) استخدم قالب `.env.production.example` بدل `.env.example`.
4. **التشغيل**: `docker compose up -d app` — أول تشغيل يُنشئ القاعدة على volume مسمّى **ويبذر `admin` تلقائيًا**.
5. **التحقق الموحد**: `BASE_URL=http://SERVER:8000 WAIT=90 python tests/stack_check.py`
   (فحص قراءة فقط يصلح للإنتاج: الصحة + `/status` + الواجهة + كل المحاور + تقارير PDF + تصدير CSV + التدقيق).
6. **اختياري — اختبار حمل**: `USERS=10 REQUESTS=20 python tests/load_test.py` (يقيس p50/p95 ويعطي حكم PASS/FAIL).
6. **تأمين الدخول**: غيّر كلمة `admin` فورًا من زر 🔑 في الواجهة.
7. **بيانات تجريبية (اختياري)**: `docker compose exec app python seed_demo.py`.
8. **النسخ الاحتياطي**: زر النسخ الاحتياطي في الواجهة (SQLite — يحفظ داخل volume `hospital_backups`) أو `pg_dump` على PostgreSQL — جدول زمني مقترح: يوميًا.
9. **السجلات والإيقاف**: `docker compose logs -f app` — `docker compose restart app` — `docker compose down` (البيانات تنجو) — `down -v` (حذف نهائي).
10. **الترقية لاحقًا**: حمّل الصورة الجديدة ثم `docker compose up -d app` — ترحيل الجداول والأعمدة الجديدة تلقائي وآمن على البيانات القائمة.

### نسخ احتياطي للبيانات

```bash
docker cp hospital:/app/data/hospital.db ./hospital-backup.db     # قاعدة البيانات
docker cp hospital:/app/uploads ./uploads-backup                  # المرفقات
# أو من داخل الواجهة: زر النسخ الاحتياطي (backups/)
```

### اختبار حي داخل حاوية

```bash
docker run -d --name hms-test -p 18080:8000 hms-hospital:test
python tests/live_container_test.py     # 107 فحصًا حيًا (SQLite)
docker rm -f hms-test

# الاختبار نفسه على أي قاعدة أخرى (مثال: compose+PostgreSQL على :8000):
LIVE_BASE=http://127.0.0.1:8000 python tests/live_container_test.py

# الفحص الموحد لأي نشرة (محلي/حاوية — SQLite/PostgreSQL — قاعدة نظيفة أو مزروعة):
BASE_URL=http://127.0.0.1:8001 WAIT=60 python tests/stack_check.py
# ( STACK_USER / STACK_PASS لاعتماد مخصّص — أسماء مقصودة تتفادى حجز USERNAME في Windows )
# ملاحظة: فحص «قفل الدخول» يُشغَّل مرة واحدة لكل خادم — إعادة التشغيل على نفس القاعدة
# تعطي 429 من أول محاولة (58/61)، فشغّله على خادم/حاوية نظيفة للرقم الكامل.

# 🔥 اختبار حمل خفيف (قراءة فقط): يحكم PASS إذا صفر أخطاء + p95 ≤ 800ms
USERS=10 REQUESTS=20 python tests/load_test.py
```

## التوثيق التفاعلي

افتح **http://127.0.0.1:8000/api/docs** ثم اضغط **Authorize** وأدخل التوكن بالشكل:

```
Bearer <access_token>
```

### الحصول على التوكن

```bash
curl -X POST http://127.0.0.1:8000/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\": \"admin\", \"password\": \"admin123\"}"
```

ثم استخدم القيمة `access_token` من الرد في Authorize أعلاه.

## الروابط

| الرابط | الوصف |
|--------|-------|
| **http://127.0.0.1:8000/ui** | 🖥️ **لوحة التحكم** (واجهة ويب كاملة) |
| http://127.0.0.1:8000/ | الصفحة الرئيسية |
| http://127.0.0.1:8000/status | حالة النظام (JSON عام دون توكن) |
| **http://127.0.0.1:8000/monitor** | 📊 **لوحة المراقبة المرئية** (أيقونات خضراء/حمراء) |
| http://127.0.0.1:8000/api/docs | Swagger UI (التوثيق) |
| http://127.0.0.1:8000/api/redoc | ReDoc (التوثيق) |
| http://127.0.0.1:8000/health | فحص حالة النظام |

## بنية المشروع

```
hosptal/
├── main.py                  # نقطة دخول + admin + static /ui
├── requirements.txt         # الاعتماديات
├── pytest.ini               # إعدادات الاختبارات
├── .env.example             # نموذج إعدادات البيئة
├── desktop.py               # 🖥️ نسخة سطح المكتب (خادم محلي + فتح المتصفح)
├── build_desktop.bat        # 🖥️ بناء HospitalMS.exe عبر PyInstaller
├── static/
│   ├── index.html           # 🖥️ الواجهة الأمامية SPA كاملة (عربي/إنجليزي)
│   ├── monitor.html         # 📊 لوحة المراقبة المرئية
│   ├── manifest.json        # 📱 تعريف PWA (قابل للتثبيت)
│   ├── sw.js                # 📱 عامل الخدمة (القشرة + الطابور دون اتصال)
│   └── icon.svg             # 📱 أيقونة النظام
├── tests/
│   ├── conftest.py          # 🧪 قاعدة بيانات اختبار منفصلة
│   ├── test_api.py          # 🧪 19 اختبارًا آليًا
│   ├── test_notifications.py # 🔔 إشعارات + بريد + تذكير (8)
│   ├── test_billing.py      # 💳 فواتير/دفع/ملف PDF (6)
│   ├── test_insurance.py    # 🏢 تأمين + مرفقات السجلات (4)
│   ├── test_export_reports.py # ⬆️⬇️ CSV + إتمام موعد + تقرير الطبيب (12)
│   ├── test_ops.py          # 🔐 قفل الدخول + قوة كلمة المرور + اللغة + PWA + 💰 الحسابات + 📊 الإيراد/المدينون (116 إجماليًا)
│   ├── test_inventory.py    # 📦 قسم المخزون: القيم/الحالات/الفلاتر/التوريد/الجرد/الحركات (9)
│   ├── stack_check.py       # ✅ الفحص الموحد (82 فحصًا — قراءة فقط)
│   ├── live_container_test.py # ✅ الفحص الحي (107 فحصًا داخل الحاوية)
│   ├── ui_accounts_check.py # 🛒🧾 فحص قسمي المبيعات والحسابات في الواجهة (59 فحصًا)
│   ├── accounts_flow_check.py # 💰 تدفق صرف → تسديد (21 فحصًا — لا يُسحب بـ pytest)
│   ├── revenue_debtors_check.py # 📊 منحنى الإيراد + المدينون (22 فحصًا)
│   ├── inventory_flow_check.py # 📦 تدفق المخزون حيًا (54 فحصًا — يحتاج خادمًا على 8001)
│   └── load_test.py         # 🔥 اختبار الحمل (متزامن + p50/p95)
├── seed_demo.py            # 🗃️ بيانات تجريبية غنية (اختياري)
├── fix_demo_emails.py      # 🔧 إصلاح نطاق البريد التجريبي (مرة واحدة)
├── live_*_test.py          # 🧪 اختبارات حية ضد الخادم العامل
├── Dockerfile               # 🐳 صورة التشغيل
├── docker-compose.yml       # 🐳 التطبيق + PostgreSQL
├── backups/                 # 💾 النسخ الاحتياطية (تُنشأ تلقائيًا)
├── uploads/                 # 📎 الملفات المرفوعة
└── app/
    ├── config.py            # الإعدادات (بريد + تذكير)
    ├── database.py          # إعداد قاعدة البيانات
    ├── auth.py              # 🔐 PBKDF2 + JWT + الصلاحيات
    ├── email_utils.py       # ✉️ SMTP + outbox + قوالب الرسائل
    ├── tasks.py             # ⏰ مهمة التذكير الخلفية
    ├── pdf_utils.py         # 📄 توليد PDF عربي (invoices/records/reports)
    ├── invoice_template.py  # 🖨️ قالب طباعة الفاتورة HTML
    ├── receipt_template.py  # 🖨️ قالب إيصال الدفعة + كشف حساب المريض HTML
    ├── models.py            # نماذج SQLAlchemy (علاقات FK + جدول stock_movements لدفتر المخزون)
    ├── schemas.py           # مخططات Pydantic للتحقق (تشمل DispenseInDB و RevenuePoint و Debtor و InventoryItem)
    └── routers/
        ├── auth.py          # 🔐 تسجيل، دخول، إدارة المستخدمين
        ├── patients.py      # إدارة المرضى
        ├── doctors.py       # إدارة الأطباء
        ├── appointments.py  # إدارة المواعيد
        ├── departments.py   # 🏥 إدارة الأقسام
        ├── beds.py          # 🛏️ إدارة الأسرّة
        ├── staff.py         # إدارة الموظفين
        ├── invoices.py      # إدارة الفواتير
        ├── reports.py       # إدارة التقارير
        ├── accounts.py      # 💰 المبيعات والحسابات (سجل/ملخص/إيراد/مدينون/تسديد/إيصال/كشف حساب)
        ├── inventory.py     # 📦 المخزون (قائمة بالقيمة/الحالة + ملخّص + دفتر الحركات + توريد/جرد)
        ├── medical_records.py # 🩺 السجلات الطبية (التشخيص والوصفات)
        ├── attachments.py    # 📎 المرفقات الطبية (رفع/معاينة/تنزيل)
        ├── notifications.py  # 🔔 الإشعارات
        ├── backup.py        # 💾 النسخ الاحتياطي
        └── dashboard.py     # 📊 الإحصائيات + التقرير PDF
```

## الواجهات البرمجية (API)

> جميع الواجهات تتطلب توكن JWT ما عدا `/auth/register` و `/auth/login` و `/` و `/health`.

### المصادقة `/auth`
- `POST /auth/register` — تسجيل مستخدم جديد
- `POST /auth/login` — تسجيل الدخول (يُرجع توكن JWT)
- `GET /auth/me` — المستخدم الحالي
- `GET /auth/users` — قائمة المستخدمين *(admin فقط)*
- `PUT /auth/users/{id}/toggle` — تفعيل/تعطيل *(admin فقط)*
- `PUT /auth/users/{id}/role` — تغيير الصلاحية `{role: admin|doctor|موظف استقبال}` *(admin فقط — يمنع تغيير الذات وسحب صلاحية آخر مدير نشط؛ دور مجهول ⇒ 422)*
- `POST /auth/change-password` — 🔑 تغيير كلمة مرور الحساب الحالي `{current_password, new_password}`

### المرضى `/patients`
- `GET /?search=&blood_type=` — القائمة مع بحث (بالاسم/الهاتف/**الهوية الوطنية**) وفلترة
- `GET /export.csv` — ⬆️ تصدير CSV (UTF-8 + BOM، عربي، يفتح مباشرة في Excel — يشمل الهوية والتأمين)
- `POST /import` — ⬇️ استيراد CSV (رؤوس عربية/إنجليزية، يتجاهل المكرّر حسب البريد **أو الهوية**، يردّ أخطاء بالأسطر، ترميز cp1256 أيضًا)
- `GET /{id}` — مريض محدد
- `POST /` — إضافة مريض (**الهوية الوطنية مميزة** + `insurer`/`policy_number` اختياريان)
- `PUT /{id}` — تحديث مريض
- `DELETE /{id}` — حذف مريض *(admin فقط)*

### السجلات الطبية `/medical-records`
- `GET /?patient_id=&search=` — السجلات (الطبيب يرى مرضاه فقط)
- `POST /` — إنشاء سجل (الطبيب يُنسب له تلقائيًا)
- `GET /{id}/pdf` — 📄 تحميل PDF عربي
- `DELETE /{id}` — *(admin فقط)*

### الفواتير `/invoices`
- `GET /{id}/print` — 🖨️ طباعة HTML
- `GET /{id}/pdf` — 📄 تحميل PDF
- `POST /` — إنشاء فاتورة

### الفواتير `/invoices`
- `GET /?patient_id=&status=&appointment_id=` — قائمة مع فلاتر
- `GET /export.csv?status=` — ⬆️ تصدير CSV (يشمل الدفع والتأمين والروابط + الخصم/الضريبة/الإجمالي/المدفوع)
- `POST /` — إنشاء (مع ربط اختياري بموعد/سجل + **بيانات تأمين** `insurer`/`policy_number` + **`discount` و `tax_rate`**)
- `POST /{id}/pay` — 💰 تسوية الفاتورة `{method: cash|card|insurance, amount?}`
  (بلا `amount` = المتبقي كله، وبها = **دفع جزئي** — الحالة: partial حتى بلوغ الإجمالي — رفض الدفع المكرر/المتجاوز — **التأمين يتطلب شركة التأمين**)
- `GET /{id}/print` — 🖨️ HTML | `GET /{id}/pdf` — 📄 (يتضمن الخصم/الضريبة/الإجمالي/المدفوع والروابط والتأمين)
- `PUT /{id}` — تحديث (يعيد مزامنة المدفوع مع الإجمالي) | `DELETE /{id}` — حذف *(admin)*
- المجاميع في كل الاستجابات: `subtotal` / `tax` / `total` / `paid_amount`

### البيانات التجريبية
```bash
python seed_demo.py      # 5 أقسام، 6 أطباء (demo_doc1..6/demo12345)، 10 مرضى،
                         # 30 سرير، مواعيد (منها واحدة خلال 6 ساعات 🔔)، سجلات، فواتير، مرفقات
```

### الملف الشامل للمريض
- `GET /patients/{id}/pdf` — 📄 ملف PDF شامل: البيانات الشخصية + السجلات الطبية
  + المواعيد + الفواتير + المرفقات *(الطبيب: ملفات مرضاه فقط)*

### الإشعارات `/notifications`
- `GET /?unread_only=` — قائمة الإشعارات
- `GET /unread-count` — عدد غير المقروءة (للجرس 🔔)
- `PUT /{id}/read` — تعليم كمقروء | `PUT /read-all` — تعليم الكل
- `DELETE /{id}` — حذف إشعار

### البريد والتذكير
- إنشاء/تأكيد الموعد → إشعار داخلي + **بريد تأكيد للمريض** (في الخلفية)
- مهمة خلفية كل `REMINDER_INTERVAL_MINUTES` دقائق — تذكير بالمواعيد القادمة
  (إشعار + بريد، مرّة واحدة لكل موعد)
- `MAIL_ENABLED=false` (الافتراضي) → يُحفظ البريد في `outbox/*.eml` بدل الإرسال
- **إشعارات فورية اختيارية** (مع التذكيرات و`low_stock` و`lab_result`): اضبط
  `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` و/أو `NOTIFY_WEBHOOK_URL` —
  أي إخفاق يُسجَّل في السجلات ولا يعطل الطلب أبدًا
- **حماية الدخول**: `LOGIN_MAX_ATTEMPTS` (افتراضي 5) و`LOGIN_LOCKOUT_MINUTES`
  (افتراضي 15 — القيمة `0` تُعطل القفل) — العدّاد في ذاكرة كل عملية خادم،
  وقوّة كلمة المرور مفروضة دائمًا: 8 أحرف فأكثر + حرف + رقم
- **حد الدخول لكل IP**: `AUTH_IP_FAIL_MAX` (افتراضي 30) و`AUTH_IP_WINDOW_MINUTES`
  (افتراضي 15 — `0` يُعطل) — يُفحص قبل الاعتماديات فيمنع تدوير أسماء
  المستخدمين من نفس العنوان حتى بأسماء مختلفة (429)

### النسخ الاحتياطي `/backup` *(admin فقط)*
- `POST /backup` — إنشاء نسخة
- `GET /backup` — قائمة النسخ (مع حقل `restorable`)
- `GET /backup/{file}` — تنزيل نسخة
- `POST /backup/{file}/restore` — ♻️ **استعادة** نسخة SQLite: يُتحقق أولًا (اسم آمن + `sqlite_master` جدول `users` + `PRAGMA quick_check`)، ثم تُصنع **نسخة أمان إلزامية** في المجلد نفسه، ثم الاستبدال بـ`sqlite3 backup` بعد إغلاق اتصالات ORM — على PostgreSQL: 400 موجّه (استخدم `pg_restore`)
- **نسخ تلقائي مجدول** (SQLite فقط): لقطة متزامنة كل `BACKUP_INTERVAL_HOURS`
  ساعة إلى `backups/auto_*.db` مع الاحتفاظ بآخر `BACKUP_RETENTION` (7) نسخ —
  شغّلها أول تشغيل ثم كل دورة، وتعطّل بـ`BACKUP_INTERVAL_HOURS=0`

### المرفقات `/attachments`
- `POST /attachments/` — رفع ملف (multipart، حد 10MB، امتدادات مسموحة فقط)
- `GET /?patient_id=` — قائمة المرفقات
- `GET /{id}/file` — تنزيل | `GET /{id}/preview` — معاينة داخل المتصفح
- `DELETE /{id}` — حذف *(admin أو طبيب السجل)*

### التقارير
- `GET /dashboard/report/pdf?month=YYYY-MM` — 📄 تقرير إحصائي PDF
  *(admin: المستشفى كلها — doctor: مرضاه ومواعيده وأقسامه فقط — استقبال:403)*
- `GET /reports/lab/pdf?status=` — 🔬 تقرير المختبر والأشعة PDF *(admin + doctor — الطبيب: طلباته فقط)*
- `GET /reports/pharmacy/pdf` — 💊 تقرير مخزون الصيدلية وتنبيهاته وآخر الصرف PDF *(admin)*
- `GET /reports/payroll/pdf?period=YYYY-MM` — 💵 كشف الرواتب PDF *(admin — الفترة اختيارية، صيغة خاطئة ⇒ 400)*
- `GET /reports/accounts/sales/pdf?period=YYYY-MM` — 💰 تقرير مبيعات الحسابات PDF *(admin — فترة اختيارية)*
- **`?lang=ar|en`** على التقارير PDF الخمسة (لوحة التحكم والمختبر والصيدلية والرواتب **والحسابات**) — 🇬🇧 إصدار إنجليزي كامل (عناوين وتذييل و`SAR`، أسماء ملفات `*_en.pdf`) — لغة مجهولة ⇒ 400، والواجهة ترسل لغتها تلقائيًا · ملفات CSV تبقى عربية
- `GET /reports/lab/csv?status=` — ⬇️ CSV طلبات المختبر *(admin + doctor — الطبيب: طلباته فقط)*
- `GET /reports/pharmacy/csv?section=inventory|dispenses` — ⬇️ CSV المخزون أو سجل الصرف *(admin — قسم خاطئ ⇒ 400)*
- `GET /reports/payroll/csv?period=YYYY-MM` — ⬇️ CSV كشف الرواتب *(admin — صيغة خاطئة ⇒ 400)*
- `GET /reports/accounts/sales/csv?period=YYYY-MM` — ⬇️ CSV حركات المبيعات *(admin — صيغة خاطئة ⇒ 400)*

### الاختبارات
```bash
python -m pytest                        # 116 اختبارًا آليًا
python tests/stack_check.py             # 82 فحصًا — BASE_URL / WAIT
python tests/live_container_test.py     # الفحص الحي داخل الحاوية (107 فحصًا — LIVE_BASE)
python tests/ui_accounts_check.py       # فحص قسمي المبيعات والحسابات (59 فحصًا — يحتاج خادمًا على 8001)
python tests/accounts_flow_check.py     # تدفق صرف → تسديد جزئي → كامل (21 فحصًا — يحتاج خادمًا على 8001)
python tests/revenue_debtors_check.py   # 📊 منحنى الإيراد + المدينون (22 فحصًا — يحتاج خادمًا على 8001)
python tests/inventory_flow_check.py    # 📦 تدفق المخزون (54 فحصًا — يحتاج خادمًا على 8001)

# 🔥 اختبار حمل وأداء: متزامن × طلبات، متوسط/p50/p95، حكم آلي PASS/FAIL
USERS=10 REQUESTS=20 python tests/load_test.py
BASE_URL=http://SERVER:8000 USERS=20 REQUESTS=30 python tests/load_test.py
```

### التشغيل بـ Docker
```bash
docker compose up -d --build        # التطبيق على :8000 + PostgreSQL
docker compose up app -d --build    # التطبيق فقط (SQLite مضمّن)
```

### نسخة سطح المكتب (Windows)
```bat
build_desktop.bat        :: بناء dist\HospitalMS.exe (PyInstaller — أوّل مرة ~دقيقتين)
dist\HospitalMS.exe      :: خادم محلي على :8765 + يفتح المتصفح تلقائيًا
```
- القاعدة `hospital.db` والنسخ `backups/` تُنشأ **بجانب الملف التنفيذي**
- منفذ مخصّص: اضبط `HMS_DESKTOP_PORT` قبل التشغيل
- تحقّق دون بناء: `python desktop.py` (نفس منطق النسخة المجمّعة)

### الواجهة الإنجليزية وPWA
- زر `🌐 EN` / `🌐 عربي` في شاشة الدخول والترويسة — يبدّل اللغة والاتجاه
  (RTL ⇄ LTR) ويحفظ الاختيار في `localStorage` (القوائم والجداول والرسائل مترجمة)
- PWA: `/ui/manifest.json` + `/ui/icon.svg` + عامل خدمة `/ui/sw.js` —
  بعد أول زيارة تُخزَّن قشرة التطبيق وشاشة الطابور للعرض دون اتصال

### الأطباء `/doctors`
- `GET /` — قائمة الأطباء
- `POST /` — إضافة طبيب
- `PUT /{id}` — تحديث طبيب
- `DELETE /{id}` — حذف طبيب *(admin فقط)*

### المواعيد `/appointments`
- `GET /?date=YYYY-MM-DD&status=&doctor_id=` — القائمة مع فلاتر
- `POST /` — حجز موعد (مع التحقق من توفر الطبيب)
- `PUT /{id}` — تحديث الحالة (pending → confirmed → completed / cancelled) — أزرار الواجهة: تأكيد/إتمام/إلغاء
- `POST /{id}/checkin` — 🎫 تسجيل وصول المريض + رقم طابور تسلسلي لليوم (يمنع التكرار/الملغى/المكتمل)
- `GET /queue?date=YYYY-MM-DD` — 🎫 طابور الوصول لذلك اليوم مرتبًا برقم الطابور (افتراضيًا اليوم)
- 📅 **تقويم شهري في الواجهة** — زر «🗓️ تقويم» في شاشة المواعيد: شبكة 7 أعمدة (تبدأ الأحد) بألوان حسب الحالة وحدود اليوم و`+N`، تنقّل بين الشهور، شهور/أيام عربية أو إنجليزية حسب لغة الواجهة
- `DELETE /{id}` — *(admin فقط)*

### المختبر والأشعة `/lab-orders`
- `GET /?patient_id=&doctor_id=&status=&test_type=` — الطلبات (الطبيب: طلبات مرضاه فقط)
- `POST /` — طلب تحليل/أشعة `{patient_id, doctor_id?, test_type: lab|radiology, test_name, price?}`
- `PUT /{id}` — تغيير الحالة أو إدخال `result` (**النتيجة مطلوبة قبل "جاهزة"** — عند الجاهزية يُنشأ إشعار `lab_result` وتُختم `result_at`)
- `DELETE /{id}` — *(admin فقط)*

### الصيدلية `/medications` + `/dispenses`
- `GET /medications/?search=&low_stock=true` — المخزون (بحث بالاسم/الرمز + فلتر المخزون المنخفض)
- `POST /medications/` — إضافة دواء (رمز مميز) *(admin)* — الرصيد الافتتاحي يُقيَّد حركة `in` | `PUT /{id}` — تحديث/توريد كمية *(admin)* — تغيير الكمية يُقيَّد حركة | `DELETE /{id}` — *(admin)*
- `POST /dispenses/` — 💊 صرف `{medication_id, patient_id, quantity}` — يخصم من المخزون ويرفض الكمية الزائدة وينبّه عند بلوغ حد التنبيه **ويقيَّد حركة `out`**
- `GET /dispenses/?patient_id=&medication_id=` — سجل الصرف (مُصرِّف باسم المستخدم)

### المخزون `/inventory` *(القراءة لأي مستخدم مسجّل — التوريد/الجرد للمدير فقط)*
- `GET /inventory/?search=&status=ok|low|out|expiring|expired&expiring_days=` — الأصناف بقيمة محسوبة (`quantity × price`) وحالة موحّدة و`days_to_expiry` (حالة خاطئة أو `expiring_days` خارج 0–365 ⇒ 400)
- `GET /summary?expiring_days=` — ملخّص: `items, units, total_value, low, out, expired, expiring, expiring_days`
- `GET /movements?medication_id=&type=in|out|adjust&limit=` — دفتر الحركات (أحدث أولًا · نوع خاطئ ⇒ 400 · `limit` خارج 1–500 ⇒ 422)
- `POST /{id}/restock` — 📦 توريد `{quantity, note?}` يزيد الكمية ويسجّل حركة `in` *(كمية ≤ 0 ⇒ 422 · غير موجود ⇒ 404)*
- `PUT /{id}/adjust` — 🧮 جرد مطلق `{quantity, note?}` يضبط الكمية ويسجّل فرقها حركة `adjust` *(سالب ⇒ 422 · غير موجود ⇒ 404)*

### الحسابات والمبيعات `/accounts` *(القراءة والتسديد لأي مستخدم مسجّل)*
- `GET /sales?patient_id=&staff=&payment_method=&status=UNPAID|PARTIAL|PAID&from_date=&to_date=` — سجل المبيعات
- `GET /summary?period=YYYY-MM | from_date=&to_date=` — ملخّص: إجمالي/محصّل/متبقي/عدد + تجميع لكل طريقة دفع (صيغة فترة خاطئة ⇒ 400)
- `GET /sales/{id}` — تفصيل عملية بيع (غير موجود ⇒ 404)
- `GET /revenue?period=YYYY-MM | from_date=&to_date=&group=day|month` — 📊 منحنى الإيراد: نقاط `{date, sales, collected, count}` مجمّعة يوميًا (الافتراضي) أو شهريًا، مرتبة تصاعديًا (صيغة فترة خاطئة ⇒ 400 · `group` خاطئ ⇒ 400)
- `GET /debtors?period=YYYY-MM | from_date=&to_date=&min_outstanding=` — 🧾 المرضى الذين باقي عليهم مبلغ: `{patient_id, full_name, operations, total, paid, outstanding}` مرتبون تنازليًا حسب المتبقي (يُستبعد المسدّد بالكامل · `min_outstanding` سالب ⇒ 422)
- `PUT /sales/{id}/payment` — 💰 تسجيل دفعة `{paid_amount, payment_method}` — **يستبدل** المدفوع لا يجمعه (لذلك الواجهة ترسل المجموع التراكمي)، ويحدّث الحالة `PAID` إذا بلغ الإجمالي وإلا `PARTIAL` (سالب/صفر ⇒ 422 · يتجاوز الإجمالي ⇒ 400 · غير موجود ⇒ 404 · **عملية مسدّدة بالكامل ⇒ 409** صلاحية أدق تمنع إعادة التسديد)
- `GET /sales/{id}/receipt?lang=ar|en` — 🖨️ إيصال الدفعة كصفحة HTML جاهزة للطباعة (عربي/إنجليزي · لغة خاطئة ⇒ 400 · غير موجود ⇒ 404)
- `GET /statement/{patient_id}` — 🧾 كشف حساب مريض JSON: بيانات المريض + حركات الصيدلية + الفواتير + `totals` (`sales_total/sales_paid/inv_total/inv_paid/dues/outstanding`) *(غير موجود ⇒ 404)*
- `GET /statement/{patient_id}/print?lang=ar|en` — 🖨️ كشف الحساب نفسه كصفحة HTML للطباعة (لغة خاطئة ⇒ 404/400)
- كل عملية بيع تحمل `total_price` (الكمية × سعر الوحدة يُحسب آليًا عند الصرف) و`status` و`paid_amount` و`paid_at`
- تقارير: `GET /reports/accounts/sales/csv` و `GET /reports/accounts/sales/pdf` *(admin فقط — `?period=YYYY-MM` و `?lang=ar|en`)*

### الرواتب `/payroll` *(admin فقط بالكامل)*
- `GET /?staff_id=&period=YYYY-MM=&status=` — كشف الرواتب
- `POST /` — قيد جديد (الصافي = أساسي + بدلات − استقطاعات؛ الأساسي 0 ⇒ راتب الموظف؛ فترة مكررة ⇒ 400)
- `PUT /{id}` — تحديث يعيد حساب الصافي | `POST /{id}/pay` — 💵 الصرف | `DELETE /{id}`

### سجل التدقيق `/audit-logs` *(admin فقط)*
- `GET /?username=&method=&limit=` — سجل عمليات POST/PUT/PATCH/DELETE (المسار، المستخدم، حالة الاستجابة) عبر وسيط في الخادم
- `GET /stats?days=7` — 📈 تحليل الاستخدام: توزيع الطرق، أكثر المستخدمين نشاطًا، أكثر المسارات طلبًا (مطبّعة)، والأخطاء الأخيرة

### الأقسام `/departments` *(الإنشاء والحذف للمدير فقط)*
- `GET /` — قائمة الأقسام مع أسرّتها
- `POST /` — إضافة قسم *(admin)*
- `PUT /{id}` — تحديث قسم *(admin)*
- `DELETE /{id}` — حذف قسم *(admin)*

### الأسرّة `/beds`
- `GET /` — قائمة الأسرّة
- `POST /` — إضافة سرير *(admin)*
- `PUT /{id}` — تغيير الحالة / إسناد مريض
- `DELETE /{id}` — حذف سرير *(admin)*

### لوحة التحكم `/dashboard`
- `GET /dashboard/stats` — إحصائيات شاملة (مرضى، أطباء، مواعيد اليوم، الإيرادات، الإشغال)

### الموظفون `/staff`، الفواتير `/invoices`، التقارير `/reports`
- عمليات CRUD مماثلة

## قاعدة البيانات

يستخدم **SQLite** افتراضياً (ملف `hospital.db` يُنشأ تلقائياً عند التشغيل).
للاستخدام مع PostgreSQL عدّل `DATABASE_URL` في ملف `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/hospital
```
