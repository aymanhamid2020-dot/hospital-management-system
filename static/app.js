const API = '';
// الجلسة الافتراضية في الذاكرة فقط: فتح الموقع يعرض شاشة الدخول دائمًا.
// "تذكرني" وحده ينقل الجلسة إلى localStorage لتُستأنف بعد إعادة التشغيل.
let TOKEN = '';
let USER = null;
try {
  if (localStorage.getItem('hms_remember') === '1') {
    TOKEN = localStorage.getItem('hms_token') || '';
    USER = JSON.parse(localStorage.getItem('hms_user') || 'null');
  } else {
    TOKEN = sessionStorage.getItem('hms_token') || '';
    USER = JSON.parse(sessionStorage.getItem('hms_user') || 'null');
  }
} catch (e) { TOKEN = ''; USER = null; }
let CURRENT_VIEW = 'dashboard';

/* ========== أدوات ========== */
function toast(msg, isErr = false) {
  const t = document.getElementById('toast');
  t.textContent = tr(msg);
  t.className = 'toast show' + (isErr ? ' err' : '');
  setTimeout(() => t.className = 'toast', 3200);
}

async function api(path, opts = {}) {
  opts.headers = Object.assign({ 'Content-Type': 'application/json; charset=utf-8' },
    TOKEN ? { 'Authorization': 'Bearer ' + TOKEN } : {}, opts.headers || {});
  const res = await fetch(API + path, opts);
  if (res.status === 401) { logout(); throw new Error('انتهت الجلسة — سجّل دخولًا من جديد'); }
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.detail) || 'خطأ غير متوقع');
  return data;
}

async function apiBlob(path) {
  const res = await fetch(API + path, { headers: { 'Authorization': 'Bearer ' + TOKEN } });
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'فشل التحميل'); }
  return await res.blob();
}

/* جلب HTML محميًا (إيصال/كشف حساب) وفتحه في نافذة طباعة */
async function openPrint(path) {
  /* نفتح النافذة أولًا (قبل أي انتظار) حتى لا يحجبها المتصفح */
  const w = window.open('', '_blank');
  if (!w) throw new Error('الرجاء السماح بالنوافذ المنبثقة للطباعة');
  try {
    const res = await fetch(API + path, { headers: { 'Authorization': 'Bearer ' + TOKEN } });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || 'فشل التحميل');
    }
    w.document.write(await res.text());
    w.document.close();
    w.focus();
  } catch (e) { w.close(); throw e; }
}

/* إيصال دفعة لعملية بيع */
function openReceipt(id) {
  openPrint('/accounts/sales/' + id + '/receipt?lang=' + LANG)
    .then(() => toast('تم فتح الإيصال للطباعة ✅'))
    .catch(e => toast(e.message, true));
}

/* كشف حساب مريض: ملخص JSON داخل الصفحة + طباعة HTML */
async function showStatement() {
  const pid = Number((document.getElementById('f-stmt-patient') || {}).value || 0);
  if (!pid) return toast('أدخل رقم المريض أولًا', true);
  try {
    const st = await api('/accounts/statement/' + pid);
    const t = st.totals;
    const box = document.getElementById('stmt-out');
    const row = (l, v, cls) =>
      `<div class="kv"><span>${l}</span><b class="${cls || ''}">${v}</b></div>`;
    box.innerHTML = `
      <div class="kv"><span>المريض</span><b>${esc(st.patient.full_name)} (#${st.patient.id})</b></div>
      <div class="kv"><span>الجوال</span><b>${esc(st.patient.phone || '-')}</b></div>
      ${row('مبيعات الصيدلية', t.sales_total.toLocaleString() + ' ر.س')}
      ${row('مدفوع من المبيعات', t.sales_paid.toLocaleString() + ' ر.س', 'ok')}
      ${row('إجمالي الفواتير', t.inv_total.toLocaleString() + ' ر.س')}
      ${row('مدفوع من الفواتير', t.inv_paid.toLocaleString() + ' ر.س', 'ok')}
      ${row('إجمالي المستحقات', t.dues.toLocaleString() + ' ر.س')}
      ${row('الرصيد المستحق', t.outstanding.toLocaleString() + ' ر.س',
            t.outstanding > 0 ? 'bad' : 'ok')}
      <div class="kv"><span>عدد حركات الصيدلية</span><b>${st.sales.length}</b></div>
      <div class="kv"><span>عدد الفواتير</span><b>${st.invoices.length}</b></div>
      <div class="row2" style="margin-top:12px">
        <button class="btn" onclick="openPrint('/accounts/statement/${pid}/print?lang=' + LANG)
          .then(() => toast('تم فتح الكشف للطباعة ✅')).catch(e => toast(e.message, true))">🖨️ طباعة الكشف</button>
        <button class="btn success" onclick="download('/accounts/statement/${pid}/pdf','patient_statement_${pid}.pdf')">⬇️ PDF الكشف</button>
        <button class="btn ghost" onclick="openPrint('/accounts/statement/${pid}/print?lang=en')
          .then(() => toast('Opened English statement ✅')).catch(e => toast(e.message, true))">🇬🇧 EN</button>
      </div>`;
    applyI18n(box);
  } catch (e) { toast(e.message, true); }
}

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmtDate(s) { return s ? String(s).replace('T', ' ').slice(0, 16) : '-'; }
function pill(v) { return `<span class="pill ${esc(v)}">${esc(v)}</span>`; }
function isAdmin() { return USER && USER.role === 'admin'; }
function isDoctor() { return USER && USER.role === 'doctor'; }

/* ========== اللغة: عربي / English (i18n) ========== */
let LANG = localStorage.getItem('hms_lang') || 'ar';

/* ===== الوضع الداكن 🌙 ===== */
let THEME = localStorage.getItem('hms_theme') || 'light';
/* التعرّف على تفضيل النظام عند أول زيارة فقط — اختيار المستخدم الصريح يبقى متفوقًا */
if (!localStorage.getItem('hms_theme')
    && window.matchMedia('(prefers-color-scheme: dark)').matches) {
  THEME = 'dark';
}

function applyTheme() {
  document.documentElement.dataset.theme = THEME;
  ['theme-btn', 'theme-btn-login'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.textContent = THEME === 'dark' ? '☀️' : '🌙';
  });
}

function toggleTheme() {
  THEME = THEME === 'dark' ? 'light' : 'dark';
  localStorage.setItem('hms_theme', THEME);
  applyTheme();
  toast(THEME === 'dark' ? '🌙 الوضع الداكن مفعّل' : '☀️ الوضع الفاتح مفعّل');
}
applyTheme();
const AR2EN = {
  /* الشاشة العامة */
  'نظام إدارة المستشفيات — لوحة التحكم': 'Hospital Management — Dashboard',
  '🏥 نظام إدارة المستشفيات': '🏥 Hospital Management',
  'سجّل دخولك للوصول إلى لوحة التحكم': 'Sign in to access the dashboard',
  'اسم المستخدم': 'Username',
  'كلمة المرور': 'Password',
  'تسجيل الدخول': 'Sign in',
  'طبيب:': 'Doctor:',
  'موظف:': 'Staff:',
  /* القائمة والترويسة */
  '🏥 المستشفى': '🏥 Hospital',
  'لوحة التحكم': 'Dashboard',
  'المرضى': 'Patients',
  'الأطباء': 'Doctors',
  'المواعيد': 'Appointments',
  'المختبر والأشعة': 'Lab & Radiology',
  'المختبر': 'Lab',
  'الصيدلية': 'Pharmacy',
  'السجلات الطبية': 'Medical Records',
  'المرفقات': 'Attachments',
  'الأقسام': 'Departments',
  'الأسرّة': 'Beds',
  'الفواتير': 'Invoices',
  'الموظفون': 'Staff',
  'قائمة الموظفين': 'Employee List',
  'شؤون الموظفين': 'Employee Affairs',
  'البيانات الشخصية والتعريفية': 'Personal & Identification Info',
  'البيانات الوظيفية والإدارية': 'Employment & Job Info',
  'البيانات المالية والتعويضات': 'Salary & Allowances Info',
  /* شاشة ملف المريض */
  'الملف الشخصي': 'Profile',
  'السجل الطبي': 'Medical Record',
  'المواعيد والزيارات': 'Appointments & Visits',
  'الفحوصات والوصفات': 'Diagnostics & Orders',
  'الحسابات والتأمين': 'Billing & Insurance',
  'المرفقات': 'Documents',
  'الاستقطاعات والتأمينات والضرائب': 'Deductions & Taxes',
  'الإجازات والدوام': 'Leave & Attendance',
  'العهد العينية والعهد': 'Assets & Loans',
  'مستحقات نهاية الخدمة والقيود': 'End of Service & Accounting Defaults',
  'الرواتب': 'Payroll',
  'النسخ الاحتياطي': 'Backup',
  'الإشعارات': 'Notifications',
  'سجل التدقيق': 'Audit Log',
  /* الحسابات والمبيعات */
  'الحسابات والمبيعات': 'Accounts & Sales',
  'المبيعات': 'Sales',
  'الحسابات': 'Accounts',
  /* كشف حساب مريض */
  'عرض الكشف': 'Show statement',
  'طباعة الكشف': 'Print statement',
  '⬇️ PDF الكشف': '⬇️ Statement PDF',
  'أدخل رقم المريض أولًا': 'Enter the patient ID first',
  'أدخل رقم المريض لعرض كشف حسابه (مبيعات + فواتير + الرصيد)': 'Enter the patient ID to view their statement (sales + invoices + balance)',
  'مبيعات الصيدلية': 'Pharmacy sales',
  'مدفوع من المبيعات': 'Sales paid',
  'إجمالي الفواتير': 'Invoices total',
  'مدفوع من الفواتير': 'Invoices paid',
  'إجمالي المستحقات': 'Total dues',
  'الرصيد المستحق': 'Outstanding balance',
  'عدد حركات الصيدلية': 'Pharmacy transactions',
  'عدد الفواتير': 'Invoices count',
  'تم فتح الكشف للطباعة ✅': 'Statement opened for printing ✅',
  'تم فتح الإيصال للطباعة ✅': 'Receipt opened for printing ✅',
  'الرجاء السماح بالنوافذ المنبثقة للطباعة': 'Please allow popups for printing',
  'الحسابات': 'Accounts',
  'عدد المدينين': 'Debtors count',
  'كشف حساب مريض': 'Patient statement',
  'الإيراد الشهري': 'Monthly revenue',
  'إجمالي المدينين': 'Total debtors',
  'تقييم طرق الدفع': 'Payment methods breakdown',
  'توزيع طرق الدفع': 'Payment methods breakdown',
  '📄 تقرير المبيعات PDF': '📄 Sales report PDF',
  '⬇️ تقرير المبيعات CSV': '⬇️ Sales report CSV',
  '🧾 إيصال': '🧾 Receipt',
  'لا يوجد إيراد': 'No revenue',
  '🛒 المبيعات': '🛒 Sales',
  '🧾 الحسابات': '🧾 Accounts',
  'إجمالي المبيعات': 'Total sales',
  'المحصّل': 'Collected',
  'المتبقي (مدين)': 'Outstanding',
  'عدد العمليات': 'Operations count',
  'سجل المبيعات': 'Sales log',
  'كل طرق الدفع': 'All payment methods',
  'كل الحالات': 'All statuses',
  'كل الفترات': 'All periods',
  'غير مدفوع': 'Unpaid',
  'مدفوع جزئيًا': 'Partially paid',
  'مدفوع': 'Paid',
  'نقدًا': 'Cash',
  'بطاقة': 'Card',
  'تأمين': 'Insurance',
  'رقم المريض': 'Patient ID',
  'صرفه…': 'Dispensed by…',
  'تطبيق': 'Apply',
  'مسح': 'Clear',
  'الدواء': 'Medicine',
  'المدفوع': 'Paid',
  'المتبقي': 'Outstanding',
  'الطريقة': 'Method',
  'لا توجد مبيعات في هذه الفترة': 'No sales in this period',
  'تسديد': 'Record payment',
  'المبلغ المدفوع (ر.س):': 'Paid amount (SAR):',
  'طريقة الدفع (cash/card/insurance):': 'Payment method (cash/card/insurance):',
  'تم تسجيل الدفعة ✅': 'Payment recorded ✅',
  'لا يمكن أن يتجاوز المبلغ إجمالي العملية': 'Amount cannot exceed the operation total',
  'قيمة غير رقمية': 'Not a number',
  'عملية بيع #': 'Sale #',
  /* نافذة التسديد */
  '💰 تسديد دفعة': '💰 Record payment',
  'عملية البيع': 'Sale operation',
  'المبلغ (ر.س)': 'Amount (SAR)',
  'طريقة الدفع': 'Payment method',
  'المتبقي بعد الدفع': 'Remaining after payment',
  'تأكيد التسديد': 'Confirm payment',
  'لا يمكن أن يتجاوز المبلغ المتبقي': 'Amount cannot exceed the remaining balance',
  'تعذر فتح عملية البيع': 'Cannot open this sale',
  'لا توجد عمليات غير مسددة': 'No unpaid operations',
  'سيتم تسديد المتبقي كاملاً للعمليات غير المسددة. متابعة؟': 'The full remaining amount of all unpaid operations will be settled. Continue?',
  'تم تسديد كل العمليات ✅': 'All operations settled ✅',
  'سدّد الكل': 'Settle all',
  /* منحنى الإيراد والمدينون */
  '📈 منحنى الإيراد': '📈 Revenue curve',
  'يومًا': 'days',
  'شهرًا': 'months',
  'يومي': 'Daily',
  'شهري': 'Monthly',
  'لا يوجد إيراد في هذه الفترة': 'No revenue in this period',
  '🧾 المدينون': '🧾 Debtors',
  'عمليات غير مسدّدة': 'Unpaid operations',
  'إجمالي مستحقاتهم': 'Their total dues',
  'مدفوع': 'Paid',
  '✅ لا يوجد مدينون — كل المبالغ مسدّدة': '✅ No debtors — everything is settled',
  'الإجمالي': 'Total',
  'تغيير كلمة المرور': 'Change password',
  'تبديل اللغة': 'Toggle language',
  'خروج': 'Logout',
  /* عام */
  'جارٍ التحميل…': 'Loading…',
  'انتهت الجلسة — سجّل دخولًا من جديد': 'Session ended — please sign in again',
  'خطأ غير متوقع': 'Unexpected error',
  'فشل التحميل': 'Download failed',
  'تم تنزيل الملف ✅': 'File downloaded ✅',
  'طبيب': 'Doctor',
  'مدير': 'Admin',
  'موظف': 'Staff',
  'ر.س': 'SAR',
  'ذكر': 'Male',
  'أنثى': 'Female',
  'حذف': 'Delete',
  'إجراء': 'Action',
  'بحث': 'Search',
  'تقرير': 'Report',
  'مراجعة': 'Review',
  'معاينة': 'View',
  'تنزيل': 'Download',
  'تحديث': 'Update',
  'تعليم': 'Mark read',
  'تأكيد': 'Confirm',
  'إتمام': 'Complete',
  'إلغاء': 'Cancel',
  'وصل': 'Arrived',
  'وصول': 'Arrive',
  'بدء': 'Start',
  'طباعة': 'Print',
  'الحالة': 'Status',
  'النوع': 'Type',
  'القسم': 'Department',
  'المريض': 'Patient',
  'الطبيب': 'Doctor',
  'التاريخ': 'Date',
  'الهاتف': 'Phone',
  'البريد': 'Email',
  'الاسم': 'Name',
  'العنوان': 'Address',
  'السرير': 'Bed',
  'السجل': 'Record',
  'الملف': 'File',
  'الرسالة': 'Message',
  'الإجمالي': 'Total',
  'الخصم': 'Discount',
  'الضريبة': 'Tax',
  'المبلغ': 'Amount',
  'الوصف': 'Description',
  'التخصص': 'Specialty',
  'الترخيص': 'License',
  'الدور': 'Floor',
  'السعر': 'Price',
  'النتيجة': 'Result',
  'الكمية': 'Quantity',
  'الوحدة': 'Unit',
  'الحجم': 'Size',
  'المنصب': 'Position',
  'الراتب': 'Salary',
  'الفترة': 'Period',
  'الأساسي': 'Base',
  'البدلات': 'Allowances',
  'الاستقطاعات': 'Deductions',
  'الوقت': 'Time',
  'الطريقة': 'Method',
  'المستخدم': 'User',
  'العمليات': 'Operations',
  'المسار': 'Path',
  'الطلبات': 'Requests',
  'التاريخ والوقت': 'Date & time',
  'السبب': 'Reason',
  'التشخيص': 'Diagnosis',
  'الوصفة الطبية': 'Prescription',
  'ملاحظات': 'Notes',
  'اسم القسم': 'Department name',
  'رقم السرير': 'Bed no.',
  'اسم الدواء': 'Medication name',
  'رمز الدواء': 'Code',
  'اسم التحليل': 'Test name',
  'حد التنبيه': 'Alert threshold',
  'رقم الترخيص': 'License no.',
  'تاريخ الميلاد': 'Date of birth',
  'تاريخ التعيين': 'Hire date',
  'تاريخ الرفع': 'Uploaded',
  'تاريخ الإنشاء': 'Created',
  'الهوية الوطنية': 'National ID',
  'رقم الهوية/الإقامة': 'ID/Iqama number',
  'شركة التأمين': 'Insurance company',
  'رقم وثيقة التأمين': 'Insurance policy no.',
  'مجموعة الدم': 'Blood group',
  'البريد الإلكتروني': 'Email address',
  'الاسم الكامل': 'Full name',
  'أُضيف': 'Created',
  'متاح': 'Available',
  'مشغول': 'Occupied',
  'صيانة': 'Maintenance',
  'متوفر': 'In stock',
  'مقروء': 'Read',
  'جديد': 'New',
  'معلّقة': 'Pending',
  'مؤكدة': 'Confirmed',
  'ملغاة': 'Cancelled',
  'مكتملة': 'Completed',
  'غير مدفوعة': 'Unpaid',
  'مدفوعة': 'Paid',
  'جزئية': 'Partial',
  'مصروف': 'Paid out',
  'غير مصروف': 'Not paid',
  'مسجّل': 'Registered',
  'قيد التنفيذ': 'In progress',
  'جاهزة': 'Ready',
  'مراجَعة': 'Reviewed',
  /* عناوين وأزرار */
  'إضافة مريض جديد': 'Add new patient',
  'إضافة طبيب جديد': 'Add new doctor',
  'إضافة قسم': 'Add department',
  'إضافة سرير': 'Add bed',
  'إضافة موظف': 'Add staff member',
  'إضافة سجل طبي': 'Add medical record',
  'إضافة قيد راتب': 'Add payroll entry',
  'حجز موعد جديد': 'New appointment',
  'حجز الموعد': 'Book appointment',
  'طلب تحليل/أشعة جديد': 'New lab/radiology order',
  'صرف دواء لمريض': 'Dispense medication',
  'سلة الصرف (متعددة البنود)': 'Dispense basket (multi-item)',
  'صرف السلة كلها': 'Dispense whole basket',
  'إضافة بند': 'Add item',
  'بحث بالباركود': 'Search by barcode',
  'امسح الباركود أو أدخل الرمز أولًا': 'Scan the barcode or enter the code first',
  'لا يوجد دواء بهذا الرمز': 'No medication with this code',
  'السلة فارغة — أضف بندًا أولًا': 'Basket is empty — add an item first',
  'أضف بن وصفة واحدًا على الأقل': 'Add at least one prescription item',
  'سبب الإرجاع إلزامي': 'Return reason is required',
  'إرجاع': 'Return',
  'إيصال': 'Receipt',
  'إتلاف': 'Dispose',
  'الوصفات الطبية': 'Medical prescriptions',
  'وصفة جديدة': 'New prescription',
  'حفظ الوصفة': 'Save prescription',
  'صرف الوصفة': 'Dispense prescription',
  'اقتراحات إعادة الطلب': 'Reorder suggestions',
  'توريد المقترح': 'Restock suggested',
  'إحصاءات PDF': 'Stats PDF',
  'إحصاءات CSV': 'Stats CSV',
  'إتلاف/إرجاع CSV': 'Disposals/returns CSV',
  'طلب CSV': 'Reorder CSV',
  '🏷️ ملصقات الكل': '🏷️ All labels',
  '🏷️ ملصق': '🏷️ Label',
  '🖨️ ورقة النتيجة': '🖨️ Result sheet',
  'عرض المعلّقات': 'Show pending',
  '⏳ وصفات معلّقة منذ أكثر من 24 ساعة': '⏳ Prescriptions pending over 24 hours',
  'وصفة معلّقة': 'Pending prescription',
  'كل الوصفات': 'All prescriptions',
  'إيراد الصرف': 'Dispense revenue',
  'وحدات مصروفة': 'Units dispensed',
  'عمليات صرف': 'Dispense operations',
  'منخفض/نافد': 'Low/out',
  'الجرعة': 'Dosage',
  'التكرار': 'Frequency',
  'المدة': 'Duration',
  'تعليمات': 'Instructions',
  'إنشاء فاتورة': 'Create invoice',
  'إنشاء الفاتورة': 'Create invoice',
  'إنشاء نسخة احتياطية الآن': 'Create backup now',
  'فحص السلامة': 'Verify integrity',
  'تنظيف النسخ حسب السياسة': 'Prune backups',
  'حفظ المريض': 'Save patient',
  'حفظ الطبيب': 'Save doctor',
  'حفظ القسم': 'Save department',
  'حفظ السرير': 'Save bed',
  'حفظ الموظف': 'Save staff',
  'حفظ السجل': 'Save record',
  'حفظ الدواء': 'Save medication',
  'حفظ الطلب': 'Save order',
  'حفظ القيد': 'Save entry',
  'رفع مرفق جديد': 'Upload new attachment',
  'حد أقصى': 'max',
  'رفع الملف': 'Upload file',
  'تصدير CSV': 'Export CSV',
  'استيراد CSV': 'Import CSV',
  'تحميل تقرير PDF': 'Download PDF report',
  'تقرير المختبر PDF': 'Lab report PDF',
  'تقرير المخزون PDF': 'Inventory report PDF',
  'كشف الرواتب': 'Payroll report',
  'مخزون الأدوية': 'Medication inventory',
  'سجل الصرف': 'Dispense log',
  'كل الحالات': 'All statuses',
  'طابور اليوم': 'Today\'s queue',
  'في الخدمة الآن': 'Now serving',
  'مواعيد اليوم': 'Today\'s appointments',
  'مواعيد معلّقة': 'Pending appointments',
  'أسرّة مشغولة': 'Occupied beds',
  'إيرادات محصّلة': 'Paid revenue',
  'مستحقات غير محصّلة': 'Outstanding dues',
  'توزيع المواعيد حسب الحالة': 'Appointments by status',
  'معاينة السجل': 'View record',
  'الملف PDF': 'File PDF',
  '💵 صرف': '💵 Pay out',
  'صرف CSV': 'Dispense CSV',
  'مخزون': 'Inventory',
  'صرف الآن': 'Dispense now',
  'الانتهاء': 'Expiry',
  'توريد': 'Restock',
  'التعيين': 'Hire',
  'الدفع': 'Payment',
  'دفع': 'Pay',
  'أساسي': 'Base',
  'خصم': 'discount',
  'ضريبة': 'tax',
  'علبة': 'Box',
  'ربط بموعد': 'Link appointment',
  'ربط بسجل طبي': 'Link record',
  'بحث بالمستخدم أو المسار': 'Search by user or path',
  'بحث بالاسم أو الهاتف أو الهوية': 'Search by name, phone or ID',
  'أكثر المستخدمين نشاطًا': 'Most active users',
  'أكثر المسارات طلبًا': 'Most requested paths',
  'أخطاء آخر الفترة': 'Recent errors',
  'تعليم الكل كمقروء': 'Mark all read',
  'النسخ الاحتياطي لقاعدة البيانات': 'Database backup',
  'سجل التدقيق — العمليات التعديلية': 'Audit log — write operations',
  '🔒 هذه الصفحة متاحة للمدير فقط': '🔒 Admin only',
  /* قسم المخزون */
  '📦 المخزون': '📦 Inventory',
  'المخزون': 'Inventory',
  'قيمة المخزون (ر.س)': 'Inventory value (SAR)',
  'عدد الأصناف': 'Items count',
  'إجمالي القطع': 'Total units',
  'مخزون منخفض': 'Low stock',
  'أصناف نافدة': 'Out-of-stock items',
  'أصناف تنتهي قريبًا': 'Expiring soon items',
  'أصناف منتهية': 'Expired items',
  'حركات المخزون': 'Stock movements',
  'نوع الحركة': 'Movement type',
  'الرصيد بعد الحركة': 'Balance after movement',
  'القيمة': 'Value',
  'الرمز': 'Code',
  'التغير': 'Change',
  'ملاحظة': 'Note',
  'سليم': 'OK',
  'منخفض': 'Low',
  'نافد': 'Out of stock',
  'قارب على الانتهاء': 'Expiring soon',
  'منتهي الصلاحية': 'Expired',
  'وارد': 'In',
  'صادر': 'Out',
  'جرد': 'Stocktake',
  'ابحث بالاسم أو الرمز': 'Search by name or code',
  'أيام قرب الانتهاء (0–365)': 'Days to expiry (0–365)',
  'أيام متبقية للانتهاء': 'Days remaining to expiry',
  'لا توجد أصناف مطابقة': 'No matching items',
  'لا حركات مخزون بعد': 'No stock movements yet',
  /* حالات فارغة */
  'لا توجد مواعيد بعد': 'No appointments yet',
  'لا توجد مواعيد': 'No appointments',
  'لا يوجد مرضى': 'No patients',
  'لا يوجد أطباء': 'No doctors',
  'لا توجد أقسام': 'No departments',
  'لا توجد أسرّة': 'No beds',
  'لا توجد فواتير': 'No invoices',
  'لا يوجد موظفون': 'No staff members',
  'لا قيود رواتب': 'No payroll entries',
  'لا مرفقات': 'No attachments',
  'لا توجد مرفقات — ارفع أول ملف': 'No attachments — upload your first file',
  'لا توجد سجلات': 'No records',
  'لا توجد طلبات': 'No orders yet',
  'لا عمليات صرف بعد': 'No dispenses yet',
  'لا توجد إشعارات': 'No notifications',
  'لا توجد عمليات بعد': 'No operations yet',
  'لا توجد نسخ بعد': 'No backups yet',
  'لا أدوية': 'No medications',
  'أضف أول دواء': 'add your first medication',
  'أنشئ أول طلب': 'create your first order',
  /* رسائل ونوافذ */
  'هل أنت متأكد من الحذف؟ لا يمكن التراجع.': 'Are you sure? This cannot be undone.',
  'تم الحفظ بنجاح': 'Saved successfully',
  'تم الحذف': 'Deleted',
  'املأ الحقول المطلوبة': 'Fill in the required fields',
  'التشخيص مطلوب': 'Diagnosis required',
  'اسم القسم مطلوب': 'Department name required',
  'رقم السرير مطلوب': 'Bed number required',
  'المبلغ والوصف مطلوبان': 'Amount and description are required',
  'اختر التاريخ والوقت': 'Select date and time',
  'الصيغة يجب أن تكون YYYY-MM': 'Format must be YYYY-MM',
  'صيغة الفترة: YYYY-MM': 'Period format: YYYY-MM',
  'كلمة المرور الحالية:': 'Current password:',
  'كلمة المرور الجديدة (8 أحرف على الأقل):': 'New password (min 8 characters):',
  'تأكيد كلمة المرور الجديدة:': 'Confirm new password:',
  'كلمتا المرور غير متطابقتين': 'Passwords do not match',
  'كلمة المرور قصيرة (8 أحرف على الأقل)': 'Password too short (min 8 characters)',
  'تم تغيير كلمة المرور ✅': 'Password changed ✅',
  'تم تسجيل الوصول': 'Arrival recorded',
  'تم تحديث الحالة': 'Status updated',
  'تم حفظ النتيجة': 'Result saved',
  'تم تحديث الطلب': 'Order updated',
  'تم تحديث السرير': 'Bed updated',
  'تم رفع الملف': 'File uploaded',
  'تم الصرف': 'Dispensed',
  'تم التوريد': 'Restocked',
  'تم الدفع': 'Payment recorded',
  'تم صرف الراتب 💵': 'Salary disbursed 💵',
  'اختر ملفًا أولًا': 'Choose a file first',
  'فشل الرفع': 'Upload failed',
  'فشل فتح نافذة الطباعة': 'Failed to open the print window',
  'اسمح بالنوافذ المنبثقة للمعاينة': 'Allow popups for the preview',
  'أدخل الشهر (YYYY-MM) أو اتركه فارغًا للفترة الحالية:': 'Enter month (YYYY-MM) or leave empty for the current period:',
  'أدخل نتيجة التحليل:': 'Enter the test result:',
  'كمية التوريد:': 'Restock quantity:',
  'أدخل كمية صحيحة': 'Enter a valid quantity',
  'طريقة الدفع (cash / card / insurance):': 'Payment method (cash / card / insurance):',
  'اختر: cash أو card أو insurance': 'Choose: cash, card or insurance',
  'المبلغ (اتركه فارغًا لدفع المتبقي كاملًا):': 'Amount (leave empty to pay the remaining balance):',
  'أدخل مبلغًا صحيحًا أكبر من صفر': 'Enter a valid amount greater than zero',
  'اسم التحليل مطلوب': 'Test name required',
  'الرمز والاسم مطلوبان': 'Code and name are required',
  'الفترة والراتب الأساسي مطلوبان': 'Period and base salary are required',
  'تأكيد صرف هذا الراتب؟': 'Confirm disbursement of this salary?',
  /* رسائل الخادم الشائعة */
  'اسم المستخدم أو كلمة المرور غير صحيحة': 'Invalid username or password',
  'تجاوزت محاولات الدخول الفاشلة': 'Too many failed login attempts',
  'أعد المحاولة بعد': 'Try again in',
  'ثانية': 'seconds',
  'الحساب غير نشط': 'Account is inactive',
  'كلمة المرور يجب أن تحتوي على حرف واحد على الأقل': 'Password must contain at least one letter',
  'كلمة المرور يجب أن تحتوي على رقم واحد على الأقل': 'Password must contain at least one digit',
  'كلمة المرور قصيرة — يجب أن تكون 8 أحرف على الأقل': 'Password too short — at least 8 characters',
  /* إدارة المستخدمين والصلاحيات */
  'المستخدمون': 'Users',
  'إضافة مستخدم جديد': 'Add new user',
  'الصلاحية': 'Role',
  'مدير النظام': 'Administrator',
  'موظف استقبال': 'Receptionist',
  'إنشاء الحساب': 'Create account',
  'الرمز والاسم والبريد وكلمة المرور مطلوبان': 'Code, name, email and password are required',
  'تم إنشاء المستخدم ✅': 'User created ✅',
  'تم تحديث الحساب ✅': 'Account updated ✅',
  'تم تغيير الصلاحية ✅': 'Role changed ✅',
  'نشط': 'Active',
  'معطّل': 'Disabled',
  'تعطيل': 'Disable',
  'تفعيل': 'Enable',
  'المستخدم غير موجود': 'User not found',
  'لا يمكنك تغيير دور حسابك': 'You cannot change your own role',
  'لا يمكن سحب صلاحية آخر مدير نشط': 'Cannot revoke the last active administrator',
  /* استعادة النسخ الاحتياطي */
  'استعادة': 'Restore',
  'تمت الاستعادة': 'Restore completed',
  'نسخة الأمان': 'safety copy',
  'سيُستبدل محتوى القاعدة الحالية — ستُصنع نسخة أمان تلقائيًا.': 'This replaces the current database contents — a safety copy is created first.',
  'تمت استعادة قاعدة البيانات بنجاح': 'Database restored successfully',
  'الاستعادة تتطلب ملف': 'Restore requires a',
  'الملف ليس قاعدة SQLite صالحة': 'File is not a valid SQLite database',
  'الملف ليس نسخة صحيحة لهذه القاعدة': 'File is not a valid copy of this database',
  'تعذّرت نسخة الأمان — لم تُستعد النسخة': 'Safety copy failed — restore aborted',
  /* تقويم المواعيد */
  'تقويم': 'Calendar',
  'الجدول': 'Table',
  'الشهر السابق': 'Previous month',
  'الشهر التالي': 'Next month',
  /* حماية الدخول على مستوى الـIP */
  'تجاوزت محاولات الدخول الفاشلة من هذا العنوان': 'Too many failed login attempts from this address',
  'أعد المحاولة لاحقًا': 'Try again later',
  /* سجل التدقيق: محاولات الدخول الفاشلة */
  'محاولات الدخول الفاشلة': 'Failed login attempts',
  'آخر 24 ساعة': 'Last 24 hours',
  'لا توجد محاولات فاشلة': 'No failed attempts',
  'الإجمالي': 'Total',
  /* شاشة المحاسبة (تبويباتها) */
  'المحاسبة': 'Accounting',
  'نظرة عامة': 'Overview',
  'المدينون': 'Debtors',
  'الدفتر العام': 'General Ledger',
  'التقارير': 'Reports',
  'اختر موظفًا لعرض ملفه': 'Select an employee to view their file',
  'لا توجد مرفقات لهذا الموظف.': 'No documents for this employee.',
  'حفظ ملف الموظف': 'Save Employee File'
};
const _enPairs = Object.entries(AR2EN).sort((a, b) => b[0].length - a[0].length);

function trEn(s) {
  let out = String(s == null ? '' : s);
  for (const [ar, en] of _enPairs) {
    if (out.indexOf(ar) !== -1) out = out.split(ar).join(en);
  }
  return out;
}
function tr(s) { return LANG === 'en' ? trEn(s) : s; }

/* ترجمة العقد النصية (مع حفظ النص الأصلي للاستعادة عند التبديل للعربية) */
function applyI18n(root) {
  if (!root) return;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  const nodes = [];
  while (w.nextNode()) {
    const n = w.currentNode;
    const tag = n.parentElement ? n.parentElement.tagName : '';
    if (tag === 'SCRIPT' || tag === 'STYLE') continue;
    nodes.push(n);
  }
  for (const n of nodes) {
    if (n.__ar === undefined) n.__ar = n.nodeValue;
    const v = LANG === 'en' ? trEn(n.__ar) : n.__ar;
    if (n.nodeValue !== v) n.nodeValue = v;
  }
  for (const el of root.querySelectorAll('[placeholder],[title]')) {
    for (const attr of ['placeholder', 'title']) {
      if (!el.hasAttribute(attr)) continue;
      const k = '__ar_' + attr;
      if (el[k] === undefined) el[k] = el.getAttribute(attr);
      const v = LANG === 'en' ? trEn(el[k]) : el[k];
      if (el.getAttribute(attr) !== v) el.setAttribute(attr, v);
    }
  }
}

function applyLangChrome() {
  document.documentElement.lang = LANG === 'en' ? 'en' : 'ar';
  document.documentElement.dir = LANG === 'en' ? 'ltr' : 'rtl';
  document.title = LANG === 'en'
    ? 'Hospital Management — Dashboard'
    : 'نظام إدارة المستشفيات — لوحة التحكم';
  document.querySelectorAll('.lang-btn').forEach(b => {
    b.textContent = LANG === 'en' ? '🌐 عربي' : '🌐 EN';
  });
}

function toggleLang() {
  LANG = LANG === 'en' ? 'ar' : 'en';
  localStorage.setItem('hms_lang', LANG);
  applyLangChrome();
  applyI18n(document.body);
  if (TOKEN && USER) navigate(CURRENT_VIEW);
}

function initLang() { applyLangChrome(); applyI18n(document.body); }

/* ترجمة نوافذ المتصفح الأصلية (prompt/confirm) */
const _nativePrompt = window.prompt;
const _nativeConfirm = window.confirm;
window.prompt = (m, d) => _nativePrompt.call(window, tr(m), d);
window.confirm = (m) => _nativeConfirm.call(window, tr(m));

async function download(path, name) {
  try {
    /* تقارير PDF تتبع لغة الواجهة (ar|en) */
    if (path.indexOf('/pdf') !== -1 && path.indexOf('lang=') === -1) {
      path += (path.indexOf('?') !== -1 ? '&' : '?') + 'lang=' + LANG;
    }
    const blob = await apiBlob(path);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
    toast('تم تنزيل الملف ✅');
  } catch (e) { toast(e.message, true); }
}

async function downloadPayroll(kind) {
  const p = ((document.getElementById('f-rpp') || {}).value || '').trim();
  await download('/reports/payroll/' + kind + (p ? '?period=' + p : ''),
                 'payroll_report.' + kind);
}

/* ========== الحسابات والمبيعات ========== */
let ACC = { period: '', method: '', status: '', patient: '', staff: '' };
let accGroup = 'day';

/* --- شاشة المحاسبة: التبويب الحالي + تعريفات التبويبات واختصارات القائمة --- */
let ACC_TAB = 'overview';
const ACC_TAB_LIST = [
  ['overview', '📊 نظرة عامة'],
  ['sales', '🛒 المبيعات'],
  ['debtors', '🧾 المدينون'],
  ['invoices', '💳 الفواتير'],
  ['ledger', '📒 الدفتر العام'],
  ['reports', '📄 التقارير']
];
/* أسماء الشاشات السابقة → التبويب المقابل (تعمل كاختصارات وعمق روابط) */
const ACC_ALIAS = { sales: 'sales', accounts: 'overview', invoices: 'invoices' };
/* مفتاح التبويب → اسم العرض المنفّذ داخل VIEWS (تبويب «نظرة عامة» = قسم الحسابات) */
const ACC_VIEW = {
  overview: 'accounts', sales: 'sales', debtors: 'debtors', invoices: 'invoices',
  ledger: 'ledger', reports: 'reports',
};

function setAccGroup(g) { accGroup = g; setAccTab('overview'); }

/* تمييل رابط القائمة المطابق للتبويب — وبقية الروابط تُطفأ */
function highlightAccTab(tab) {
  let hit = false;
  document.querySelectorAll('.sidebar a').forEach(a => {
    const on = a.dataset.tab === tab;
    if (on) hit = true;
    a.classList.toggle('active', on);
  });
  if (!hit) {
    const acc = document.querySelector('.sidebar a[data-view="accounting"]');
    if (acc) acc.classList.add('active');
  }
}

/* الانتقال بين تبويبات المحاسبة دون إعادة بناء الشاشة كاملة.
   المحتوى يُرسم أولاً في حاوية معزولة ثم يُنقل — فلا يكتب تبويب متأخر فوق الأحدث. */
let ACC_SEQ = 0;
async function setAccTab(tab) {
  if (!ACC_TAB_LIST.some(([k]) => k === tab)) tab = 'overview';
  ACC_TAB = tab;
  document.querySelectorAll('#acc-tabs .tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
  highlightAccTab(tab);
  const body = document.getElementById('acc-body');
  if (!body) return;
  const seq = ++ACC_SEQ;
  const stage = document.createElement('div');
  stage.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  try { await VIEWS[ACC_VIEW[tab] || tab](stage); }
  catch (e) { stage.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`; }
  if (seq !== ACC_SEQ || !body.isConnected) return;   /* تبويب/شاشة أحدث تولّى العرض */
  body.innerHTML = stage.innerHTML;
}

/* تحويل YYYY-MM إلى (من/إلى) — يرجع {} إذا كانت الفترة فارغة أو خاطئة */
function periodRange(period) {
  if (!period) return {};
  const m = /^(\d{4})-(\d{2})$/.exec(period.trim());
  if (!m) return {};
  const y = Number(m[1]), mo = Number(m[2]);
  if (mo < 1 || mo > 12) return {};
  const last = new Date(y, mo, 0).getDate();
  const pad = n => String(n).padStart(2, '0');
  return { from: `${y}-${pad(mo)}-01`, to: `${y}-${pad(mo)}-${pad(last)}T23:59:59` };
}

async function loadAccounts() {
  ACC = {
    period: V('f-acc-period') || '',
    method: V('f-acc-method') || '',
    status: V('f-acc-status') || '',
    patient: V('f-acc-patient') || '',
    staff: V('f-acc-staff') || ''
  };
  if (ACC.period && !/^\d{4}-\d{2}$/.test(ACC.period)) {
    ACC.period = '';
    return toast('صيغة الفترة: YYYY-MM', true);
  }
  await navigate('sales');
}

async function clearAccounts() {
  ACC = { period: '', method: '', status: '', patient: '', staff: '' };
  await navigate('sales');
}

/* ========== المخزون ========== */
let INV = { q: '', status: '', days: 30 };

/* ========== الصيدلية: حالة الفلاتر + بيانات مساعدة ========== */
let PH = { q: '', status: '' };
let PH_MEDS = [];   // كل الأدوية (للبحث بالباركود)
let PH_OPTS = '';   // خيارات <select> القابلة للصرف (بدون المنتهية)

async function loadInventory() {
  const d = V('f-inv-days');
  let days = (d === '' || d == null) ? 30 : Number(d);
  if (!Number.isFinite(days) || days < 0 || days > 365) {
    return toast('أيام قرب الانتهاء (0–365)', true);
  }
  INV = { q: V('f-inv-q') || '', status: V('f-inv-status') || '', days };
  await navigate('inventory');
}

async function clearInv() {
  INV = { q: '', status: '', days: 30 };
  await navigate('inventory');
}

async function downloadAccounts(kind) {
  const p = (ACC.period || '').trim();
  await download('/reports/accounts/sales/' + kind + (p ? '?period=' + p : ''),
                 'accounts_sales.' + kind);
}

/* كشف حساب مريض PDF — تُقرأ رقم المريض من حقل تبويب «التقارير» */
async function statementPdf() {
  const pid = V('f-rep-patient');
  if (!pid) return toast('أدخل رقم المريض أولًا', true);
  await download('/accounts/statement/' + pid + '/pdf', 'patient_statement_' + pid + '.pdf');
}

/* تسديد دفعة لعملية بيع — نافذة منبثقة (مبلغ + طريقة + معاينة المتبقي) */
let ACC_ROWS = [];

/* ══════════ قائمة المرضى: حالة العرض (بحث/فلاتر/ترقيم/ترتيب) ══════════
   الحالة تعيش خارج VIEWS كي تبقى محفوظة عند إعادة رسم الشاشة، والبحث
   يُرسل إلى الخادم (كان قبلها يطابق نص الصف كله ⇒ نتائج مضلّلة). */
const PAGE_SIZE = 25;
let PAT_LIST = { search: '', blood: '', alert: false, sort: 'created', sortDir: 'desc', page: 0, total: 0 };
let patSearchTimer = null;

function getPatientListState() { return { ...PAT_LIST }; }
function setPatientListState(patch) { Object.assign(PAT_LIST, patch); }

/* إعادة رسم شاشة المرضى فقط (تبقى الفلاتر) — بلا إعادة تحميل الصفحة كلها */
function reloadPatients() { if (CURRENT_VIEW === 'patients') renderView('patients'); }

function searchPatients(value) {
  setPatientListState({ search: value, page: 0 });
  clearTimeout(patSearchTimer);
  patSearchTimer = setTimeout(reloadPatients, 300);   /* مؤقّت ⇒ طلب واحد بعد التوقف */
}

function filterPatients() {
  setPatientListState({
    blood: (document.getElementById('flt-blood') || {}).value || '',
    alert: (document.getElementById('flt-alert') || {}).checked || false,
    page: 0,
  });
  reloadPatients();
}

function resetPatients() {
  setPatientListState({ search: '', blood: '', alert: false, page: 0 });
  reloadPatients();
}

function gotoPatientPage(n) {
  const st = getPatientListState();
  const pages = Math.max(1, Math.ceil((st.total || 0) / PAGE_SIZE));
  setPatientListState({ page: Math.max(0, Math.min(n, pages - 1)) });
  reloadPatients();
}

function sortPatients(key) {
  const st = getPatientListState();
  const same = st.sort === key;
  // created ينزل تنازليًا افتراضيًا (الأحدث أولًا)، والاسم/العمر تصاعديًا
  const descFirst = key === 'created';
  setPatientListState({
    sort: key,
    sortDir: same ? (st.sortDir === 'asc' ? 'desc' : 'asc') : (descFirst ? 'desc' : 'asc'),
    page: 0,
  });
  reloadPatients();
}

/* نموذج الإضافة — يشمل حقول الملف الشخصي والتأمين والتاريخ الطبي
   حتى لا تُكتب نفس البيانات مرتين (مرة عند الإضافة ومرة في الملف). */
function patientAddForm() {
  return `<details class="addbox"><summary>➕ إضافة مريض جديد</summary>
    <div class="form-grid">
      <div class="field"><label>الاسم الكامل *</label><input id="f-name"></div>
      <div class="field"><label>تاريخ الميلاد *</label><input id="f-dob" type="date"></div>
      <div class="field"><label>النوع *</label><select id="f-gender"><option>ذكر</option><option>أنثى</option></select></div>
      <div class="field"><label>الجنسية</label><input id="f-nat2" placeholder="اختياري"></div>
      <div class="field"><label>حالة التدخين</label><select id="f-smoke">
        <option value="">—</option><option>غير مدخّن</option><option>مدخّن</option>
        <option>مقلّح سابقًا</option></select></div>
      <div class="field"><label>مجموعة الدم</label><select id="f-blood"><option value="">—</option>
        <option>O+</option><option>O-</option><option>A+</option><option>A-</option>
        <option>B+</option><option>B-</option><option>AB+</option><option>AB-</option></select></div>
      <div class="field"><label>الهاتف *</label><input id="f-phone"></div>
      <div class="field"><label>البريد الإلكتروني *</label><input id="f-email" type="email"></div>
      <div class="field"><label>العنوان</label><input id="f-addr"></div>
      <div class="field"><label>الهوية الوطنية</label><input id="f-nat" placeholder="رقم الهوية/الإقامة"></div>
      <div class="field"><label>جهة الطوارئ</label><input id="f-emg" placeholder="اسم شخص للطوارئ"></div>
      <div class="field"><label>هاتف الطوارئ</label><input id="f-emgph"></div>
      <div class="field"><label>شركة التأمين</label><input id="f-ins" placeholder="اختياري"></div>
      <div class="field"><label>رقم وثيقة التأمين</label><input id="f-pol"></div>
      <div class="field"><label>درجة التغطية</label><select id="f-grade">
        <option value="">—</option><option>ذهبية</option><option>فضية</option>
        <option>برونزية</option><option>أساسية</option></select></div>
      <div class="field"><label>نسبة التحمل %</label><input id="f-copay" type="number" min="0" max="100" step="1"></div>
      <div class="field wide"><label>الحساسية</label><input id="f-allergy" placeholder="أدوية/أطعمة"></div>
      <div class="field wide"><label>تحذيرات طبية</label><input id="f-warn" placeholder="مريض سكر، سيولة في الدم…"></div>
    </div>
    <button class="btn success" style="margin-top:12px" onclick="addPatient()">حفظ المريض</button>
    <p class="muted">ما لا تملأه هنا يمكن إضافته لاحقًا من 🗂️ ملف المريض.</p>
  </details>`;
}

/* ══════════ شاشة ملف المريض: الأقسام الستة ══════════
   نقطة واحدة GET /patients/{id}/chart تجمع كل الأقسام، والتبويبات تُرسم
   من الذاكرة (CHART) بلا طلبات إضافية — تبديل التبويب فوري. */
let CHART = null, CHART_ID = null, CHART_TAB = 'profile';

const CHART_TABS = [
  ['profile', 'الملف الشخصي', '🪪'],
  ['record', 'السجل الطبي', '🩺'],
  ['visits', 'المواعيد والزيارات', '📅'],
  ['orders', 'الفحوصات والوصفات', '🔬'],
  ['billing', 'الحسابات والتأمين', '💰'],
  ['docs', 'المرفقات', '📎'],
];

const emptyRow = (cols, msg) =>
  `<tr><td colspan="${cols}" class="empty">${msg}</td></tr>`;

async function openPatientChart(id) {
  CHART_ID = id;
  try {
    CHART = await api(`/patients/${id}/chart`);
  } catch (e) { return toast(e.message, true); }
  if (!CHART) return;
  CHART_TAB = 'profile';
  openModal('🗂️ ملف المريض', `<div id="chart-box"></div>`, true);
  renderPatientChart();
  paintChartTab();
}

function chartHead() {
  const p = CHART.profile;
  return `<div class="chart-head">
    <div><h3>${esc(p.full_name)}</h3>
      <p>${esc(p.gender)} · ${fmtDate(p.date_of_birth)} · 🩸 ${esc(p.blood_type || '—')}
         ${p.national_id ? ' · 🪪 ' + esc(p.national_id) : ''}</p></div>
    <div class="actions">
      <button class="btn ghost sm" onclick="download('/patients/${p.id}/pdf','patient_${p.id}_file.pdf')">📄 الملف PDF</button>
      <button class="btn ghost sm" onclick="download('/accounts/statement/${p.id}/pdf','patient_statement_${p.id}.pdf')">🧾 كشف الحساب</button>
    </div></div>`;
}

function renderPatientChart() {
  const box = document.getElementById('chart-box');
  if (!box) return;
  box.innerHTML = chartHead() + `
    <div class="tabbar" id="chart-tabs">${CHART_TABS.map(([k, l, i]) =>
      `<button class="tab${k === CHART_TAB ? ' active' : ''}" data-ctab="${k}"
        onclick="setChartTab('${k}')">${i} ${tr(l)}</button>`).join('')}</div>
    <div id="chart-body"></div>`;
}

function setChartTab(tab) { CHART_TAB = tab; renderPatientChart(); paintChartTab(); }

async function paintChartTab() {
  const body = document.getElementById('chart-body');
  if (!body || !CHART) return;
  document.querySelectorAll('#chart-tabs .tab').forEach(b =>
    b.classList.toggle('active', b.dataset.ctab === CHART_TAB));
  body.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  const renderers = { profile: chartProfile, record: chartRecord, visits: chartVisits,
                      orders: chartOrders, billing: chartBilling, docs: chartDocs };
  try { body.innerHTML = renderers[CHART_TAB](); }
  catch (e) { body.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`; }
  applyI18n(body);
}

/* — (1) الملف الشخصي والإداري — */
function chartProfile() {
  const p = CHART.profile;
  const f = (l, id, v, type = 'text') =>
    `<div class="field"><label>${tr(l)}</label>
      <input data-pf="${id}" type="${type}" value="${esc(v == null ? '' : v)}"></div>`;
  const ta = (l, id, v) =>
    `<div class="field wide"><label>${tr(l)}</label>
      <textarea data-pf="${id}" rows="2">${esc(v || '')}</textarea></div>`;
  return `<div class="card">
    <h3>🪪 البيانات الشخصية</h3>
    <div class="form-grid">
      ${f('الاسم الكامل', 'full_name', p.full_name)}
      ${f('الرقم القومي/الهوية', 'national_id', p.national_id)}
      ${f('تاريخ الميلاد', 'date_of_birth', (p.date_of_birth || '').slice(0, 10), 'date')}
      ${f('الجنس', 'gender', p.gender)}
      ${f('الجنسية', 'nationality', p.nationality)}
      ${f('حالة التدخين', 'smoking_status', p.smoking_status)}
      ${f('فصيلة الدم', 'blood_type', p.blood_type)}
    </div>
    <h3 style="margin-top:18px">📞 معلومات الاتصال</h3>
    <div class="form-grid">
      ${f('رقم الهاتف', 'phone', p.phone)}
      ${f('البريد الإلكتروني', 'email', p.email, 'email')}
      ${f('العنوان', 'address', p.address)}
      ${f('جهة الطوارئ', 'emergency_contact_name', p.emergency_contact_name)}
      ${f('هاتف الطوارئ', 'emergency_contact_phone', p.emergency_contact_phone)}
      ${f('صلة القرابة', 'emergency_contact_relation', p.emergency_contact_relation)}
    </div>
    <h3 style="margin-top:18px">🏢 التأمين الصحي</h3>
    <div class="form-grid">
      ${f('شركة التأمين', 'insurer', p.insurer)}
      ${f('رقم البوليصة', 'policy_number', p.policy_number)}
      ${f('درجة التغطية', 'insurance_grade', p.insurance_grade)}
      ${f('نسبة التحمل %', 'insurance_copay', p.insurance_copay, 'number')}
    </div>
    <button class="btn success" style="margin-top:14px" onclick="savePatientProfile()">💾 حفظ الملف الشخصي</button>
  </div>

  <div class="card">
    <h3>🩺 التاريخ الطبي</h3>
    <div class="form-grid">
      ${ta('الأمراض المزمنة', 'chronic_conditions', p.chronic_conditions)}
      ${ta('العمليات الجراحية السابقة', 'past_surgeries', p.past_surgeries)}
      ${ta('التاريخ العائلي المرضي', 'family_history', p.family_history)}
    </div>
    <h3 style="margin-top:18px">⚠️ الحساسية والتحذيرات</h3>
    <div class="form-grid">
      ${ta('الحساسية (أدوية/أطعمة)', 'allergies', p.allergies)}
      ${ta('تحذيرات طبية مهمة', 'medical_warnings', p.medical_warnings)}
    </div>
  </div>`;
}

async function savePatientProfile() {
  const body = {};
  document.querySelectorAll('#chart-body [data-pf]').forEach(el => {
    let v = el.value;
    if (el.type === 'number') v = v === '' ? null : Number(v);
    else if (v === '') v = null;
    body[el.dataset.pf] = v;
  });
  try {
    CHART.profile = await api(`/patients/${CHART_ID}/profile`, {
      method: 'PUT', body: JSON.stringify(body) });
    toast('تم حفظ الملف ✅');
    renderPatientChart(); paintChartTab();
  } catch (e) { toast(e.message, true); }
}

/* — (2) السجل الطبي: الزيارات + العلامات الحيوية — */
function chartRecord() {
  const p = CHART.profile;
  const warn = (t, v, cls) => v ? `<div class="alert-box ${cls}"><b>${tr(t)}</b><span>${esc(v)}</span></div>` : '';
  return `<div class="card">
    <h3>⚠️ ملخّص التحذيرات</h3>
    <div class="alert-grid">
      ${warn('الحساسية', p.allergies, 'danger')}
      ${warn('تحذيرات طبية', p.medical_warnings, 'warn')}
      ${warn('أمراض مزمنة', p.chronic_conditions, 'info')}
      ${warn('عمليات سابقة', p.past_surgeries, 'info')}
      ${warn('تاريخ عائلي', p.family_history, 'info')}
    </div>
    ${(!p.allergies && !p.medical_warnings && !p.chronic_conditions)
      ? '<div class="empty">لا توجد تحذيرات مسجّلة</div>' : ''}
  </div>

  <div class="card">
    <h3>💓 العلامات الحيوية (${CHART.vitals.length})</h3>
    <details class="addbox"><summary>➕ تسجيل قياس جديد</summary>
      <div class="form-grid">
        <div class="field"><label>الضغط الانقباضي</label><input id="v-sys" type="number" min="0" max="300"></div>
        <div class="field"><label>الضغط الانبساطي</label><input id="v-dia" type="number" min="0" max="200"></div>
        <div class="field"><label>الحرارة °C</label><input id="v-temp" type="number" step="0.1" min="30" max="45"></div>
        <div class="field"><label>النبض</label><input id="v-pulse" type="number" min="0" max="250"></div>
        <div class="field"><label>الوزن كجم</label><input id="v-weight" type="number" step="0.1" min="1"></div>
        <div class="field"><label>الطول سم</label><input id="v-height" type="number" step="0.1" min="30"></div>
        <div class="field wide"><label>ملاحظات</label><input id="v-notes"></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addVital()">حفظ القياس</button>
    </details>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الضغط</th><th>الحرارة</th><th>النبض</th><th>الوزن</th><th>الطول</th><th>BMI</th><th></th></tr></thead>
      <tbody>${CHART.vitals.map(v => `<tr>
        <td>${fmtDate(v.recorded_at)}</td>
        <td>${v.systolic || '-'}/${v.diastolic || '-'}</td>
        <td>${v.temperature ?? '-'}</td><td>${v.pulse ?? '-'}</td>
        <td>${v.weight ?? '-'}</td><td>${v.height ?? '-'}</td>
        <td>${v.bmi ?? '-'}</td>
        <td class="actions">${isAdmin() ? `<button class="btn sm danger" onclick="delVital(${v.id})">حذف</button>` : ''}</td>
      </tr>`).join('') || emptyRow(8, 'لا توجد علامات حيوية مسجّلة')}</tbody>
    </table></div>
  </div>

  <div class="card">
    <h3>🩺 الملاحظات الطبية والتشخيصات (${CHART.records.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الطبيب</th><th>الشكوى</th><th>التشخيص</th><th>الوصفة</th><th>ملاحظات</th></tr></thead>
      <tbody>${CHART.records.map(r => `<tr>
        <td>${fmtDate(r.created_at)}</td>
        <td>${esc(r.doctor ? r.doctor.full_name : '—')}</td>
        <td>${esc(r.chief_complaint || '—')}</td>
        <td><strong>${esc(r.diagnosis)}</strong></td>
        <td>${esc(r.prescription || '—')}</td>
        <td>${esc(r.notes || '—')}</td>
      </tr>`).join('') || emptyRow(6, 'لا توجد زيارات مسجّلة')}</tbody>
    </table></div>
  </div>`;
}

async function addVital() {
  const num = id => { const v = V(id); return v === '' || v === undefined ? null : Number(v); };
  const body = { systolic: num('v-sys'), diastolic: num('v-dia'), temperature: num('v-temp'),
                 pulse: num('v-pulse'), weight: num('v-weight'), height: num('v-height'),
                 notes: V('v-notes') || null };
  try {
    await api(`/patients/${CHART_ID}/vitals`, { method: 'POST', body: JSON.stringify(body) });
    toast('تم تسجيل القياس ✅');
    await refreshChart();
  } catch (e) { toast(e.message, true); }
}

async function delVital(id) {
  if (!confirm('حذف هذا القياس؟')) return;
  try {
    await api(`/patients/${CHART_ID}/vitals/${id}`, { method: 'DELETE' });
    toast('تم الحذف ✅');
    await refreshChart();
  } catch (e) { toast(e.message, true); }
}

/* إعادة تحميل نقطة الملف بعد تعديل (تبقى التبويب الحالي) */
async function refreshChart() {
  CHART = await api(`/patients/${CHART_ID}/chart`);
  renderPatientChart(); paintChartTab();
}

/* — (3) المواعيد والزيارات — */
function chartVisits() {
  const { past = [], upcoming = [] } = CHART.appointments;
  const rows = (list, empty) => list.map(a => `<tr>
      <td>${fmtDate(a.appointment_date)}</td>
      <td>${esc(a.doctor ? a.doctor.full_name : '—')}</td>
      <td>${esc(a.reason || '—')}</td>
      <td><span class="pill ${a.status}">${esc(a.status)}</span></td>
    </tr>`).join('') || emptyRow(4, empty);
  return `<div class="card">
    <h3>📅 سجل الزيارات السابقة (${past.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الطبيب</th><th>السبب</th><th>الحالة</th></tr></thead>
      <tbody>${rows(past, 'لا زيارات سابقة')}</tbody>
    </table></div>
  </div>
  <div class="card">
    <h3>⏰ المواعيد القادمة (${upcoming.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الطبيب</th><th>السبب</th><th>الحالة</th></tr></thead>
      <tbody>${rows(upcoming, 'لا مواعيد قادمة')}</tbody>
    </table></div>
    <p class="muted">لتعديل أو إلغاء موعد افتح شاشة «المواعيد».</p>
  </div>`;
}

/* — (4) الفحوصات والخدمات الطبية — */
function chartOrders() {
  const stLbl = { pending: 'مسجّل', in_progress: 'قيد التنفيذ', ready: 'جاهزة',
                  reviewed: 'مراجَعة', cancelled: 'ملغاة' };
  return `<div class="card">
    <h3>🔬 المختبر والأشعة (${CHART.lab_orders.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>النوع</th><th>الفحص</th><th>الحالة</th><th>النتيجة</th><th></th></tr></thead>
      <tbody>${CHART.lab_orders.map(l => `<tr>
        <td>${fmtDate(l.ordered_at)}</td>
        <td>${l.test_type === 'radiology' ? '🩻 أشعة' : '🧪 مختبر'}</td>
        <td><strong>${esc(l.test_name)}</strong></td>
        <td><span class="pill ${l.status}">${esc(stLbl[l.status] || l.status)}</span></td>
        <td>${esc(l.result || '—')}</td>
        <td><button class="btn sm ghost" onclick="download('/lab-orders/${l.id}/pdf','lab_${l.id}.pdf')">🖨️ ورقة</button></td>
      </tr>`).join('') || emptyRow(6, 'لا فحوصات')}</tbody>
    </table></div>
  </div>

  <div class="card">
    <h3>💊 الوصفات الطبية (${CHART.prescriptions.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الطبيب</th><th>التشخيص</th><th>الحالة</th><th></th></tr></thead>
      <tbody>${CHART.prescriptions.map(r => `<tr>
        <td>${fmtDate(r.created_at)}</td>
        <td>${esc(r.doctor ? r.doctor.full_name : '—')}</td>
        <td>${esc(r.diagnosis || '—')}</td>
        <td><span class="pill ${r.status}">${esc(r.status)}</span></td>
        <td><button class="btn sm ghost" onclick="download('/prescriptions/${r.id}/pdf','rx_${r.id}.pdf')">🖨️ وصفة</button></td>
      </tr>`).join('') || emptyRow(5, 'لا وصفات')}</tbody>
    </table></div>
  </div>

  <div class="card">
    <h3>🛒 الأدوية المصروفة (${CHART.dispenses.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الدواء</th><th>الكمية</th><th>الجرعة</th><th>الإجمالي</th><th>الحالة</th></tr></thead>
      <tbody>${CHART.dispenses.map(s => `<tr>
        <td>${fmtDate(s.created_at)}</td>
        <td>${esc(s.medication ? s.medication.name : '—')}</td>
        <td>${s.quantity ?? '—'}</td>
        <td>${esc(s.dosage || '—')}</td>
        <td>${(s.total_price || 0).toLocaleString()} ر.س</td>
        <td><span class="pill ${s.status}">${esc(s.status)}</span></td>
      </tr>`).join('') || emptyRow(6, 'لا صرف')}</tbody>
    </table></div>
  </div>`;
}

/* — (5) الحسابات والمطالبات — */
function chartBilling() {
  const f = CHART.financials;
  const clLbl = { submitted: 'مُقدَّمة', approved: 'موافق عليها',
                  rejected: 'مرفوضة', paid: 'مسدَّدة' };
  return `<div class="card">
    <h3>💰 ملخّص الحساب</h3>
    <div class="stats">
      <div class="stat"><div class="num">${f.dues.toLocaleString()}</div><div class="lbl">إجمالي المستحق</div></div>
      <div class="stat green"><div class="num">${(f.invoices_paid + f.sales_paid).toLocaleString()}</div><div class="lbl">المسدَّد</div></div>
      <div class="stat ${f.outstanding > 0 ? 'red' : 'green'}"><div class="num">${f.outstanding.toLocaleString()}</div><div class="lbl">المتبقي</div></div>
      <div class="stat"><div class="num">${CHART.invoices.length}</div><div class="lbl">فواتير</div></div>
    </div>
    <p class="muted">فواتير الخدمات ${f.invoices_total.toLocaleString()} · صرف الصيدلية ${f.sales_total.toLocaleString()} ر.س</p>
  </div>

  <div class="card">
    <h3>🧾 الفواتير (${CHART.invoices.length})</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>التاريخ</th><th>الوصف</th><th>الإجمالي</th><th>المدفوع</th><th>الحالة</th><th></th></tr></thead>
      <tbody>${CHART.invoices.map(i => `<tr>
        <td>${fmtDate(i.created_at)}</td>
        <td>${esc(i.description || '—')}</td>
        <td>${(i.total || 0).toLocaleString()}</td>
        <td>${(i.paid_amount || 0).toLocaleString()}</td>
        <td><span class="pill ${i.status}">${esc(i.status)}</span></td>
        <td><button class="btn sm ghost" onclick="download('/invoices/${i.id}/pdf','invoice_${i.id}.pdf')">🖨️</button></td>
      </tr>`).join('') || emptyRow(6, 'لا فواتير')}</tbody>
    </table></div>
  </div>

  <div class="card">
    <h3>🏢 مطالبات التأمين (${CHART.claims.length})</h3>
    ${isAdmin() ? `<details class="addbox"><summary>➕ تقديم مطالبة</summary>
      <div class="form-grid">
        <div class="field"><label>رقم المطالبة *</label><input id="c-no"></div>
        <div class="field"><label>القيمة (ر.س) *</label><input id="c-amount" type="number" step="0.01" min="0"></div>
        <div class="field wide"><label>ملاحظات</label><input id="c-notes"></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addClaim()">تقديم المطالبة</button>
    </details>` : ''}
    <div style="overflow-x:auto"><table>
      <thead><tr><th>رقم المطالبة</th><th>الشركة</th><th>القيمة</th><th>الموافق</th><th>الحالة</th><th>القرار</th><th></th></tr></thead>
      <tbody>${CHART.claims.map(c => `<tr>
        <td><strong>${esc(c.claim_number)}</strong></td>
        <td>${esc(c.insurer || '—')}</td>
        <td>${(c.amount || 0).toLocaleString()}</td>
        <td>${c.approved_amount != null ? c.approved_amount.toLocaleString() : '—'}</td>
        <td><span class="pill ${c.status}">${esc(clLbl[c.status] || c.status)}</span></td>
        <td>${esc(c.rejection_reason || c.decision_notes || '—')}</td>
        <td class="actions">${isAdmin() ? `
          ${c.status !== 'approved' && c.status !== 'paid'
            ? `<button class="btn sm success" onclick="decideClaim(${c.id},'approved')">موافقة</button>` : ''}
          ${c.status !== 'rejected'
            ? `<button class="btn sm danger" onclick="decideClaim(${c.id},'rejected')">رفض</button>` : ''}
          <button class="btn sm ghost" onclick="delClaim(${c.id})">حذف</button>` : ''}</td>
      </tr>`).join('') || emptyRow(7, 'لا مطالبات تأمين')}</tbody>
    </table></div>
  </div>`;
}

async function addClaim() {
  const no = V('c-no'), amt = V('c-amount');
  if (!no || amt === '') return toast('رقم المطالبة والقيمة مطلوبان', true);
  try {
    await api(`/patients/${CHART_ID}/claims`, { method: 'POST',
      body: JSON.stringify({ claim_number: no, amount: Number(amt), decision_notes: V('c-notes') || null }) });
    toast('تم تقديم المطالبة ✅');
    await refreshChart();
  } catch (e) { toast(e.message, true); }
}

async function decideClaim(id, action) {
  const body = { status: action };
  if (action === 'approved') {
    const v = prompt('القيمة الموافق عليها (ر.س):', '0');
    if (v === null) return;
    body.approved_amount = Number(v);
  } else {
    const v = prompt('سبب الرفض:');
    if (!v) return;
    body.rejection_reason = v;
  }
  try {
    await api(`/patients/${CHART_ID}/claims/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    toast(action === 'approved' ? 'تم تسجيل الموافقة ✅' : 'تم تسجيل الرفض ❌');
    await refreshChart();
  } catch (e) { toast(e.message, true); }
}

async function delClaim(id) {
  if (!confirm('حذف هذه المطالبة؟')) return;
  try {
    await api(`/patients/${CHART_ID}/claims/${id}`, { method: 'DELETE' });
    toast('تم الحذف ✅');
    await refreshChart();
  } catch (e) { toast(e.message, true); }
}

/* — (6) المرفقات والوثائق — */
function chartDocs() {
  return `<div class="card">
    <h3>📎 المرفقات والوثائق (${CHART.attachments.length})</h3>
    <p class="muted">صور الهوية · بطاقة التأمين · التقارير الطبية الخارجية · نماذج الإقرار والتوقيعات (حد 10MB)</p>
    <label class="btn ghost" style="cursor:pointer;margin:0;display:inline-block">⬆️ رفع ملف
      <input type="file" style="display:none" onchange="uploadChartFile(this)"></label>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>الملف</th><th>النوع</th><th>الحجم</th><th>تاريخ الرفع</th><th></th></tr></thead>
      <tbody>${CHART.attachments.map(a => `<tr>
        <td><strong>${esc(a.original_name)}</strong></td>
        <td>${esc(a.content_type)}</td>
        <td>${(a.size_bytes / 1024).toFixed(0)} KB</td>
        <td>${fmtDate(a.uploaded_at)}</td>
        <td class="actions">
          <button class="btn sm ghost" onclick="window.open('/attachments/${a.id}/preview','_blank')">👁️ معاينة</button>
          <button class="btn sm ghost" onclick="download('/attachments/${a.id}/file','${esc(a.original_name)}')">⬇️ تنزيل</button>
        </td>
      </tr>`).join('') || emptyRow(5, 'لا مرفقات — ارفع صورة الهوية أو التقارير')}</tbody>
    </table></div>
  </div>`;
}

async function uploadChartFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('patient_id', CHART_ID);
  fd.append('file', file);
  try {
    const res = await fetch(API + '/attachments/', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + TOKEN }, body: fd });
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'فشل الرفع'); }
    toast('تم الرفع ✅');
    await refreshChart();
  } catch (e) { toast(e.message, true); }
}

function openModal(title, html, wide = false) {
  const t = document.getElementById('modal-title');
  t.textContent = title;
  document.getElementById('modal-body').innerHTML = html;
  const back = document.getElementById('modal-back');
  back.classList.add('show');
  back.classList.toggle('wide', !!wide);
  applyI18n(back);
}
function closeModal() { document.getElementById('modal-back').classList.remove('show'); }

function payRowHTML(s) {
  const rest = Math.max(0, Math.round((s.total_price - s.paid_amount) * 100) / 100);
  const opt = (v, label, sel) =>
    `<option value="${v}" ${sel ? 'selected' : ''}>${label}</option>`;
  return `
    <div class="kv"><span>عملية البيع</span><b>#${s.id}</b></div>
    <div class="kv"><span>الإجمالي</span><b>${s.total_price.toLocaleString()} ر.س</b></div>
    <div class="kv"><span>المدفوع</span><b style="color:#28a745">${s.paid_amount.toLocaleString()} ر.س</b></div>
    <div class="kv"><span>المتبقي</span><b style="color:${rest > 0 ? '#dc3545' : '#28a745'}">${rest.toLocaleString()} ر.س</b></div>
    <div class="field"><label>المبلغ (ر.س)</label>
      <input id="pay-amount" type="number" step="0.01" min="0" value="${rest}" oninput="payPreview()"></div>
    <div class="field"><label>طريقة الدفع</label>
      <select id="pay-method">
        ${opt('cash', 'نقدًا', s.payment_method !== 'card' && s.payment_method !== 'insurance')}
        ${opt('card', 'بطاقة', s.payment_method === 'card')}
        ${opt('insurance', 'تأمين', s.payment_method === 'insurance')}
      </select></div>
    <div class="kv" id="pay-after"><span>المتبقي بعد الدفع</span><b>—</b></div>
    <div class="row2">
      <button class="btn success" onclick="submitPay(${s.id})">تأكيد التسديد</button>
      <button class="btn ghost" onclick="closeModal()">إلغاء</button>
    </div>`;
}

function payPreview() {
  const s = window.__paySale; if (!s) return;
  const n = Number(document.getElementById('pay-amount').value);
  const box = document.getElementById('pay-after'); if (!box) return;
  if (isNaN(n) || n < 0) { box.innerHTML = '<span>المتبقي بعد الدفع</span><b>—</b>'; return; }
  const after = Math.max(0, Math.round((s.total_price - n) * 100) / 100);
  box.innerHTML = `<span>المتبقي بعد الدفع</span><b style="color:${after > 0 ? '#dc3545' : '#28a745'}">${after.toLocaleString()} ر.س</b>`;
  applyI18n(box);
}

function pay(id) {
  const s = ACC_ROWS.find(r => r.id === id);
  if (!s) return toast('تعذر فتح عملية البيع', true);
  window.__paySale = s;
  openModal('💰 تسديد دفعة', payRowHTML(s));
  payPreview();
  const el = document.getElementById('pay-amount');
  if (el) { el.focus(); el.select(); }
}

async function submitPay(id) {
  const s = window.__paySale; if (!s || s.id !== id) return;
  const raw = (document.getElementById('pay-amount').value || '').trim();
  const n = Number(raw);
  if (!raw || isNaN(n) || n <= 0) return toast('قيمة غير رقمية', true);
  const rest = Math.round((s.total_price - s.paid_amount) * 100) / 100;
  if (n > rest + 0.001) return toast('لا يمكن أن يتجاوز المبلغ المتبقي', true);
  const pm = document.getElementById('pay-method').value;
  /* الخادم يستبدل paid_amount — نرسل المجموع التراكمي للحفاظ على الدفعات السابقة */
  const total = Math.round((s.paid_amount + n) * 100) / 100;
  try {
    await api('/accounts/sales/' + id + '/payment', {
      method: 'PUT', body: JSON.stringify({ paid_amount: total, payment_method: pm }) });
    closeModal();
    toast('تم تسجيل الدفعة ✅');
    await navigate('sales');
  } catch (e) { toast(e.message, true); }
}

/* تسديد إجمالي كل العمليات غير المسددة دفعة واحدة */
async function payAll() {
  const rows = ACC_ROWS.filter(r => r.status !== 'PAID');
  if (!rows.length) return toast('لا توجد عمليات غير مسددة');
  if (!confirm('سيتم تسديد المتبقي كاملاً للعمليات غير المسددة. متابعة؟')) return;
  let done = 0;
  for (const s of rows) {
    try {
      await api('/accounts/sales/' + s.id + '/payment', {
        method: 'PUT',
        body: JSON.stringify({ paid_amount: s.total_price, payment_method: s.payment_method }) });
      done++;
    } catch (e) { /* نتابع ونبلّغ في النهاية */ }
  }
  toast(done === rows.length
    ? 'تم تسديد كل العمليات ✅'
    : `تم تسديد ${done} من ${rows.length} ⚠️`, done !== rows.length);
  await navigate('sales');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

/* ========== الدخول / الخروج ========== */
async function login() {
  const u = document.getElementById('li-user').value.trim();
  const p = document.getElementById('li-pass').value;
  const errBox = document.getElementById('login-err');
  errBox.style.display = 'none';
  try {
    const r = await api('/auth/login', { method: 'POST', body: JSON.stringify({ username: u, password: p }) });
    TOKEN = r.access_token; USER = r.user;
    const remember = document.getElementById('li-remember').checked;
    localStorage.removeItem('hms_token');
    localStorage.removeItem('hms_user');
    sessionStorage.removeItem('hms_token');
    sessionStorage.removeItem('hms_user');
    const store = remember ? localStorage : sessionStorage;
    store.setItem('hms_token', TOKEN);
    store.setItem('hms_user', JSON.stringify(USER));
    localStorage.setItem('hms_remember', remember ? '1' : '0');
    enterApp();
  } catch (e) { errBox.textContent = tr(e.message); errBox.style.display = 'block'; }
}

function logout() {
  TOKEN = ''; USER = null;
  localStorage.removeItem('hms_token');
  localStorage.removeItem('hms_user');
  localStorage.removeItem('hms_remember');
  sessionStorage.removeItem('hms_token');
  sessionStorage.removeItem('hms_user');
  document.getElementById('app-view').style.display = 'none';
  document.getElementById('login-view').style.display = 'flex';
}

function enterApp() {
  document.getElementById('login-view').style.display = 'none';
  document.getElementById('app-view').style.display = 'block';
  document.getElementById('ub-name').textContent = USER.full_name;
  document.getElementById('ub-role').textContent = tr(isDoctor() ? 'طبيب' : (isAdmin() ? 'مدير' : 'موظف'));
  navigate('dashboard');
  setInterval(refreshBell, 30000); // تحديث الجرس كل 30 ثانية
}

/* ========== التنقل ========== */
document.querySelectorAll('.sidebar a[data-view]').forEach(a => {
  a.addEventListener('click', e => { e.preventDefault(); navigate(a.dataset.view); });
});

const TITLES = {
  dashboard: 'لوحة التحكم', patients: 'المرضى', doctors: 'الأطباء',
  appointments: 'المواعيد', records: 'السجلات الطبية', attachments: 'المرفقات',
  departments: 'الأقسام', beds: 'الأسرّة', invoices: 'الفواتير',
  staff: 'الموظفون', hr: 'شؤون الموظفين', users: 'المستخدمون', backup: 'النسخ الاحتياطي', notifications: 'الإشعارات',
  lab: 'المختبر والأشعة', pharmacy: 'الصيدلية', inventory: 'المخزون', payroll: 'الرواتب',
  clinical: 'الرعاية والتشغيل', support: 'الصيانة والتعقيم', governance: 'الجودة والموارد',
  audit: 'سجل التدقيق', sales: 'المبيعات', accounts: 'الحسابات', accounting: 'المحاسبة'
};

async function refreshBell() {
  try {
    const r = await api('/notifications/unread-count');
    const el = document.getElementById('bell-count');
    if (el) {
      el.textContent = r.unread;
      el.style.color = r.unread > 0 ? '#dc3545' : '';
      el.style.fontWeight = r.unread > 0 ? 'bold' : '';
    }
  } catch (e) { /* تجاهل */ }
}

/* التنقل بين الشاشات — يُجدول واحدًا تلو الآخر حتى لا تكتب شاشة أبطأ محتواها فوق الأحدث */
let NAV_CHAIN = Promise.resolve();

function navigate(view) {
  const step = () => renderView(view);
  const run = NAV_CHAIN.then(step, step);
  NAV_CHAIN = run.catch(() => {});
  return run;
}

async function renderView(view) {
  /* اختصارات شاشة المحاسبة (المبيعات/الحسابات/الفواتير) تفتح تبويبها،
     ورابط «المحاسبة» نفسه يبدأ من تبويب «نظرة عامة» */
  if (ACC_ALIAS[view]) { ACC_TAB = ACC_ALIAS[view]; view = 'accounting'; }
  else if (view === 'accounting') { ACC_TAB = 'overview'; }
  CURRENT_VIEW = view;
  document.querySelectorAll('.sidebar a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  document.getElementById('page-title').textContent = tr(TITLES[view] || '');
  const main = document.getElementById('main');
  main.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  try { await VIEWS[view](main); }
  catch (e) { main.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`; }
  applyI18n(main);
  refreshBell();
}

const OP_GROUPS = {
  clinical: [['service-requests','مجموعات الرعاية والوحدات','🧑‍⚕️','service_pending'],['care-plans','خطط الرعاية والتقييم','🗺️','care_plans_active'],['physiotherapy','العلاج الطبيعي','🦵','service_pending'],['nutrition','التغذية السريرية','🥗','service_pending'],['emergency','الطوارئ','🚑','service_pending'],['home-health','الرعاية الصحية المنزلية','🏠','service_pending'],['wellness','برامج العافية','🧘','service_pending'],['housekeeping','النظافة والتدبير المنزلي','🧹','service_pending'],['nursing-tasks','مهام التمريض','🩺','nursing_pending'],['surgeries','مسرح العمليات','🏥','surgeries_active'],['admissions','التنويم الداخلي','🛏️','admitted']],
  support: [['blood-bank','بنك الدم','🩸','blood_available'],['maintenance','صيانة الأجهزة','🔧','maintenance_open'],['sterilization','التعقيم','♨️','sterilization_running']],
  governance: [['safety-events','الجودة ومكافحة العدوى والحوادث','🛡️','safety_open'],['budgets','الميزانيات','📊','budget_total'],['assets','الأصول الثابتة','🏗️',''],['patient-portal-accounts','حسابات بوابة المريض','👤','']]
};
const OP_FIELDS = {
  'service-requests': [['patient_id','المريض','number'],['service_type','نوع الخدمة','select',['care_sets','dental','physiotherapy','emergency','home_health','wellness','nutrition','housekeeping']],['title','العنوان'],['details','التفاصيل'],['priority','الأولوية']],
  physiotherapy: [['patient_id','المريض','number'],['therapist_id','الطبيب المعالج','number'],['title','عنوان الحالة'],['assessment','التقييم'],['plan','الخطة العلاجية'],['notes','ملاحظات']],
  nutrition: [['patient_id','المريض','number'],['title','عنوان الحالة'],['dietary_plan','الخطة الغذائية'],['meal_plan','خطة الوجبات'],['notes','ملاحظات']],
  emergency: [['patient_id','المريض','number'],['complaint','الشكوى'],['triage_level','الفرز','select',['resuscitation','emergent','urgent','less_urgent','non_urgent','standard']],['arrival_at','وقت الوصول','datetime'],['disposition','الوجهة'],['notes','ملاحظات']],
  'home-health': [['patient_id','المريض','number'],['coordinator','منسق الرعاية'],['care_plan','خطة الزيارة المنزلية'],['next_visit_at','الزيارة القادمة','datetime'],['notes','ملاحظات']],
  wellness: [['patient_id','المريض','number'],['program_name','اسم البرنامج'],['goal','الهدف'],['baseline_metrics','المؤشرات الأساسية'],['progress_notes','ملاحظات التقدم'],['next_review_at','موعد المراجعة','datetime']],
  housekeeping: [['room_number','رقم الغرفة'],['task_type','نوع المهمة','select',['cleaning','laundry','sanitation','linen','other']],['priority','الأولوية','select',['low','normal','high','critical']],['assigned_to','المسؤول'],['notes','ملاحظات']],
  'nursing-tasks': [['patient_id','المريض','number'],['department_id','القسم','number'],['title','المهمة'],['instructions','التعليمات'],['shift','الوردية','select',['day','evening','night']],['priority','الأولوية']],
  surgeries: [['patient_id','المريض','number'],['surgeon_id','الجراح','number'],['procedure_name','العملية'],['theater','المسرح'],['priority','الأولوية','select',['emergency','urgent','elective']]],
  admissions: [['patient_id','المريض','number'],['bed_id','السرير','number'],['department_id','القسم','number'],['admission_date','وقت الدخول','datetime'],['diagnosis','التشخيص'],['notes','ملاحظات']],
  'blood-bank': [['unit_number','رقم الوحدة'],['donor_name','المتبرع'],['blood_group','فصيلة الدم'],['component','المكون','select',['whole_blood','platelets','plasma','red_cells']],['quantity_ml','الكمية مل','number'],['expiry_date','تاريخ الصلاحية','datetime']],
  maintenance: [['asset_name','الجهاز'],['serial_number','الرقم التسلسلي'],['location','الموقع'],['issue','العطل'],['priority','الأولوية']],
  sterilization: [['machine_name','الجهاز'],['cycle_type','النوع','select',['autoclave','chemical','low_temperature']],['load_description','الحمولة'],['started_at','وقت البدء','datetime'],['operator_name','المشغل']],
  'safety-events': [['category','التصنيف','select',['incident','infection','medication','fall','equipment','other']],['severity','الخطورة','select',['low','medium','high','critical']],['title','الحادث'],['description','الوصف'],['location','الموقع']],
  budgets: [['fiscal_year','السنة','number'],['department','القسم'],['category','البند'],['allocated_amount','المخصص','number'],['spent_amount','المنصرف','number']],
  assets: [['asset_code','رمز الأصل'],['name','الاسم'],['category','الفئة'],['department','القسم'],['purchase_cost','التكلفة','number'],['salvage_value','القيمة المتبقية','number'],['useful_life_years','العمر','number']],
  'patient-portal-accounts': [['patient_id','المريض','number'],['username','اسم المستخدم'],['password','كلمة المرور']]
};
const OP_UNIT_PATHS = ['physiotherapy','nutrition','emergency','home-health','wellness','housekeeping'];
const OP_STATUS = {
  'service-requests':['in_progress','completed','cancelled'], 'nursing-tasks':['in_progress','completed','cancelled'], surgeries:['in_progress','completed','cancelled'], admissions:['discharged','transferred'],
  'blood-bank':['reserved','issued','quarantined','discarded'], maintenance:['in_progress','completed','cancelled'], sterilization:['passed','failed'], 'safety-events':['investigating','resolved','closed'], assets:['maintenance','retired'],
  physiotherapy:['in_treatment','suspended','completed','cancelled'], nutrition:['active','suspended','completed','cancelled'], emergency:['under_treatment','discharged','closed','cancelled'],
  'home-health':['active','on_hold','completed','cancelled'], wellness:['active','paused','completed','cancelled'], housekeeping:['in_progress','completed','cancelled']
};
// الوحدات التشغيلية تعمل تحت /service-units، وبقية الموارد تحت /clinical.
function opUrl(path, id) {
  return OP_UNIT_PATHS.includes(path)
    ? `/service-units/${path}${id ? `/${id}/status` : ''}`
    : `/clinical/${path}${id ? `/status/${id}` : ''}`;
}
let OP_PATH = '';
async function renderOps(main, group) {
  const ov = await api('/clinical/overview'), defs = OP_GROUPS[group].filter(([p]) => p !== 'patient-portal-accounts' || isAdmin());
  const cards = defs.map(([p,t,i,k]) => `<button class="stat" style="cursor:pointer;border:2px solid ${OP_PATH===p?'#2c7be5':'transparent'}" onclick="selectOps('${p}')"><div class="num">${k ? Number(ov[k] || 0) : '∞'}</div><div class="lbl">${i} ${t}</div></button>`).join('');
  const [path,title,icon] = defs.find(x => x[0] === OP_PATH) || defs[0]; OP_PATH = path;
  if (path === 'care-plans') { await renderCarePlans(main, cards); return; }
  const rows = await api(opUrl(path));
  const canAdd = (isAdmin() || isDoctor()) && path !== 'patient-portal-accounts' && !(isDoctor() && ['budgets','assets'].includes(path));
  main.innerHTML = `<div class="stats">${cards}</div><div class="card"><div class="toolbar"><h3 style="margin:0">${icon} ${title}</h3>${canAdd?'<button class="btn success" onclick="opForm()">➕ إضافة</button>':''}<input oninput="filterTable('ops-table',this.value)" placeholder="🔍 بحث…"></div><div style="overflow-x:auto"><table id="ops-table"><thead><tr><th>#</th><th>التفاصيل</th><th>الحالة</th><th>التاريخ</th><th>الإجراء</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${esc(opLabel(r))}</td><td>${pill(r.status || 'نشط')}</td><td>${fmtDate(r.created_at || r.started_at || r.purchase_date || r.admission_date)}</td><td><div class="actions">${canAdd?(OP_STATUS[path] || []).map(s => `<button class="btn sm ghost" onclick="opStatus('${path}',${r.id},'${s}')">${s}</button>`).join(''):'—'}</div></td></tr>`).join('') || `<tr><td colspan="5" class="empty">لا توجد سجلات</td></tr>`}</tbody></table></div></div>`;
async function renderCarePlans(main, cards) {
  const plans = await api('/clinical/care-plans?limit=200');
  const canManage = isAdmin() || isDoctor();
  const planCards = plans.map(plan => {
    const actions = canManage && plan.status === 'active' ? `<div class="actions" style="margin-top:10px">
      <button class="btn success sm" onclick="carePlanAction('complete',${plan.id})">إكمال الخطة</button>
      <button class="btn danger sm" onclick="carePlanAction('cancel',${plan.id})">إلغاء الخطة</button></div>` : '';
    const items = plan.items.map(item => {
      const execute = canManage && plan.status === 'active' && !['completed','cancelled'].includes(item.status)
        ? `<button class="btn sm" onclick="carePlanAction('execute',${plan.id},${item.id})">تسجيل تنفيذ</button>` : '';
      return `<tr><td>${item.id}</td><td>${esc(item.title)}</td><td>${esc(item.category)}</td>
        <td>${esc(item.assigned_to || '—')}</td><td>${esc(item.instructions || '—')}</td>
        <td>${pill(item.status)}</td><td>${fmtDate(item.completed_at || item.cancelled_at || item.scheduled_at)}</td>
        <td>${(item.executions || []).length}<div class="actions">${execute}</div></td></tr>`;
    }).join('');
    return `<details class="care-plan" ${plans.length === 1 ? 'open' : ''}>
      <summary><strong>${esc(plan.title)}</strong> — المريض #${plan.patient_id} ${pill(plan.status)}
        <span class="care-progress">${Number(plan.completion_percentage || 0).toLocaleString()}%</span></summary>
      <div class="care-goal"><b>الأهداف:</b> ${esc(plan.goals)}<br><b>الإحداث:</b> ${fmtDate(plan.started_at)} — ${esc(plan.coordinator || plan.created_by)}</div>
      <div style="overflow-x:auto"><table><thead><tr><th>#</th><th>البند</th><th>الفئة</th><th>المسؤول</th><th>التعليمات</th><th>الحالة</th><th>آخر إجراء</th><th>التنفيذات</th></tr></thead>
      <tbody>${items || '<tr><td colspan="8" class="empty">لا توجد بنود</td></tr>'}</tbody></table></div>${actions}</details>`;
  }).join('');
  main.innerHTML = `<div class="stats">${cards}</div><div class="card">
    <div class="toolbar"><h3 style="margin:0">🗺️ خطط الرعاية والتقييم</h3>
    ${canManage ? '<button class="btn success" onclick="carePlanForm()">➕ خطة جديدة</button>' : ''}
    <input oninput="filterCarePlans(this.value)" placeholder="🔍 بحث…"></div>
    <div id="care-plans-table">${planCards || '<div class="empty">لا توجد خطط رعاية بعد</div>'}</div></div>`;
}

function filterCarePlans(term) {
  document.querySelectorAll('#care-plans-table .care-plan').forEach(el => {
    el.style.display = el.textContent.toLowerCase().includes(term.trim().toLowerCase()) ? '' : 'none';
  });
}

function carePlanForm() {
  const now = new Date().toISOString().slice(0,16);
  const item = n => `<fieldset class="care-item-fields"><legend>بند الرعاية ${n}</legend><div class="form-grid">
    <div class="field"><label>الفئة</label><select id="cp-item-${n}-category">
    ${['nursing','medication','nutrition','mobility','education','discharge','other'].map(x=>`<option value="${x}">${x}</option>`).join('')}</select></div>
    <div class="field"><label>عنوان البند *</label><input id="cp-item-${n}-title"></div>
    <div class="field"><label>التعليمات</label><input id="cp-item-${n}-instructions"></div></div></fieldset>`;
  openModal('➕ خطة رعاية جديدة', `<div class="form-grid">
    <div class="field"><label>المريض *</label><input id="cp-patient" type="number" min="1"></div>
    <div class="field"><label>طلب الخدمة (اختياري)</label><input id="cp-request" type="number" min="1"></div>
    <div class="field"><label>التنويم (اختياري)</label><input id="cp-admission" type="number" min="1"></div>
    <div class="field"><label>بداية الخطة *</label><input id="cp-started" type="datetime-local" value="${now}"></div>
    <div class="field"><label>عنوان الخطة *</label><input id="cp-title"></div>
    <div class="field"><label>المنسق</label><input id="cp-coordinator"></div>
    <div class="field" style="grid-column:1/-1"><label>الأهداف *</label><textarea id="cp-goals" rows="2"></textarea></div>
  </div>${item(1)}${item(2)}<div class="row2"><button class="btn success" onclick="submitCarePlan()">حفظ الخطة</button>
  <button class="btn ghost" onclick="closeModal()">إلغاء</button></div>`);
}

async function submitCarePlan() {
  const items = [1,2].map(n => { const title=V(`cp-item-${n}-title`).trim(); return title ? {
    category:V(`cp-item-${n}-category`), title, instructions:V(`cp-item-${n}-instructions`).trim() || null } : null; }).filter(Boolean);
  const patientId=Number(V('cp-patient')), optional=id => { const n=Number(V(id)); return n>0?n:null; };
  if (patientId<1) return toast('أدخل رقم المريض الصحيح',true);
  if (!V('cp-title').trim() || !V('cp-goals').trim()) return toast('عنوان الخطة والأهداف مطلوبان',true);
  if (!items.length) return toast('أضف بند رعاية واحدًا على الأقل',true);
  try {
    await api('/clinical/care-plans',{method:'POST',body:JSON.stringify({patient_id:patientId,
      service_request_id:optional('cp-request'),admission_id:optional('cp-admission'),title:V('cp-title').trim(),
      goals:V('cp-goals').trim(),coordinator:V('cp-coordinator').trim()||null,started_at:V('cp-started'),items})});
    closeModal(); toast('تم إنشاء خطة الرعاية ✅'); await navigate(CURRENT_VIEW);
  } catch(e) { toast(typeof e.message==='string'?e.message:'تعذر إنشاء الخطة',true); }
}


}
function opLabel(r) { return esc(r.title || r.procedure_name || r.issue || r.load_description || r.unit_number || r.asset_name || r.name || r.username || `${r.department || ''} ${r.category || ''}`); }
function selectOps(path) { OP_PATH = path; navigate(CURRENT_VIEW); }
async function opStatus(path,id,status) { try { await api(opUrl(path,id),{method:'POST',body:JSON.stringify({status})}); toast('تم تحديث الحالة ✅'); await navigate(CURRENT_VIEW); } catch(e) { toast(e.message,true); } }
function opForm() {
  const defs = OP_FIELDS[OP_PATH] || [];
  const fields = defs.map(([n,l,t,opts]) => `<div class="field"><label>${l}</label>${t==='select'?`<select id="op-${n}">${opts.map(o=>`<option>${o}</option>`).join('')}</select>`:`<input id="op-${n}" type="${t||'text'}" ${t==='number'?'step="any"':''}>`}</div>`).join('');
  openModal('➕ إضافة سجل', `<div class="form-grid">${fields}</div><div class="row2" style="margin-top:12px"><button class="btn success" onclick="submitOp()">حفظ</button><button class="btn ghost" onclick="closeModal()">إلغاء</button></div>`);
}
async function submitOp() {
  const data = {}; (OP_FIELDS[OP_PATH] || []).forEach(([n,,t]) => { const v=V('op-'+n); if(v!=='' && v!=null) data[n]=t==='number'?Number(v):v; });
  try { await api(opUrl(OP_PATH),{method:'POST',body:JSON.stringify(data)}); closeModal(); toast('تمت الإضافة ✅'); await navigate(CURRENT_VIEW); } catch(e) { toast(e.message,true); }
}
async function carePlanAction(action, planId, itemId) {
  try {
    if (action === 'execute') {
      const notes = prompt('ملاحظات التنفيذ (اختياري)') ?? '';
      if (!confirm('تسجيل تنفيذ هذا البند الآن؟')) return;
      await api(`/clinical/care-plan-items/${itemId}/execute`, {method:'POST',body:JSON.stringify({
        executed_at:new Date().toISOString(),outcome:'completed',notes:notes.trim()||null})});
      toast('تم تسجيل تنفيذ البند ✅');
    } else if (action === 'complete') {
      if (!confirm('إكمال الخطة؟ يجب تنفيذ جميع البنود أولًا.')) return;
      await api(`/clinical/care-plans/${planId}/complete`,{method:'POST'}); toast('تم إكمال خطة الرعاية ✅');
    } else if (action === 'cancel') {
      if (!confirm('إلغاء الخطة وبنودها غير المنفذة؟')) return;
      await api(`/clinical/care-plans/${planId}/cancel`,{method:'POST'}); toast('تم إلغاء خطة الرعاية');
    }
    await navigate(CURRENT_VIEW);
  } catch (e) { toast(typeof e.message==='string'?e.message:'تعذر تنفيذ العملية',true); }
}



async function renderGeneralLedger(main) {
  try {
    const [gl, chart, entries, vendors, bills, trial] = await Promise.all([
      api('/accounts/ledger/summary'), api('/accounts/ledger/accounts'),
      api('/accounts/ledger/entries?limit=30'), api('/accounts/ledger/vendors'),
      api('/accounts/ledger/vendor-bills'), api('/accounts/ledger/trial-balance')
    ]);
    const money = v => `${(Number(v) || 0).toLocaleString('ar-SA', { maximumFractionDigits: 2 })} ر.س`;
    const aging = (title, rows) => `<div class="card"><h3>${title}</h3>
      <div style="overflow-x:auto"><table><thead><tr><th>الفئة</th><th>العدد</th><th>الإجمالي</th><th>المتبقي</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td>${esc(r.bucket)}</td><td>${r.count}</td><td>${money(r.total)}</td><td>${money(r.outstanding)}</td></tr>`).join('')}</tbody>
      </table></div></div>`;
    const actions = isAdmin() ? `<div class="toolbar">
      <button class="btn success sm" onclick="ledgerAction('postInvoice')">ترحيل فاتورة</button>
      <button class="btn success sm" onclick="ledgerAction('invoicePayment')">تحصيل دفعة</button>
      <button class="btn sm" onclick="ledgerAction('vendor')">إضافة مورد</button>
      <button class="btn sm" onclick="ledgerAction('vendorBill')">فاتورة مورد</button>
      <button class="btn ghost sm" onclick="ledgerAction('vendorPayment')">دفع مورد</button>
    </div>` : '';
    main.insertAdjacentHTML('beforeend', `
      <div class="card ledger-panel">
        <div class="toolbar"><h3 style="margin:0">🏛️ الدفتر العام والمحاسبة المؤسسية</h3>
          <span class="pill ${Math.abs(gl.trial_balance_difference) < 0.01 ? 'paid' : 'unpaid'}">
            فرق ميزان المراجعة: ${money(gl.trial_balance_difference)}</span>
          <button class="btn ghost sm" onclick="setAccTab('ledger')">تحديث</button></div>
        ${actions}
        <div class="stats" style="margin:16px 0">
          <div class="stat"><div class="num">${money(gl.cash)}</div><div class="lbl">النقدية والبنك</div></div>
          <div class="stat"><div class="num">${money(gl.accounts_receivable)}</div><div class="lbl">ذمم المرضى والتأمين</div></div>
          <div class="stat amber"><div class="num">${money(gl.accounts_payable)}</div><div class="lbl">ذمم الموردين</div></div>
          <div class="stat green"><div class="num">${money(gl.net_income)}</div><div class="lbl">صافي الربح</div></div>
        </div>
        <div class="toolbar"><h3 style="margin:0">ميزان المراجعة</h3>
          <span class="pill confirmed">مدين ${money(trial.total_debit)}</span>
          <span class="pill pending">دائن ${money(trial.total_credit)}</span></div>
        <div style="overflow-x:auto"><table><thead><tr><th>الكود</th><th>الحساب</th><th>مدين</th><th>دائن</th><th>الرصيد</th></tr></thead>
          <tbody>${trial.rows.map(r => `<tr><td>${esc(r.code)}</td><td>${esc(r.name)}</td><td>${money(r.debit)}</td><td>${money(r.credit)}</td><td><strong>${money(r.balance)}</strong></td></tr>`).join('') || '<tr><td colspan="5" class="empty">لا توجد قيود</td></tr>'}</tbody>
        </table></div>
      </div>
      <div class="card"><h3>📘 دليل الحسابات (${chart.length})</h3><div style="overflow-x:auto"><table>
        <thead><tr><th>الكود</th><th>الاسم</th><th>النوع</th><th>الحساب الأب</th><th>الحالة</th></tr></thead>
        <tbody>${chart.map(a => `<tr><td>${esc(a.code)}</td><td>${esc(a.name)}</td><td>${esc(a.account_type)}</td><td>${esc(a.parent_code || '—')}</td><td>${a.is_active ? 'نشط' : 'موقوف'}</td></tr>`).join('')}</tbody>
      </table></div></div>
      <div class="card"><h3>📒 القيود اليومية (${entries.length})</h3><div style="overflow-x:auto"><table>
        <thead><tr><th>رقم القيد</th><th>التاريخ</th><th>البيان</th><th>الحساب</th><th>مدين</th><th>دائن</th></tr></thead>
        <tbody>${entries.map(e => e.lines.map((l, i) => `<tr>${i ? '' : `<td rowspan="${e.lines.length}">${esc(e.entry_no)}</td><td rowspan="${e.lines.length}">${fmtDate(e.entry_date)}</td><td rowspan="${e.lines.length}">${esc(e.description)}</td>`}<td>${esc(l.account_code)} — ${esc(l.account_name)}</td><td>${money(l.debit)}</td><td>${money(l.credit)}</td></tr>`).join('')).join('') || '<tr><td colspan="6" class="empty">لا توجد قيود</td></tr>'}</tbody>
      </table></div></div>
      ${aging('⏳ أعمار ذمم المرضى', gl.debtors)}
      ${aging('🏭 أعمار ذمم الموردين', gl.creditors)}
      <div class="card"><h3>الموردون (${vendors.length}) وفواتيرهم (${bills.length})</h3><div style="overflow-x:auto"><table>
        <thead><tr><th>فاتورة المورد</th><th>المورد</th><th>التاريخ</th><th>الإجمالي</th><th>المتبقي</th><th>الحالة</th></tr></thead>
        <tbody>${bills.map(b => `<tr><td>${esc(b.bill_no)}</td><td>${esc(b.vendor_name)}</td><td>${fmtDate(b.bill_date)}</td><td>${money(b.amount)}</td><td>${money(b.outstanding)}</td><td>${esc(b.status)}</td></tr>`).join('') || `<tr><td colspan="6" class="empty">لا توجد فواتير موردين (${vendors.length} مورد مسجل)</td></tr>`}</tbody>
      </table></div></div>`);
  } catch (err) {
    main.insertAdjacentHTML('beforeend', `<div class="card"><div class="empty">تعذر تحميل الدفتر العام: ${esc(err.message || 'خطأ غير معروف')}</div></div>`);
  }
}

async function ledgerAction(action) {
  if (!isAdmin()) return toast('هذه العملية متاحة للمدير فقط', true);
  const ask = (label, required = true) => {
    const value = window.prompt(label);
    return value == null ? null : (required && !value.trim() ? (toast('لا يمكن ترك الحقل فارغًا', true), null) : value.trim());
  };
  const askNumber = (label, positive = true) => {
    const value = ask(label);
    if (value == null) return null;
    const number = Number(value);
    if (!Number.isFinite(number) || (positive && number <= 0)) {
      toast('أدخل قيمة رقمية صحيحة', true);
      return null;
    }
    return number;
  };
  const askChoice = (label, values) => {
    const value = ask(`${label} (${values.join(' / ')})`);
    return value && values.includes(value) ? value : (value ? (toast('اختر طريقة صحيحة', true), null) : null);
  };
  const now = () => new Date().toISOString();
  let path, payload = {};
  try {
    if (action === 'postInvoice') {
      const id = askNumber('رقم فاتورة المريض');
      if (id == null) return;
      path = `/accounts/ledger/invoices/${id}/post`;
    } else if (action === 'invoicePayment') {
      const id = askNumber('رقم فاتورة المريض');
      const amount = id == null ? null : askNumber('مبلغ التحصيل');
      const method = amount == null ? null : askChoice('طريقة التحصيل', ['cash', 'card', 'bank', 'insurance']);
      const reference = amount == null ? null : ask('مرجع الدفعة (اختياري)', false);
      if (id == null || amount == null || method == null || reference === null) return;
      path = `/accounts/ledger/invoices/${id}/payments`;
      payload = { amount, method, paid_at: now(), reference: reference || null };
    } else if (action === 'vendor') {
      const code = ask('كود المورد');
      const name = code == null ? null : ask('اسم المورد');
      const phone = name == null ? null : ask('هاتف المورد (اختياري)', false);
      if (code == null || name == null || phone === null) return;
      path = '/accounts/ledger/vendors';
      payload = { code, name, phone: phone || null };
    } else if (action === 'vendorBill') {
      const billNo = ask('رقم فاتورة المورد');
      const vendorId = billNo == null ? null : askNumber('رقم المورد');
      const amount = vendorId == null ? null : askNumber('قيمة الفاتورة');
      const expenseCode = amount == null ? null : ask('حساب المصروف (5100 افتراضي)', false);
      if (billNo == null || vendorId == null || amount == null || expenseCode === null) return;
      path = '/accounts/ledger/vendor-bills';
      payload = { bill_no: billNo, vendor_id: vendorId, amount, bill_date: now(),
                  due_date: now(), expense_account_code: expenseCode || '5100' };
    } else if (action === 'vendorPayment') {
      const id = askNumber('رقم فاتورة المورد');
      const amount = id == null ? null : askNumber('مبلغ الدفعة');
      const method = amount == null ? null : askChoice('طريقة الدفع', ['cash', 'card', 'bank']);
      const reference = method == null ? null : ask('مرجع الدفعة (اختياري)', false);
      if (id == null || amount == null || method == null || reference === null) return;
      path = `/accounts/ledger/vendor-bills/${id}/payments`;
      payload = { amount, method, paid_at: now(), reference: reference || null };
    } else {
      return toast('العملية غير معروفة', true);
    }
    await api(path, { method: 'POST', body: JSON.stringify(payload) });
    toast('تم ترحيل العملية المحاسبية ✅');
    await setAccTab('ledger');
  } catch (err) {
    toast(err.message || 'تعذر تنفيذ العملية المحاسبية', true);
  }
}


let HR_ROWS = [], HR_SELECTED = null, HR_TAB = 'personal', HR_ACCOUNTS = [];
const HR_TABS = [
  ['roster','قائمة الموظفين','👥'],
  ['personal','البيانات الشخصية والتعريفية','🪪'], ['employment','البيانات الوظيفية والإدارية','🏢'],
  ['salary','البيانات المالية والتعويضات','💰'], ['deductions','الاستقطاعات والتأمينات والضرائب','🧮'],
  ['attendance','الإجازات والدوام','🕒'], ['assets','العهد العينية والعهد','💻'],
  ['end_service','مستحقات نهاية الخدمة والقيود','🏁'], ['payroll','الرواتب','💵']
];
const HR_DEFAULT = {
  personal: { birth_date:'', gender:'', nationality:'', marital_status:'', national_id:'', passport_number:'', document_issue_date:'', document_expiry_date:'', phone:'', email:'', address:'' },
  employment: { job_title:'', job_grade:'', department:'', branch:'', manager:'', contract_type:'', probation_period:'', status:'على رأس العمل' },
  salary: { basic_salary:0, housing_allowance:0, transport_allowance:0, nature_of_work_allowance:0, communication_allowance:0, payment_method:'تحويل بنكي', bank_name:'', bank_account:'', iban:'', cost_center:'' },
  deductions: { employee_social_rate:0, company_social_rate:0, income_tax_rule:'', tax_allowance:0, other_deductions:0 },
  attendance: { annual_leave:0, sick_leave:0, special_leave:0, shift:'الوردية الصباحية', work_hours:'8', overtime_policy:'', absence_policy:'', late_policy:'' },
  assets: { loan_amount:0, monthly_installment:0, remaining_loan:0, assets:'', custody_notes:'' },
  end_service: { end_service_method:'مخصص الخدمة المتبقية', provision_rate:0, payroll_account:'', loan_account:'', end_service_account:'' }
};
function currentHR() { return HR_ROWS.find(x => x.id === HR_SELECTED) || null; }
function hrProfile() {
  const s = currentHR();
  const p = Object.assign({}, HR_DEFAULT, s?.hr_profile || {});
  /* ربط عمودي الموظف بالملف: الهاتف والبريد يُدخلان في شاشة الموظفين داخل أعمدة
     الموظف نفسها، فيُعرضان هنا متى لم يُدخَلا في الملف بعد — فلا يُطلب إدخالهما ثانية،
     وعند الحفظ يدفعهما saveHR إلى العمودين فتبقى المصدرين متّحدَين. */
  p.personal = Object.assign({}, HR_DEFAULT.personal, p.personal);
  if (!p.personal.phone) p.personal.phone = s?.phone || '';
  if (!p.personal.email) p.personal.email = s?.email || '';
  return p;
}
function hrField(group, key, label, type='text', options='') {
  const v = hrProfile()[group]?.[key] ?? '';
  const input = type === 'select' ? `<select data-hr="${group}.${key}">${options.map(o => `<option ${String(v)===o?'selected':''}>${esc(o)}</option>`).join('')}</select>`
    : type === 'number' ? `<input data-hr="${group}.${key}" type="number" min="0" step="0.01" value="${esc(v)}">`
    : `<input data-hr="${group}.${key}" type="${type}" value="${esc(v)}">`;
  return `<div class="field"><label>${label}</label>${input}</div>`;
}
function hrDirectoryHTML(filter='') {
  const list = HR_ROWS.filter(x => (x.full_name+' '+x.position).toLowerCase().includes(filter.toLowerCase()));
  return list.map(x => `<button class="hr-person${x.id===HR_SELECTED?' active':''}" onclick="selectHR(${x.id})">
    <span class="avatar">${esc((x.full_name||'?').trim().charAt(0))}</span><span><b>${esc(x.full_name)}</b><small>${esc(x.position)}</small></span>
    <i>${esc(x.hr_profile?.employment?.status || 'على رأس العمل')}</i></button>`).join('') || '<div class="empty">لا توجد نتائج</div>';
}
function hrEditorHTML() {
  const s = currentHR();
  if (!s) HR_TAB = 'roster';   /* بلا موظف مختار: القائمة هي العرض الافتراضي */
  const p = s ? hrProfile() : null;
  const tabs = `<div class="tabbar" role="tablist">${HR_TABS.map(([k,l,i])=>`<button class="tab${HR_TAB===k?' active':''}" role="tab" aria-selected="${HR_TAB===k}" onclick="setHRTab('${k}')">${i} ${l}</button>`).join('')}</div>`;
  /* تبويب «قائمة الموظفين»: الجدول + الإضافة + الحذف — بلا رأس ملف */
  if (HR_TAB === 'roster') return `<div class="card">${tabs}<div id="hr-tab" class="hr-tab">${hrTabHTML()}</div></div>`;
  return `<div class="card hr-card">
    <div class="hr-profile-head"><div><h3>${esc(s.full_name)}</h3><p>${esc(s.position)} · تعيين ${fmtDate(s.hire_date)}</p></div>
      <div class="actions"><button class="btn success" onclick="saveHR()">💾 حفظ ملف الموظف</button><span class="pill active">${esc(p.employment.status || 'على رأس العمل')}</span></div></div>
    ${tabs}
    <div id="hr-tab" class="hr-tab">${hrTabHTML()}</div></div>`;
}
/* اختيار موظف: يُعاد بناء المحرّر كاملًا — ومع التبويب الحالي «الرواتب»
   يجب إعادة رسم كشف الرواتب أيضًا، وإلا بقيت حاويتها فارغة (‎#hr-payroll‎)
   لأن hrEditorHTML() يعيد بناء <div id="hr-payroll"></div> من الصفر. */
async function selectHR(id) {
  captureHRFields(); HR_SELECTED=id;
  if (HR_TAB === 'roster') HR_TAB = 'personal';   /* من القائمة: يُفتح ملف الموظف مباشرة */
  document.getElementById('hr-list').innerHTML=hrDirectoryHTML();
  document.getElementById('hr-editor').innerHTML=hrEditorHTML();
  applyI18n(document.getElementById('hr-editor'));
  await renderHRCurrentTab();
}
async function setHRTab(tab) { captureHRFields(); HR_TAB=tab; document.getElementById('hr-editor').innerHTML=hrEditorHTML(); applyI18n(document.getElementById('hr-editor')); await renderHRCurrentTab(); }
/* رسم محتوى التبويب الذي يُبنى لاحقًا (القائمة أو الرواتب يُستدعى عبر VIEWS…) */
async function renderHRCurrentTab() {
  if (HR_TAB === 'roster') await renderHRRoster();
  else if (HR_TAB === 'payroll') await renderHRPayroll();
}
function filterHR(value) { document.getElementById('hr-list').innerHTML=hrDirectoryHTML(value); }
function captureHRFields() {
  const staff = currentHR();
  if (!staff) return;
  const profile = hrProfile();
  document.querySelectorAll('#hr-tab [data-hr]').forEach(el => {
    const [group, key] = el.dataset.hr.split('.');
    profile[group] = profile[group] || {};
    profile[group][key] = el.type === 'number' ? (el.value === '' ? 0 : Number(el.value)) : el.value;
  });
  staff.hr_profile = profile;
}
async function saveHR() {
  captureHRFields();
  const staff = currentHR();
  if (!staff) return;
  const p = hrProfile();
  try {
    await api(`/staff/${staff.id}`, { method: 'PUT', body: JSON.stringify({
      position: p.employment.job_title || staff.position, phone: p.personal.phone,
      email: p.personal.email, salary: Number(p.salary.basic_salary) || 0, hr_profile: p
    }) });
    toast('تم حفظ ملف الموظف ✅');
    await navigate('hr');
  } catch (e) { toast(e.message, true); }
}
async function uploadHRDocument(staffId) {
  const input = document.getElementById('hr-doc-file');
  if (!input?.files.length) return toast('اختر مستندًا أولًا', true);
  const fd = new FormData();
  fd.append('doc_type', document.getElementById('hr-doc-type').value);
  fd.append('file', input.files[0]);
  try {
    const res = await fetch(API + `/staff/${staffId}/documents`, { method: 'POST', headers: { 'Authorization': 'Bearer ' + TOKEN }, body: fd });
    if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || 'تعذر رفع المستند'); }
    toast('تم رفع المستند ✅'); await navigate('hr');
  } catch (e) { toast(e.message, true); }
}
function downloadStaffDoc(id) { download(`/staff/documents/${id}/file`, `staff-document-${id}`); }
async function deleteStaffDoc(id) {
  if (!confirm('حذف مستند الموظف نهائيًا؟')) return;
  try { await api(`/staff/documents/${id}`, { method: 'DELETE' }); toast('تم حذف المستند ✅'); await navigate('hr'); }
  catch (e) { toast(e.message, true); }
}

function hrTabHTML() {
  const p = hrProfile(), s = currentHR();
  if (HR_TAB === 'roster') return '<div id="hr-roster"></div>';
  if (HR_TAB === 'personal') return `<div class="section-title">🪪 البيانات الأساسية والوثائقية</div><div class="form-grid">
    ${hrField('personal','birth_date','تاريخ الميلاد','date')}${hrField('personal','gender','الجنس','select',['ذكر','أنثى'])}${hrField('personal','nationality','الجنسية')}${hrField('personal','marital_status','الحالة الاجتماعية','select',['أعزب','متزوج','مطلق','أرمل'])}
    ${hrField('personal','national_id','رقم الهوية / الرقم الوطني')}${hrField('personal','passport_number','رقم الجواز')}${hrField('personal','document_issue_date','تاريخ إصدار الوثائق','date')}${hrField('personal','document_expiry_date','تاريخ انتهاء الوثائق','date')}</div>
    <div class="section-title">📞 بيانات الاتصال</div><div class="form-grid">${hrField('personal','phone','رقم الهاتف','tel')}${hrField('personal','email','البريد الإلكتروني','email')}${hrField('personal','address','عنوان السكن الفعلي')}</div>
    <div class="section-title">📎 المرفقات</div><div class="hr-upload"><select id="hr-doc-type"><option value="id">صورة الرقم الوطني</option><option value="contract">العقد</option><option value="cv">السيرة الذاتية</option><option value="certificate">الشهادات</option><option value="other">أخرى</option></select><input id="hr-doc-file" type="file"><button class="btn" onclick="uploadHRDocument(${s.id})">⬆️ رفع مستند</button></div>
    <div class="hr-docs">${(s.documents||[]).map(d=>`<div class="hr-doc"><span>📄 ${esc(d.original_name)}</span><small>${esc(d.doc_type)} · ${Math.round(d.size_bytes/1024)} KB</small><button class="btn sm ghost" onclick="downloadStaffDoc(${d.id})">تنزيل</button><button class="btn sm danger" onclick="deleteStaffDoc(${d.id})">حذف</button></div>`).join('') || '<small class="muted">لا توجد مرفقات لهذا الموظف.</small>'}</div>`;
  if (HR_TAB === 'employment') return `<div class="section-title">🏢 المسمى الوظيفي والدرجة</div><div class="form-grid">${hrField('employment','job_title','المسمى المهني')}${hrField('employment','job_grade','المرفق الإداري / الدرجة الوظيفية')}</div><div class="section-title">🌳 التبعية الإدارية</div><div class="form-grid">${hrField('employment','department','القسم / الإدارة')}${hrField('employment','branch','الفرع')}${hrField('employment','manager','المدير المباشر')}</div><div class="section-title">📄 بيانات التعاقد</div><div class="form-grid">${hrField('employment','contract_type','نوع العقد','select',['محدد','غير محدد','دوام جزئي'])}${hrField('employment','probation_period','فترة التجربة')}${hrField('employment','status','حالة الموظف','select',['على رأس العمل','في إجازة','موقوف','نهيت خدماته'])}</div>`;
  if (HR_TAB === 'salary') return `<div class="section-title">💵 الهيكل المالي</div><div class="form-grid">${hrField('salary','basic_salary','الراتب الأساسي','number')}${hrField('salary','housing_allowance','بدل سكن','number')}${hrField('salary','transport_allowance','بدل مواصلات','number')}${hrField('salary','nature_of_work_allowance','بدل طبيعة عمل','number')}${hrField('salary','communication_allowance','بدل اتصالات','number')}</div><div class="section-title">🏦 طريقة الصرف والحساب البنكي</div><div class="form-grid">${hrField('salary','payment_method','طريقة الصرف','select',['تحويل بنكي','شيك','نقداً'])}${hrField('salary','bank_name','اسم البنك')}${hrField('salary','bank_account','رقم الحساب')}${hrField('salary','iban','رقم IBAN')}${hrField('salary','cost_center','مركز التكلفة','select',['تكلفة الإنتاج','مصاريف إدارية عمومية','مصاريف تسويق'])}</div>`;
  if (HR_TAB === 'deductions') return `<div class="section-title">🧮 التأمينات والضريبة</div><div class="form-grid">${hrField('deductions','employee_social_rate','نسبة خصم الموظف من التأمينات','number')}${hrField('deductions','company_social_rate','نسبة مشاركة الشركة','number')}${hrField('deductions','income_tax_rule','القاعدة الضريبية / شرائح ضريبة كسب العمل')}${hrField('deductions','tax_allowance','الخصم الإجمالي','number')}${hrField('deductions','other_deductions','استقطاعات ثابتة أخرى','number')}</div>`;
  if (HR_TAB === 'attendance') return `<div class="section-title">🌴 أرصدة الإجازات</div><div class="form-grid">${hrField('attendance','annual_leave','رصيد الإجازة السنوية','number')}${hrField('attendance','sick_leave','رصيد الإجازة المرضية','number')}${hrField('attendance','special_leave','رصيد الإجازة الخاصة','number')}</div><div class="section-title">🕒 سياسة الدوام</div><div class="form-grid">${hrField('attendance','shift','وردية العمل')}${hrField('attendance','work_hours','ساعات الدوام','number')}${hrField('attendance','overtime_policy','سياسة احتساب الإضافي')}${hrField('attendance','absence_policy','سياسة الغياب')}${hrField('attendance','late_policy','سياسة التأخير')}</div>`;
  if (HR_TAB === 'assets') return `<div class="section-title">💳 السلف والقروض</div><div class="form-grid">${hrField('assets','loan_amount','إجمالي السلفة','number')}${hrField('assets','monthly_installment','القسط الشهري','number')}${hrField('assets','remaining_loan','المتبقي','number')}</div><div class="section-title">💻 العهد العينية (Assets)</div>${hrField('assets','assets','الأجهزة المسلمة (لابتوب، سيارة، هاتف، أدوات)')}${hrField('assets','custody_notes','ملاحظات إبراء الذمة')}`;
  if (HR_TAB === 'payroll') return '<div id="hr-payroll"></div>';
  return `<div class="section-title">🏁 مستحقات نهاية الخدمة</div><div class="form-grid">${hrField('end_service','end_service_method','طريقة الاحتساب','select',['مخصص الخدمة المتبقية','نصف شهر عن كل سنة','أجر شهر عن كل سنة'])}${hrField('end_service','provision_rate','نسبة التخصيص','number')}</div><div class="section-title">🔗 الربط المحاسبي (Posting Accounts)</div><div class="form-grid">${hrField('end_service','payroll_account','حساب مجمع رواتب الموظفين','select',HR_ACCOUNTS.map(a=>a.code+' — '+a.name))}${hrField('end_service','loan_account','حساب سلف الموظفين','select',HR_ACCOUNTS.map(a=>a.code+' — '+a.name))}${hrField('end_service','end_service_account','حساب مستحقات نهاية الخدمة','select',HR_ACCOUNTS.map(a=>a.code+' — '+a.name))}</div>`;
}

/* تبويب «الرواتب» داخل شؤون الموظفين — يعيد استخدام شاشة قيود الرواتب كاملة
   (كشف + إضافة قيد + صرف + PDF/CSV) دون تكرار القائمة الجانبية أو تبويب المحاسبة */
async function renderHRPayroll() {
  const box = document.getElementById('hr-payroll');
  if (!box) return;
  box.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  try { await VIEWS.payroll(box); }
  catch (e) { box.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`; }
  applyI18n(box);   /* المحتوى يُبنى بعد applyI18n في المستدعي — نترجمه هنا */
}

/* تبويب «قائمة الموظفين» داخل شؤون الموظفين — يعيد استخدام شاشة الموظفين
   كاملة (الجدول + نموذج الإضافة + الحذف) بدل شاشة منفصلة في القائمة الجانبية */
async function renderHRRoster() {
  const box = document.getElementById('hr-roster');
  if (!box) return;
  box.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  try { await VIEWS.staff(box); }
  catch (e) { box.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`; }
  applyI18n(box);
}

const VIEWS = {
  /* --- شاشة شؤون الموظفين: ملف موظف بتبويبات متكاملة --- */
  async hr(main) {
    if (!isAdmin()) { main.innerHTML = '<div class="empty">🔒 هذه الصفحة متاحة للمدير فقط</div>'; return; }
    const [rows, accounts] = await Promise.all([api('/staff/'), api('/accounts/ledger/accounts')]);
    HR_ROWS = rows; HR_ACCOUNTS = accounts;
    const firstOpen = !HR_SELECTED;          /* أول فتح: نبدأ من قائمة الموظفين */
    if (!HR_SELECTED && rows.length) HR_SELECTED = rows[0].id;
    if (!rows.some(x => x.id === HR_SELECTED)) HR_SELECTED = rows[0]?.id || null;
    if (firstOpen) HR_TAB = 'roster';
    main.innerHTML = `
      <div class="hr-shell">
        <div class="card hr-directory">
          <div class="toolbar"><h3 style="margin:0">دليل الموظفين</h3>
            <input oninput="filterHR(this.value)" placeholder="🔍 بحث باسم الموظف…"></div>
          <div id="hr-list">${hrDirectoryHTML()}</div>
        </div>
        <div class="hr-editor" id="hr-editor">${hrEditorHTML()}</div>
      </div>`;
    applyI18n(document.getElementById('hr-editor'));
    await renderHRCurrentTab();
  },

  /* --- الموظفون --- */
  async staff(main) {
    const rows = await api('/staff/');
    const form = isAdmin() ? `
      <details class="addbox"><summary>➕ إضافة موظف</summary>
      <div class="form-grid">
        <div class="field"><label>الاسم الكامل *</label><input id="f-name"></div>
        <div class="field"><label>المنصب *</label><input id="f-pos"></div>
        <div class="field"><label>الهاتف *</label><input id="f-phone"></div>
        <div class="field"><label>البريد الإلكتروني *</label><input id="f-email" type="email"></div>
        <div class="field"><label>تاريخ التعيين *</label><input id="f-hire" type="date"></div>
        <div class="field"><label>الراتب</label><input id="f-sal" type="number" step="0.01"></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addStaff()">حفظ الموظف</button>
      </details>` : '';
    main.innerHTML = `
      <div class="card">
        <h3>الموظفون (${rows.length})</h3>
        ${form}
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>الاسم</th><th>المنصب</th><th>الهاتف</th><th>البريد</th><th>التعيين</th><th>الراتب</th>${isAdmin() ? '<th></th>' : ''}</tr></thead>
          <tbody>${rows.map(s => `<tr>
            <td>${s.id}</td><td><strong>${esc(s.full_name)}</strong></td><td>${esc(s.position)}</td>
            <td>${esc(s.phone)}</td><td>${esc(s.email)}</td><td>${fmtDate(s.hire_date)}</td>
            <td>${s.salary ? s.salary.toLocaleString() : '-'}</td>
            ${isAdmin() ? `<td><button class="btn sm danger" onclick="del('staff',${s.id},'hr')">حذف</button></td>` : ''}
          </tr>`).join('') || '<tr><td colspan="8" class="empty">لا يوجد موظفون</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- المرفقات --- */
  async attachments(main) {
    const [rows, patients, records] = await Promise.all([
      api('/attachments/'), api('/patients/'), api('/medical-records/')]);
    const fmtSize = b => b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.round(b / 1024) + ' KB';
    const icon = t => t.includes('image') ? '🖼️' : (t.includes('pdf') ? '📕' : '📄');
    main.innerHTML = `
      <div class="card">
        <h3>المرفقات الطبية (${rows.length})</h3>
        <details class="addbox"><summary>⬆️ رفع مرفق جديد (حد أقصى 10MB)</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-pat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>ربط بسجل طبي</label><select id="f-rec"><option value="">—</option>
            ${records.map(r => `<option value="${r.id}">#${r.id} — ${esc(r.patient.full_name)} — ${esc(r.diagnosis)}</option>`).join('')}</select></div>
          <div class="field" style="grid-column:1/-1"><label>الملف *</label><input id="f-file" type="file"></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="uploadAtt()">رفع الملف</button>
        </details>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>الملف</th><th>المريض</th><th>السجل</th><th>النوع</th><th>الحجم</th><th>تاريخ الرفع</th><th></th></tr></thead>
          <tbody>${rows.map(a => `<tr>
            <td>${a.id}</td>
            <td>${icon(a.content_type)} ${esc(a.original_name)}</td>
            <td>${esc(a.patient ? a.patient.full_name : '#'+a.patient_id)}</td>
            <td>${a.record_id ? '#' + a.record_id : '—'}</td>
            <td>${esc(a.content_type)}</td>
            <td>${fmtSize(a.size_bytes)}</td>
            <td>${fmtDate(a.uploaded_at)}</td>
            <td class="actions">
              <button class="btn sm ghost" onclick="previewAtt(${a.id})">👁️ معاينة</button>
              <button class="btn sm ghost" onclick="download('/attachments/${a.id}/file','${esc(a.original_name)}')">⬇️ تنزيل</button>
              <button class="btn sm danger" onclick="del('attachments',${a.id},'attachments')">حذف</button>
            </td>
          </tr>`).join('') || '<tr><td colspan="8" class="empty">لا توجد مرفقات — ارفع أول ملف</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- الإشعارات --- */
  async notifications(main) {
    const rows = await api('/notifications/');
    const icon = t => t === 'reminder' ? '⏰'
      : (t === 'appointment' ? '📅'
      : (t === 'lab_result' ? '🔬'
      : (t === 'low_stock' ? '💊'
      : (t === 'rx_stale' ? '⏳' : 'ℹ️'))));
    main.innerHTML = `
      <div class="card">
        <h3>الإشعارات (${rows.length})</h3>
        ${rows.some(n => !n.is_read) ? `<button class="btn ghost" style="margin-bottom:14px" onclick="readAll()">✓ تعليم الكل كمقروء</button>` : ''}
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>النوع</th><th>العنوان</th><th>الرسالة</th><th>التاريخ</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${rows.map(n => `<tr style="${n.is_read ? '' : 'background:#fff8e1'}">
            <td>${n.id}</td><td>${icon(n.type)}</td>
            <td><strong>${esc(n.title)}</strong></td>
            <td>${esc(n.message)}</td>
            <td>${fmtDate(n.created_at)}</td>
            <td>${n.is_read ? '<span class="pill completed">مقروء</span>' : '<span class="pill pending">جديد</span>'}</td>
            <td class="actions">
              ${!n.is_read ? `<button class="btn sm success" onclick="readNotif(${n.id})">تعليم</button>` : ''}
              <button class="btn sm danger" onclick="del('notifications',${n.id},'notifications')">حذف</button>
            </td>
          </tr>`).join('') || '<tr><td colspan="7" class="empty">لا توجد إشعارات</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- المختبر والأشعة --- */
  async lab(main) {
    const [rows, patients, doctors] = await Promise.all([
      api('/lab-orders/'), api('/patients/'), api('/doctors/')]);
    const stLabels = { pending: 'مسجّل', in_progress: 'قيد التنفيذ',
                       ready: 'جاهزة', reviewed: 'مراجَعة', cancelled: 'ملغاة' };
    main.innerHTML = `
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">طلبات المختبر والأشعة (${rows.length})</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${isAdmin() || isDoctor() ? `<button class="btn ghost" onclick="download('/reports/lab/pdf','lab_report.pdf')">📄 تقرير المختبر PDF</button>` : ''}
          ${isAdmin() || isDoctor() ? `<button class="btn ghost" onclick="download('/reports/lab/csv','lab_orders.csv')">⬇️ CSV</button>` : ''}
          </div>
        </div>
        <details class="addbox"><summary>➕ طلب تحليل/أشعة جديد</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-pat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>الطبيب</label><select id="f-doc"><option value="">—</option>
            ${doctors.map(d => `<option value="${d.id}">${esc(d.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>النوع</label><select id="f-type">
            <option value="lab">تحليل مختبري</option><option value="radiology">أشعة</option></select></div>
          <div class="field"><label>اسم التحليل *</label><input id="f-test" placeholder="مثال: CBC — صورة أشعة صدر"></div>
          <div class="field"><label>السعر (ر.س)</label><input id="f-price" type="number" step="0.01" min="0"></div>
          <div class="field"><label>ملاحظات</label><input id="f-lnotes"></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="addLabOrder()">حفظ الطلب</button>
        </details>
        <div class="toolbar"><input id="f-lab-q" placeholder="🔍 بحث…" oninput="filterLabRows()">
          <select id="f-lab-status" onchange="filterLabRows()">
            ${[['', 'كل الحالات'], ...Object.entries(stLabels)]
              .map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
          </select></div>
        <div style="overflow-x:auto"><table id="tbl">
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الطبيب</th><th>النوع</th><th>التحليل</th><th>الحالة</th><th>النتيجة</th><th></th></tr></thead>
          <tbody>${rows.map(o => `<tr data-status="${o.status}">
            <td>${o.id}</td><td>${fmtDate(o.ordered_at)}</td>
            <td>${esc(o.patient.full_name)}</td><td>${esc(o.doctor ? o.doctor.full_name : '-')}</td>
            <td>${o.test_type === 'radiology' ? 'أشعة 🔬' : 'تحليل 🧪'}</td>
            <td><strong>${esc(o.test_name)}</strong>${o.price ? `<br><small>${o.price.toLocaleString()} ر.س</small>` : ''}</td>
            <td><span class="pill ${o.status}">${stLabels[o.status] || o.status}</span></td>
            <td>${o.result ? esc(o.result) : '—'}</td>
            <td class="actions">
              <button class="btn sm ghost" onclick="download('/lab-orders/${o.id}/pdf','lab_result_${o.id}.pdf')">🖨️ ورقة النتيجة</button>
              ${o.status === 'pending' ? `<button class="btn sm ghost" onclick="setLabStatus(${o.id},'in_progress')">▶ بدء</button>` : ''}
              ${o.status === 'in_progress' ? `<button class="btn sm success" onclick="setLabResult(${o.id})">📥 النتيجة</button>` : ''}
              ${o.status === 'ready' && (isAdmin() || isDoctor()) ? `<button class="btn sm success" onclick="setLabStatus(${o.id},'reviewed')">🔎 مراجعة</button>` : ''}
              ${o.status !== 'cancelled' && o.status !== 'reviewed' ? `<button class="btn sm danger" onclick="setLabStatus(${o.id},'cancelled')">إلغاء</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('lab-orders',${o.id},'lab')">حذف</button>` : ''}
            </td>
          </tr>`).join('') || '<tr><td colspan="9" class="empty">لا توجد طلبات — أنشئ أول طلب</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- الصيدلية --- */
  async pharmacy(main) {
    const [meds, patients, dispenses, stats, rxs, reorder] = await Promise.all([
      api('/medications/'), api('/patients/'), api('/dispenses/'),
      api('/pharmacy/stats').catch(() => null),
      api('/prescriptions/').catch(() => []),
      api('/pharmacy/reorder').catch(() => [])]);
    PH_MEDS = meds;
    const nowMs = Date.now();
    const isExpired = m => m.expiry_date && new Date(m.expiry_date).getTime() < nowMs;
    const medStatus = m => isExpired(m) ? 'expired'
      : m.quantity === 0 ? 'out'
      : m.quantity <= m.min_quantity ? 'low' : 'ok';
    const stLbl = { ok: 'سليم', low: 'منخفض', out: 'نافد', expired: 'منتهي الصلاحية' };
    const stPill = { ok: 'confirmed', low: 'lowstock', out: 'unpaid', expired: 'cancelled' };
    // خيارات الأدوية القابلة للصرف (باستثناء المنتهية)
    PH_OPTS = meds.filter(m => !isExpired(m))
      .map(m => `<option value="${m.id}">${esc(m.name)} — متوفر ${m.quantity} ${esc(m.unit)}</option>`).join('')
      || '<option value="">— لا توجد أدوية متاحة —</option>';
    const dispenseOpts = PH_OPTS;
    const medForm = isAdmin() ? `
      <details class="addbox"><summary>➕ إضافة دواء للمخزون</summary>
      <div class="form-grid">
        <div class="field"><label>رمز الدواء *</label><input id="f-code" placeholder="PAR500"></div>
        <div class="field"><label>اسم الدواء *</label><input id="f-mname"></div>
        <div class="field"><label>الكمية</label><input id="f-qty" type="number" min="0" value="0"></div>
        <div class="field"><label>الوحدة</label><input id="f-unit" value="علبة"></div>
        <div class="field"><label>السعر (ر.س)</label><input id="f-mprice" type="number" step="0.01" min="0"></div>
        <div class="field"><label>حد التنبيه</label><input id="f-minq" type="number" min="0" value="10"></div>
        <div class="field"><label>تاريخ الانتهاء</label><input id="f-exp" type="date"></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addMedication()">حفظ الدواء</button>
      </details>` : '';
    /* بطاقات إحصاءات الفترة */
    const statsRow = stats ? `
      <div class="stats">
        <div class="stat"><div class="num">${stats.revenue.toLocaleString()} ر.س</div><div class="lbl">إيراد الصرف</div></div>
        <div class="stat green"><div class="num">${stats.paid.toLocaleString()} ر.س</div><div class="lbl">المحصّل</div></div>
        <div class="stat red"><div class="num">${stats.outstanding.toLocaleString()} ر.س</div><div class="lbl">المتبقي</div></div>
        <div class="stat"><div class="num">${stats.units}</div><div class="lbl">وحدات مصروفة</div></div>
        <div class="stat"><div class="num">${stats.dispense_count}</div><div class="lbl">عمليات صرف</div></div>
        <div class="stat amber"><div class="num">${stats.low + stats.out}</div><div class="lbl">منخفض/نافد</div></div>
        <div class="stat red"><div class="num">${stats.expired}</div><div class="lbl">منتهي الصلاحية</div></div>
      </div>` : '';
    /* وصفات معلّقة (PENDING أقدم من 24 ساعة) — تنبيه الصيدلية */
    const staleRx = rxs.filter(r => r.status === 'PENDING'
      && r.created_at && nowMs - new Date(r.created_at).getTime() > 24 * 3600e3);
    const staleCard = staleRx.length ? `
      <div class="card" id="rx-stale">
        <div class="toolbar"><h3 style="margin:0">⏳ وصفات معلّقة منذ أكثر من 24 ساعة (${staleRx.length})</h3>
          <button class="btn ghost" onclick="showStaleRx()">عرض المعلّقات</button></div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الطبيب</th><th>البنود</th><th>العمر</th><th></th></tr></thead>
          <tbody>${staleRx.map(r => `<tr>
            <td>${r.id}</td><td>${fmtDate(r.created_at)}</td>
            <td>${esc(r.patient ? r.patient.full_name : '#' + r.patient_id)}</td>
            <td>${r.doctor ? esc(r.doctor.full_name) : '—'}</td>
            <td>${(r.items || []).map(i => `${esc(i.medication ? i.medication.name : '#' + i.medication_id)} ×${i.quantity}`).join('<br>')}</td>
            <td><span class="pill pending">${Math.floor((nowMs - new Date(r.created_at).getTime()) / 3600e3)} ساعة</span></td>
            <td class="actions">
              <button class="btn sm ghost" onclick="download('/prescriptions/${r.id}/pdf','prescription_${r.id}.pdf')">🖨️ طباعة</button>
              ${isAdmin() ? `<button class="btn sm success" onclick="dispenseRx(${r.id})">💊 صرف</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="cancelRx(${r.id})">إلغاء</button>` : ''}
            </td>
          </tr>`).join('')}</tbody>
        </table></div>
      </div>` : '';
    /* فلاتر الجدول: بحث + حالة */
    const filterOpts = [['', 'كل الحالات'], ['ok', 'سليم'], ['low', 'منخفض'],
                        ['out', 'نافد'], ['expired', 'منتهي الصلاحية']]
      .map(([v, l]) => `<option value="${v}" ${PH.status === v ? 'selected' : ''}>${l}</option>`)
      .join('');
    /* حالة الوصفة */
    const rxLbl = { PENDING: 'قيد الصرف', PARTIAL: 'صرف جزئي',
                    DISPENSED: 'مصروف بالكامل', CANCELLED: 'ملغاة' };
    const rxPillCls = { PENDING: 'pending', PARTIAL: 'partial',
                        DISPENSED: 'confirmed', CANCELLED: 'cancelled' };
    const payPill = s => s === 'PAID' ? 'confirmed' : s === 'PARTIAL' ? 'partial' : 'unpaid';
    const payLbl = { PAID: 'مدفوع', PARTIAL: 'جزئيًا', UNPAID: 'غير مدفوع' };
    main.innerHTML = `
      ${statsRow}
      ${staleCard}
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">مخزون الأدوية (<span id="ph-count">${meds.length}</span>)</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/pdf','pharmacy_report.pdf')">📄 تقرير المخزون PDF</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/stats/pdf','pharmacy_stats.pdf')">📊 إحصاءات PDF</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/stats/csv','pharmacy_stats.csv')">📊 إحصاءات CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/csv?section=inventory','pharmacy_inventory.csv')">⬇️ مخزون CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/csv?section=dispenses','pharmacy_dispenses.csv')">⬇️ صرف CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/csv?section=disposals','pharmacy_disposals.csv')">🗑️ إتلاف/إرجاع CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/csv?section=reorder','pharmacy_reorder.csv')">🛒 طلب CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/inventory/labels','med_labels.pdf')">🏷️ ملصقات الكل</button>` : ''}
          </div>
        </div>
        <div class="toolbar">
          <input id="f-ph-q" placeholder="ابحث بالاسم أو الرمز" value="${esc(PH.q)}"
                 oninput="filterPharmacy()" style="min-width:180px">
          <select id="f-ph-status" onchange="filterPharmacy()">${filterOpts}</select>
          <input id="f-ph-code" placeholder="🔎 امسح الباركود ثم Enter"
                 onkeydown="if(event.key==='Enter'){event.preventDefault();quickFind();}" style="min-width:180px">
          <button class="btn" onclick="quickFind()">بحث بالباركود</button>
        </div>
        <details class="addbox" open><summary>🛒 سلة الصرف (متعددة البنود)</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-dpat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>باركود الدواء</label>
            <input id="f-basket-code" placeholder="امسح الباركود ثم Enter"
                   onkeydown="if(event.key==='Enter'){event.preventDefault();quickFind();}"></div>
          <div class="field"><label>ملاحظات</label><input id="f-basket-notes" placeholder="سياق الصرف"></div>
        </div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>الدواء *</th><th>الكمية *</th><th>الجرعة</th><th>التكرار</th><th>المدة</th><th>تعليمات</th><th></th></tr></thead>
          <tbody id="basket-rows">${basketRowHTML(dispenseOpts)}</tbody>
        </table></div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button class="btn ghost" onclick="addBasketRow()">➕ إضافة بند</button>
          <button class="btn success" onclick="dispenseBatch()">💸 صرف السلة كلها</button>
        </div>
        </details>
        ${medForm}
        <div style="overflow-x:auto"><table id="ph-meds">
          <thead><tr><th>#</th><th>الرمز</th><th>الاسم</th><th>الكمية</th><th>الحالة</th><th>السعر</th><th>حد التنبيه</th><th>الانتهاء</th><th></th></tr></thead>
          <tbody>${meds.map(m => {
            const st = medStatus(m);
            return `<tr data-status="${st}" data-text="${esc((m.name + ' ' + m.code).toLowerCase())}"
                    style="${st === 'low' || st === 'out' ? 'background:#fff8e1' : st === 'expired' ? 'background:#fff0f0' : ''}">
            <td>${m.id}</td><td>${esc(m.code)}</td><td><strong>${esc(m.name)}</strong></td>
            <td>${st === 'low' || st === 'out'
              ? `<span class="pill lowstock">${m.quantity} ${esc(m.unit)} ⚠️</span>`
              : `<span class="pill confirmed">${m.quantity} ${esc(m.unit)}</span>`}</td>
            <td><span class="pill ${stPill[st]}">${stLbl[st]}</span></td>
            <td>${m.price.toLocaleString()} ر.س</td>
            <td>${m.min_quantity}</td>
            <td>${m.expiry_date ? fmtDate(m.expiry_date) : '—'}</td>
            <td class="actions">
              ${isAdmin() ? `<button class="btn sm ghost" onclick="restock(${m.id})">📦 توريد</button>` : ''}
              ${isAdmin() ? `<button class="btn sm ghost" onclick="download('/inventory/labels?ids=${m.id}','label_${m.code}.pdf')">🏷️ ملصق</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="disposeMed(${m.id})">🗑️ إتلاف</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('medications',${m.id},'pharmacy')">حذف</button>` : ''}
            </td>
          </tr>`; }).join('') || '<tr><td colspan="9" class="empty">لا أدوية — أضف أول دواء</td></tr>'}</tbody>
        </table></div>
      </div>
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">📋 الوصفات الطبية (${rxs.length})</h3>
          <select id="f-rx-status" onchange="filterRxRows()">
            ${[['', 'كل الوصفات'], ...Object.entries(rxLbl)]
              .map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
          </select>
        </div>
        ${isAdmin() || isDoctor() ? `
        <details class="addbox"><summary>📝 وصفة جديدة</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-rx-pat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>ملاحظات الوصفة</label><input id="f-rx-notes" placeholder="مثال: بعد الفحص"></div>
        </div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>الدواء *</th><th>الكمية *</th><th>الجرعة</th><th>التكرار</th><th>المدة</th><th>تعليمات</th><th></th></tr></thead>
          <tbody id="rx-rows">${basketRowHTML(dispenseOpts)}</tbody>
        </table></div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button class="btn ghost" onclick="addRxItemRow()">➕ إضافة بند</button>
          <button class="btn success" onclick="createRx()">💾 حفظ الوصفة</button>
        </div>
        </details>` : ''}
        <div style="overflow-x:auto"><table id="rx-list">
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الطبيب</th><th>بنود</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${rxs.map(r => `<tr data-rxstatus="${r.status}">
            <td>${r.id}</td><td>${fmtDate(r.created_at)}</td>
            <td>${esc(r.patient ? r.patient.full_name : '#' + r.patient_id)}</td>
            <td>${r.doctor ? esc(r.doctor.full_name) : '—'}</td>
            <td>${(r.items || []).map(i => `${esc(i.medication ? i.medication.name : '#' + i.medication_id)}
              ×${i.quantity} ${i.dispensed_quantity ? `<small>(صُرف ${i.dispensed_quantity})</small>` : ''}`).join('<br>')}</td>
            <td><span class="pill ${rxPillCls[r.status] || 'pending'}">${rxLbl[r.status] || r.status}</span></td>
            <td class="actions">
              <button class="btn sm ghost" onclick="download('/prescriptions/${r.id}/pdf','prescription_${r.id}.pdf')">🖨️ طباعة</button>
              ${r.status !== 'CANCELLED' && r.status !== 'DISPENSED'
                ? `<button class="btn sm success" onclick="dispenseRx(${r.id})">💊 صرف الوصفة</button>` : ''}
              ${r.status === 'PENDING' ? `<button class="btn sm ghost" onclick="cancelRx(${r.id})">إلغاء</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('prescriptions',${r.id},'pharmacy')">حذف</button>` : ''}
            </td>
          </tr>`).join('') || '<tr><td colspan="7" class="empty">لا وصفات بعد</td></tr>'}</tbody>
        </table></div>
      </div>
      ${reorder.length ? `
      <div class="card">
        <h3>🛒 اقتراحات إعادة الطلب (${reorder.length})</h3>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>الرمز</th><th>الدواء</th><th>الرصيد</th><th>الحد</th><th>مستهلَك (30ي)</th>
            <th>متوسط/يوم</th><th>تغطية (يوم)</th><th>المقترح شراءه</th><th>التكلفة</th><th></th></tr></thead>
          <tbody>${reorder.map(r => `<tr>
            <td>${esc(r.code)}</td><td><strong>${esc(r.name)}</strong></td>
            <td>${r.quantity} ${esc(r.unit)}</td><td>${r.min_quantity}</td>
            <td>${r.consumed}</td><td>${r.avg_per_day}</td>
            <td>${r.days_cover === null ? '—' : r.days_cover}</td>
            <td><span class="pill lowstock">${r.suggested_qty} ${esc(r.unit)}</span></td>
            <td>${r.suggested_cost.toLocaleString()} ر.س</td>
            <td class="actions">${isAdmin()
              ? `<button class="btn sm ghost" onclick="restockSuggested(${r.medication_id},${r.suggested_qty})">📦 توريد المقترح</button>`
              : ''}</td>
          </tr>`).join('')}</tbody>
        </table></div>
      </div>` : ''}
      <div class="card">
        <h3>سجل الصرف (${dispenses.length})</h3>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الدواء</th><th>الكمية</th>
            <th>الجرعة</th><th>الإجمالي</th><th>الدفع</th><th>صرفه</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${dispenses.map(d => `<tr style="${d.returned_at ? 'background:#fff0f0' : ''}">
            <td>${d.id}</td><td>${fmtDate(d.created_at)}</td>
            <td>${esc(d.patient.full_name)}</td>
            <td>${esc(d.medication ? d.medication.name : '#' + d.medication_id)}
              ${d.prescription_id ? `<br><small>وصفة #${d.prescription_id}</small>` : ''}</td>
            <td>${d.quantity}</td>
            <td><small>${esc([d.dosage, d.frequency, d.duration].filter(Boolean).join(' · ') || '—')}</small></td>
            <td>${Number(d.total_price || 0).toLocaleString()} ر.س</td>
            <td><span class="pill ${payPill(d.status)}">${payLbl[d.status] || d.status}</span></td>
            <td>${esc(d.dispensed_by || '-')}</td>
            <td>${d.returned_at
              ? `<span class="pill cancelled" title="${esc(d.return_reason || '')}">مرتجع ↩</span>`
              : '<span class="pill confirmed">مصروف</span>'}</td>
            <td class="actions">
              <button class="btn sm ghost" onclick="openReceipt(${d.id})">🧾 إيصال</button>
              ${!d.returned_at ? `<button class="btn sm danger" onclick="returnDispense(${d.id})">↩ إرجاع</button>` : ''}
            </td>
          </tr>`).join('') || '<tr><td colspan="11" class="empty">لا عمليات صرف بعد</td></tr>'}</tbody>
        </table></div>
      </div>`;
    filterPharmacy();
  },

  /* --- المخزون: ملخص + أصناف بحالة + دفتر الحركات --- */
  async inventory(main) {
    const qs = new URLSearchParams();
    if (INV.q) qs.set('search', INV.q);
    if (INV.status) qs.set('status', INV.status);
    qs.set('expiring_days', INV.days);
    const [items, sum, moves] = await Promise.all([
      api('/inventory/?' + qs.toString()),
      api('/inventory/summary?expiring_days=' + INV.days),
      api('/inventory/movements?limit=50')]);
function saveHR() {
  const s = currentHR(); if (!s) return;
  const profile = hrProfile();
  document.querySelectorAll('#hr-editor [data-hr]').forEach(el => {
    const [group, key] = el.dataset.hr.split('.');
    profile[group][key] = el.type === 'number' ? Number(el.value || 0) : el.value;
  });
  const personal = profile.personal, employment = profile.employment;
  const body = {
    full_name: s.full_name, position: employment.job_title || s.position, phone: personal.phone,
    email: personal.email, hire_date: s.hire_date, salary: profile.salary.basic_salary,
    hr_profile: profile
  };
  api('/staff/' + s.id, { method: 'PUT', body: JSON.stringify(body) }).then(r => {
    Object.assign(s, r); toast('تم حفظ ملف الموظف ✅'); navigate('hr');
  }).catch(e => toast(e.message, true));
}
function setHRTab(tab) { HR_TAB = tab; const b = document.getElementById('hr-editor'); if (b) b.innerHTML = hrEditorHTML(); }
function selectHR(id) { HR_SELECTED = id; HR_TAB = 'personal'; document.getElementById('hr-list').innerHTML = hrDirectoryHTML(); const b = document.getElementById('hr-editor'); if (b) b.innerHTML = hrEditorHTML(); }
function filterHR(value) { const b = document.getElementById('hr-list'); if (b) b.innerHTML = hrDirectoryHTML(value); }
async function uploadHRDocument(staffId) {
  const file = document.getElementById('hr-doc-file').files[0];
  if (!file) return toast('اختر ملف المستند أولًا', true);
  const form = new FormData(); form.append('staff_id', staffId); form.append('doc_type', document.getElementById('hr-doc-type').value); form.append('file', file);
  try {
    await api('/staff-documents/', { method: 'POST', body: form });
    const docs = await api('/staff-documents/?staff_id=' + staffId);
    const s = currentHR(); if (s) s.documents = docs; toast('تم رفع المستند ✅'); navigate('hr');
  } catch(e) { toast(e.message, true); }
}
async function deleteStaffDoc(id) {
  if (!confirm('حذف هذا المستند؟')) return;
  try { await api('/staff-documents/' + id, { method: 'DELETE' }); toast('تم حذف المستند'); navigate('hr'); } catch(e) { toast(e.message, true); }
}

    const stPill = { ok: 'confirmed', low: 'lowstock', out: 'unpaid',
                     expiring: 'pending', expired: 'cancelled' };
    const stLbl = { ok: 'سليم', low: 'منخفض', out: 'نافد',
                    expiring: 'قارب على الانتهاء', expired: 'منتهي الصلاحية' };
    const mvPill = { in: 'confirmed', out: 'cancelled', adjust: 'in_progress' };
    const mvLbl = { in: 'وارد', out: 'صادر', adjust: 'جرد' };
    const opts = [['', 'كل الحالات'], ['ok', 'سليم'], ['low', 'منخفض'], ['out', 'نافد'],
                  ['expiring', 'قارب على الانتهاء'], ['expired', 'منتهي الصلاحية']]
      .map(([v, l]) => `<option value="${v}" ${INV.status === v ? 'selected' : ''}>${l}</option>`)
      .join('');
    const medForm = isAdmin() ? `
      <details class="addbox"><summary>➕ إضافة دواء للمخزون</summary>
      <div class="form-grid">
        <div class="field"><label>رمز الدواء *</label><input id="f-code" placeholder="PAR500"></div>
        <div class="field"><label>اسم الدواء *</label><input id="f-mname"></div>
        <div class="field"><label>الكمية</label><input id="f-qty" type="number" min="0" value="0"></div>
        <div class="field"><label>الوحدة</label><input id="f-unit" value="علبة"></div>
        <div class="field"><label>السعر (ر.س)</label><input id="f-mprice" type="number" step="0.01" min="0"></div>
        <div class="field"><label>حد التنبيه</label><input id="f-minq" type="number" min="0" value="10"></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addMedication('inventory')">حفظ الدواء</button>
      </details>` : '';
    main.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="num">${sum.total_value.toLocaleString()} ر.س</div><div class="lbl">قيمة المخزون (ر.س)</div></div>
        <div class="stat green"><div class="num">${sum.items}</div><div class="lbl">عدد الأصناف</div></div>
        <div class="stat"><div class="num">${sum.units}</div><div class="lbl">إجمالي القطع</div></div>
        <div class="stat amber"><div class="num">${sum.low}</div><div class="lbl">مخزون منخفض</div></div>
        <div class="stat red"><div class="num">${sum.out}</div><div class="lbl">أصناف نافدة</div></div>
        <div class="stat amber"><div class="num">${sum.expiring}</div><div class="lbl">أصناف تنتهي قريبًا</div></div>
        <div class="stat red"><div class="num">${sum.expired}</div><div class="lbl">أصناف منتهية</div></div>
      </div>
      <div class="card">
        <div class="toolbar">
          <input id="f-inv-q" placeholder="ابحث بالاسم أو الرمز" value="${esc(INV.q)}" style="min-width:200px">
          <select id="f-inv-status">${opts}</select>
          <input id="f-inv-days" type="number" min="0" max="365" value="${INV.days}"
                 placeholder="أيام قرب الانتهاء (0–365)" style="width:140px">
          <button class="btn" onclick="loadInventory()">تطبيق</button>
          <button class="btn ghost" onclick="clearInv()">مسح</button>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/pdf','inventory_report.pdf')">📄 تقرير المخزون PDF</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/csv?section=inventory','inventory_items.csv')">⬇️ مخزون CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/inventory/labels','med_labels.pdf')">🏷️ ملصقات الكل</button>` : ''}
          </div>
        </div>
        ${medForm}
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>الرمز</th><th>الاسم</th><th>الكمية</th><th>الحالة</th><th>السعر</th><th>القيمة</th><th>حد التنبيه</th><th>الانتهاء</th><th></th></tr></thead>
          <tbody>${items.map(m => `<tr>
            <td>${m.id}</td><td>${esc(m.code)}</td><td><strong>${esc(m.name)}</strong></td>
            <td>${m.quantity} ${esc(m.unit)}</td>
            <td><span class="pill ${stPill[m.status] || 'partial'}">${stLbl[m.status] || m.status}</span></td>
            <td>${m.price.toLocaleString()} ر.س</td>
            <td>${m.value.toLocaleString()} ر.س</td>
            <td>${m.min_quantity}</td>
            <td>${m.expiry_date ? fmtDate(m.expiry_date) : '—'}${(m.status === 'expiring' || m.status === 'expired') && m.days_to_expiry !== null ? ` <small title="أيام متبقية للانتهاء">⏱ ${m.days_to_expiry}</small>` : ''}</td>
            <td class="actions">
              ${isAdmin() ? `<button class="btn sm ghost" onclick="restock(${m.id})">📦 توريد</button>` : ''}
              ${isAdmin() ? `<button class="btn sm ghost" onclick="download('/inventory/labels?ids=${m.id}','label_${m.code}.pdf')">🏷️ ملصق</button>` : ''}
              ${isAdmin() ? `<button class="btn sm ghost" onclick="adjustStock(${m.id})">🧮 جرد</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('medications',${m.id},'inventory')">حذف</button>` : ''}
            </td>
          </tr>`).join('') || '<tr><td colspan="10" class="empty">لا توجد أصناف مطابقة</td></tr>'}</tbody>
        </table></div>
      </div>
      <div class="card">
        <h3>حركات المخزون (${moves.length})</h3>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>التاريخ</th><th>الدواء</th><th>نوع الحركة</th><th>التغير</th><th>الرصيد بعد الحركة</th><th>ملاحظة</th><th>المستخدم</th></tr></thead>
          <tbody>${moves.map(mv => `<tr>
            <td>${mv.id}</td><td>${fmtDate(mv.created_at)}</td>
            <td>${esc(mv.medication_name)}</td>
            <td><span class="pill ${mvPill[mv.type] || 'partial'}">${mvLbl[mv.type] || mv.type}</span></td>
            <td style="color:${mv.change > 0 ? '#155724' : '#721c24'};font-weight:700">${mv.change > 0 ? '+' : ''}${mv.change}</td>
            <td>${mv.quantity_after}</td>
            <td>${esc(mv.note || '-')}</td>
            <td>${esc(mv.made_by || '-')}</td>
          </tr>`).join('') || '<tr><td colspan="8" class="empty">لا حركات مخزون بعد</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- تبويب «المبيعات»: السجل + الفلاتر + التسديد --- */
  async sales(main) {
    const f = ACC;
    const p = periodRange(f.period);
    const q = new URLSearchParams();
    if (p.from) { q.set('from_date', p.from); q.set('to_date', p.to); }
    if (f.method) q.set('payment_method', f.method);
    if (f.status) q.set('status', f.status);
    if (f.patient) q.set('patient_id', f.patient);
    if (f.staff) q.set('staff', f.staff);
    /* جدول المبيعات فقط — الملخّص والمنحنى في تبويب «نظرة عامة» */
    const sales = await api('/accounts/sales' + (q.toString() ? '?' + q.toString() : ''));
    ACC_ROWS = sales;
    const unpaidCount = sales.filter(x => x.status !== 'PAID').length;
    main.innerHTML = `
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">سجل المبيعات (${sales.length})</h3>
          <input id="f-acc-period" placeholder="YYYY-MM (كل الفترات)" value="${esc(f.period || '')}" style="max-width:170px">
          <select id="f-acc-method">
            <option value="">كل طرق الدفع</option>
            <option value="cash" ${f.method === 'cash' ? 'selected' : ''}>نقدًا</option>
            <option value="card" ${f.method === 'card' ? 'selected' : ''}>بطاقة</option>
            <option value="insurance" ${f.method === 'insurance' ? 'selected' : ''}>تأمين</option>
          </select>
          <select id="f-acc-status">
            <option value="">كل الحالات</option>
            <option value="UNPAID" ${f.status === 'UNPAID' ? 'selected' : ''}>غير مدفوع</option>
            <option value="PARTIAL" ${f.status === 'PARTIAL' ? 'selected' : ''}>مدفوع جزئيًا</option>
            <option value="PAID" ${f.status === 'PAID' ? 'selected' : ''}>مدفوع</option>
          </select>
          <input id="f-acc-patient" type="number" min="1" placeholder="رقم المريض" value="${esc(f.patient || '')}" style="max-width:130px">
          <input id="f-acc-staff" placeholder="صرفه…" value="${esc(f.staff || '')}" style="max-width:140px">
          <button class="btn" onclick="loadAccounts()">تطبيق</button>
          <button class="btn ghost" onclick="clearAccounts()">مسح</button>
          ${unpaidCount ? `<button class="btn success" onclick="payAll()">💰 سدّد الكل (${unpaidCount})</button>` : ''}
        </div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الدواء</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th>المدفوع</th><th>المتبقي</th><th>الطريقة</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${sales.map(s => {
            const rest = Math.max(0, Math.round((s.total_price - s.paid_amount) * 100) / 100);
            return `<tr>
            <td>${s.id}</td><td>${fmtDate(s.created_at)}</td>
            <td>${esc(s.patient ? s.patient.full_name : '#' + s.patient_id)}</td>
            <td>${esc(s.medication ? s.medication.name : '#' + s.medication_id)}</td>
            <td>${s.quantity}</td>
            <td>${s.unit_price.toLocaleString()} ر.س</td>
            <td><strong>${s.total_price.toLocaleString()} ر.س</strong></td>
            <td>${s.paid_amount.toLocaleString()} ر.س</td>
            <td style="color:${rest > 0 ? '#dc3545' : '#28a745'}">${rest.toLocaleString()} ر.س</td>
            <td>${s.payment_method === 'card' ? 'بطاقة' : (s.payment_method === 'insurance' ? 'تأمين' : 'نقدًا')}</td>
            <td>${s.status === 'PAID'
              ? `<span class="pill paid">مدفوع</span>`
              : (s.status === 'PARTIAL'
                ? `<span class="pill partial">مدفوع جزئيًا</span>`
                : `<span class="pill unpaid">غير مدفوع</span>`)}</td>
            <td class="actions">
              ${s.status !== 'PAID'
                ? `<button class="btn sm success" onclick="pay(${s.id})">💰 تسديد</button> ` : ''}
              <button class="btn sm ghost" onclick="openReceipt(${s.id})">🧾 إيصال</button>
            </td>
          </tr>`; }).join('') || '<tr><td colspan="12" class="empty">لا توجد مبيعات في هذه الفترة</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- تبويب «نظرة عامة» (قسم الحسابات): الملخّص المالي + المنحنى + طرق الدفع --- */
  async accounts(main) {
    const f = ACC;
    const p = periodRange(f.period);
    const periodQ = f.period ? '?period=' + encodeURIComponent(f.period)
      : (p.from ? '?from_date=' + p.from + '&to_date=' + encodeURIComponent(p.to) : '');
    const [sum, debtors, rev] = await Promise.all([
      api('/accounts/summary' + periodQ),
      api('/accounts/debtors' + periodQ),
      api('/accounts/revenue' + (periodQ ? periodQ + '&group=' + accGroup : '?group=' + accGroup))]);
    const pm = Object.entries(sum.by_payment_method || {});
    const outstanding = sum.total_outstanding || 0;
    const totalDues = debtors.reduce((a, d) => a + d.outstanding, 0);
    const maxRev = Math.max(1, ...rev.map(r => r.sales));
    main.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="num">${sum.total_sales.toLocaleString()} ر.س</div><div class="lbl">إجمالي المبيعات</div></div>
        <div class="stat green"><div class="num">${sum.total_paid.toLocaleString()} ر.س</div><div class="lbl">المحصّل</div></div>
        <div class="stat red"><div class="num">${outstanding.toLocaleString()} ر.س</div><div class="lbl">المتبقي (مدين)</div></div>
        <div class="stat amber"><div class="num">${sum.count}</div><div class="lbl">عدد العمليات</div></div>
        <div class="stat"><div class="num">${debtors.length}</div><div class="lbl">عدد المدينين</div></div>
        <div class="stat red"><div class="num">${totalDues.toLocaleString()} ر.س</div><div class="lbl">مستحقات المدينين</div></div>
      </div>
      <div class="card">
        <div class="toolbar" style="margin-bottom:6px">
          <h3 style="margin:0">📈 منحنى الإيراد (${rev.length} ${rev.length && rev[0] && rev[0].date.length === 7 ? 'شهرًا' : 'يومًا'})</h3>
          <button class="btn ghost sm" onclick="setAccGroup('day')" ${accGroup === 'day' ? 'disabled' : ''}>يومي</button>
          <button class="btn ghost sm" onclick="setAccGroup('month')" ${accGroup === 'month' ? 'disabled' : ''}>شهري</button>
          ${isAdmin() ? `<button class="btn ghost sm" onclick="downloadAccounts('pdf')">📄 تقرير المبيعات PDF</button>
            <button class="btn ghost sm" onclick="downloadAccounts('csv')">⬇️ تقرير المبيعات CSV</button>` : ''}
        </div>
        <div class="bars">
          ${rev.length ? rev.map(r => `
            <div class="bar-wrap" title="${r.date}: ${r.sales.toLocaleString()} ر.س (${r.count} عملية)">
              <div class="val">${Math.round(r.sales)}</div>
              <div class="bar" style="height:${Math.max(4, Math.round(r.sales / maxRev * 110))}px;
                background:linear-gradient(180deg,#28a745,#85ce8f)"></div>
              <div class="lbl">${accGroup === 'month' ? r.date : r.date.slice(5)}</div>
            </div>`).join('') : '<div class="empty">لا يوجد إيراد في هذه الفترة</div>'}
        </div>
      </div>
      ${pm.length ? `<div class="card"><h3>توزيع طرق الدفع</h3>
        <div class="toolbar">${pm.map(([k, v]) =>
          `<span class="pill ${k === 'cash' ? 'paid' : (k === 'card' ? 'completed' : 'in_progress')}">${k === 'cash' ? 'نقدًا' : (k === 'card' ? 'بطاقة' : 'تأمين')}: ${Number(v).toLocaleString()} ر.س</span>`).join('')}</div>
      </div>` : ''}
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">🔗 أقسام مرتبطة</h3>
          <button class="btn sm" onclick="setAccTab('sales')">🛒 سجل المبيعات</button>
          <button class="btn sm" onclick="setAccTab('debtors')">🧾 المدينون</button>
          <button class="btn sm ghost" onclick="setAccTab('ledger')">📒 الدفتر العام</button>
          <button class="btn sm ghost" onclick="setAccTab('reports')">📄 التقارير</button>
        </div>
      </div>`;
  },

  /* --- تبويب «المدينون»: كشف حساب المريض + ذمم المرضى --- */
  async debtors(main) {
    const f = ACC;
    const p = periodRange(f.period);
    const periodQ = f.period ? '?period=' + encodeURIComponent(f.period)
      : (p.from ? '?from_date=' + p.from + '&to_date=' + encodeURIComponent(p.to) : '');
    const debtors = await api('/accounts/debtors' + periodQ);
    const totalDues = debtors.reduce((a, d) => a + d.outstanding, 0);
    main.innerHTML = `
      <div class="card">
        <div class="toolbar">
          <h3 style="margin:0">🧾 كشف حساب مريض</h3>
          <input id="f-stmt-patient" type="number" min="1" placeholder="رقم المريض" style="max-width:150px">
          <button class="btn" onclick="showStatement()">عرض الكشف</button>
        </div>
        <div id="stmt-out"><div class="empty">أدخل رقم المريض لعرض كشف حسابه (مبيعات + فواتير + الرصيد)</div></div>
      </div>
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">🧾 المدينون (${debtors.length})</h3>
          <span class="pill unpaid">إجمالي المستحقات: ${totalDues.toLocaleString()} ر.س</span></div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>المريض</th><th>عمليات غير مسدّدة</th><th>إجمالي مستحقاتهم</th><th>مدفوع</th><th>المتبقي</th><th></th></tr></thead>
          <tbody>${debtors.map(d => `<tr>
            <td><strong>${esc(d.full_name)}</strong> <span style="color:#999">#${d.patient_id}</span></td>
            <td>${d.operations}</td>
            <td>${d.total.toLocaleString()} ر.س</td>
            <td style="color:#28a745">${d.paid.toLocaleString()} ر.س</td>
            <td style="color:#dc3545;font-weight:bold">${d.outstanding.toLocaleString()} ر.س</td>
            <td class="actions"><button class="btn sm ghost"
              onclick="document.getElementById('f-stmt-patient').value=${d.patient_id};showStatement()">🧾 كشف حساب</button></td>
          </tr>`).join('') || '<tr><td colspan="6" class="empty">✅ لا يوجد مدينون — كل المبالغ مسدّدة</td></tr>'}</tbody>
          ${debtors.length ? `<tfoot><tr>
            <td><strong>الإجمالي</strong></td>
            <td>${debtors.reduce((a, d) => a + d.operations, 0)}</td>
            <td><strong>${debtors.reduce((a, d) => a + d.total, 0).toLocaleString()} ر.س</strong></td>
            <td style="color:#28a745">${debtors.reduce((a, d) => a + d.paid, 0).toLocaleString()} ر.س</td>
            <td style="color:#dc3545;font-weight:bold">${totalDues.toLocaleString()} ر.س</td>
            <td></td>
          </tr></tfoot>` : ''}
        </table></div>
      </div>`;
  },

  /* --- تبويب «الدفتر العام»: القيود ودليل الحسابات وميزان المراجعة --- */
  async ledger(main) {
    main.innerHTML = '';
    await renderGeneralLedger(main);
  },

  /* --- تبويب «التقارير»: مركز تنزيل تقارير المحاسبة وما يتصل بها --- */
  async reports(main) {
    main.innerHTML = `
      <div class="card">
        <h3>💰 التقارير المالية</h3>
        <div class="toolbar">
          <input id="f-rep-patient" type="number" min="1" placeholder="رقم المريض" style="max-width:150px">
          <button class="btn" onclick="statementPdf()">⬇️ كشف حساب مريض PDF</button>
          ${isAdmin() ? `<button class="btn ghost" onclick="downloadAccounts('pdf')">📄 تقرير المبيعات PDF</button>
          <button class="btn ghost" onclick="downloadAccounts('csv')">⬇️ تقرير المبيعات CSV</button>
          <button class="btn ghost" onclick="downloadReport()">📊 التقرير الإحصائي PDF</button>` : ''}
        </div>
        <p style="margin:10px 0 0;color:#7a8699;font-size:13px">
          تُصدَّر التقارير بلغة الواجهة الحالية، ويستهدف تقرير المبيعات الفترة المختارة في تبويب المبيعات.</p>
      </div>
      <div class="card">
        <h3>💵 الرواتب</h3>
        <div class="toolbar">
          <input id="f-rpp" placeholder="YYYY-MM (كل الفترات)" style="max-width:170px">
          <button class="btn ghost" onclick="downloadPayroll('pdf')">📄 كشف الرواتب PDF</button>
          <button class="btn ghost" onclick="downloadPayroll('csv')">⬇️ كشف الرواتب CSV</button>
        </div>
      </div>
      <div class="card">
        <h3>🏥 تقارير التشغيل المرتبطة</h3>
        <div class="toolbar">
          ${isAdmin() || isDoctor() ? `<button class="btn ghost" onclick="download('/reports/lab/pdf','lab_report.pdf')">📄 تقرير المختبر PDF</button>
          <button class="btn ghost" onclick="download('/reports/lab/csv','lab_orders.csv')">⬇️ طلبات المختبر CSV</button>` : ''}
          ${isAdmin() ? `<button class="btn ghost" onclick="download('/reports/pharmacy/pdf','pharmacy_report.pdf')">📄 تقرير الصيدلية PDF</button>
          <button class="btn ghost" onclick="download('/reports/pharmacy/stats/pdf','pharmacy_stats.pdf')">📊 إحصاءات الصيدلية PDF</button>` : ''}
        </div>
      </div>`;
  },

  /* --- الرواتب --- */
  async payroll(main) {
    if (!isAdmin()) { main.innerHTML = '<div class="empty">🔒 هذه الصفحة متاحة للمدير فقط</div>'; return; }
    const [rows, staff] = await Promise.all([api('/payroll/'), api('/staff/')]);
    const thisMonth = new Date().toISOString().slice(0, 7);
    main.innerHTML = `
      <div class="card">
        <div class="toolbar"><h3 style="margin:0">كشف الرواتب (${rows.length})</h3>
          <input id="f-rpp" placeholder="YYYY-MM (كل الفترات)" style="max-width:180px">
          <button class="btn ghost" onclick="downloadPayroll('pdf')">📄 كشف الرواتب PDF</button>
          <button class="btn ghost" onclick="downloadPayroll('csv')">⬇️ كشف الرواتب CSV</button>
        </div>
        <details class="addbox"><summary>➕ إضافة قيد راتب</summary>
        <div class="form-grid">
          <div class="field"><label>الموظف *</label><select id="f-staff">
            ${staff.map(s => `<option value="${s.id}" data-sal="${s.salary || 0}">${esc(s.full_name)} — ${esc(s.position)}</option>`).join('')}</select></div>
          <div class="field"><label>الفترة *</label><input id="f-period" placeholder="YYYY-MM" value="${thisMonth}"></div>
          <div class="field"><label>الأساسي (ر.س) *</label><input id="f-base" type="number" step="0.01" min="0"></div>
          <div class="field"><label>البدلات</label><input id="f-bonus" type="number" step="0.01" min="0" value="0"></div>
          <div class="field"><label>الاستقطاعات</label><input id="f-ded" type="number" step="0.01" min="0" value="0"></div>
          <div class="field"><label>ملاحظات</label><input id="f-pnotes"></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="addPayroll()">حفظ القيد</button>
        </details>
        <div class="toolbar"><input placeholder="🔍 بحث…" oninput="filterTable('tbl', this.value)"></div>
        <div style="overflow-x:auto"><table id="tbl">
          <thead><tr><th>#</th><th>الفترة</th><th>الموظف</th><th>الأساسي</th><th>بدلات</th><th>استقطاعات</th><th>الصافي</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${rows.map(r => `<tr>
            <td>${r.id}</td><td><strong>${esc(r.period)}</strong></td>
            <td>${esc(r.staff ? r.staff.full_name : '#' + r.staff_id)}</td>
            <td>${r.base_salary.toLocaleString()}</td><td>${r.bonus.toLocaleString()}</td>
            <td>${r.deduction.toLocaleString()}</td>
            <td><strong style="color:#2c7be5">${r.net.toLocaleString()} ر.س</strong></td>
            <td>${r.status === 'paid'
              ? `<span class="pill paid">مصروف ${r.paid_at ? '· ' + fmtDate(r.paid_at) : ''}</span>`
              : `<span class="pill unpaid">غير مصروف</span>`}</td>
            <td class="actions">
              ${r.status !== 'paid' ? `<button class="btn sm success" onclick="payPayroll(${r.id})">💵 صرف</button>` : ''}
              <button class="btn sm danger" onclick="del('payroll',${r.id},'hr')">حذف</button>
            </td>
          </tr>`).join('') || '<tr><td colspan="9" class="empty">لا قيود رواتب</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- سجل التدقيق --- */
  async audit(main) {
    if (!isAdmin()) { main.innerHTML = '<div class="empty">🔒 هذه الصفحة متاحة للمدير فقط</div>'; return; }
    const [rows, st] = await Promise.all([
      api('/audit-logs/?limit=200'), api('/audit-logs/stats')]);
    const bm = st.by_method || {};
    const lf = st.login_failures || { total: 0, last_24h: 0, recent: [] };
    const sec = (title, items, head, row) => !items || !items.length ? '' : `
      <div class="card"><h3>${title}</h3><div style="overflow-x:auto"><table>
        <thead><tr>${head}</tr></thead><tbody>${items.map(row).join('')}</tbody>
      </table></div></div>`;
    main.innerHTML = `
      <div class="card">
        <h3>📈 ملخّص استخدام النظام (آخر ${st.window_days} يومًا)</h3>
        <div class="toolbar" style="margin-top:12px">
          <span class="pill confirmed">الإجمالي: ${st.total}</span>
          <span class="pill pending">الفترة: ${st.recent}</span>
          ${Object.entries(bm).map(([m, c]) => `<span class="pill ${m === 'DELETE' ? 'cancelled' : (m === 'POST' ? 'confirmed' : 'pending')}">${m}: ${c}</span>`).join('')}
        </div>
      </div>
      ${sec('👥 أكثر المستخدمين نشاطًا', st.top_users,
            '<th>المستخدم</th><th>العمليات</th>',
            u => `<tr><td>${esc(u.username)}</td><td>${u.count}</td></tr>`)}
      ${sec('🛣️ أكثر المسارات طلبًا', st.top_paths,
            '<th>المسار</th><th>الطلبات</th>',
            p => `<tr><td style="direction:ltr;text-align:left">${esc(p.path)}</td><td>${p.count}</td></tr>`)}
      ${sec('⚠️ أخطاء آخر الفترة', st.recent_errors,
            '<th>الوقت</th><th>الطريقة</th><th>المسار</th><th>الحالة</th>',
            e => `<tr><td>${esc(e.time)}</td><td>${e.method}</td><td style="direction:ltr;text-align:left">${esc(e.path)}</td><td><span class="pill cancelled">${e.status_code}</span></td></tr>`)}
      <div class="card">
        <h3>🔒 محاولات الدخول الفاشلة</h3>
        <div class="toolbar" style="margin-top:12px">
          <span class="pill cancelled">الإجمالي: ${lf.total}</span>
          <span class="pill pending">آخر 24 ساعة: ${lf.last_24h}</span>
        </div>
        ${lf.recent.length ? `<div style="overflow-x:auto"><table>
          <thead><tr><th>الوقت</th><th>المستخدم</th><th>الحالة</th></tr></thead>
          <tbody>${lf.recent.map(r => `<tr>
            <td>${esc(r.time)}</td><td>${esc(r.username)}</td>
            <td><span class="pill cancelled">${r.status_code}</span></td>
          </tr>`).join('')}</tbody></table></div>` : '<div class="empty">لا توجد محاولات فاشلة</div>'}
      </div>
      <div class="card">
        <h3>سجل التدقيق — العمليات التعديلية (${rows.length})</h3>
        <div class="toolbar">
          <input placeholder="🔍 بحث بالمستخدم أو المسار…" oninput="filterTable('tbl', this.value)">
          <button class="btn ghost" onclick="navigate('audit')">🔄 تحديث</button>
        </div>
        <div style="overflow-x:auto"><table id="tbl">
          <thead><tr><th>#</th><th>الوقت</th><th>المستخدم</th><th>الطريقة</th><th>المسار</th><th>الحالة</th></tr></thead>
          <tbody>${rows.map(l => `<tr>
            <td>${l.id}</td><td>${fmtDate(l.created_at)}</td>
            <td>${esc(l.username || '—')}</td>
            <td><span class="pill ${l.method === 'DELETE' ? 'cancelled' : (l.method === 'POST' ? 'confirmed' : 'pending')}">${l.method}</span></td>
            <td style="direction:ltr;text-align:left">${esc(l.path)}</td>
            <td>${l.status_code ? `<span class="pill ${l.status_code < 400 ? 'completed' : 'cancelled'}">${l.status_code}</span>` : '—'}</td>
          </tr>`).join('') || '<tr><td colspan="6" class="empty">لا توجد عمليات بعد</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- إدارة المستخدمين --- */
  async users(main) {
    if (!isAdmin()) { main.innerHTML = '<div class="empty">🔒 هذه الصفحة متاحة للمدير فقط</div>'; return; }
    const users = await api('/auth/users');
    const roles = [['admin', 'مدير النظام'], ['doctor', 'طبيب'], ['موظف استقبال', 'موظف استقبال']];
    main.innerHTML = `
      <div class="card">
        <h3>المستخدمون (${users.length})</h3>
        <details class="addbox"><summary>➕ إضافة مستخدم جديد</summary>
        <div class="form-grid">
          <div class="field"><label>اسم المستخدم</label><input id="u-username"></div>
          <div class="field"><label>الاسم الكامل</label><input id="u-fullname"></div>
          <div class="field"><label>البريد الإلكتروني</label><input id="u-email" type="email"></div>
          <div class="field"><label>الصلاحية</label><select id="u-role">
            ${roles.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></div>
          <div class="field"><label>كلمة المرور</label><input id="u-pass" type="password"></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="saveUser()">إنشاء الحساب</button>
        </details>
        <div style="overflow-x:auto; margin-top:18px"><table>
          <thead><tr><th>#</th><th>اسم المستخدم</th><th>الاسم الكامل</th><th>البريد الإلكتروني</th>
            <th>الصلاحية</th><th>الحالة</th><th></th></tr></thead>
          <tbody>${users.map(u => `<tr>
            <td>${u.id}</td><td>${esc(u.username)}</td><td>${esc(u.full_name)}</td>
            <td style="direction:ltr;text-align:left">${esc(u.email)}</td>
            <td>
              <select onchange="setRole(${u.id}, this.value)" ${u.id === USER.id ? 'disabled' : ''}>
                ${roles.map(([v, t]) => `<option value="${esc(v)}" ${u.role === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}
              </select>
            </td>
            <td>${u.is_active ? '<span class="pill completed">نشط</span>' : '<span class="pill cancelled">معطّل</span>'}</td>
            <td class="actions">
              <button class="btn sm ${u.is_active ? 'danger' : 'success'}" onclick="toggleUser(${u.id})">${u.is_active ? 'تعطيل' : 'تفعيل'}</button>
            </td>
          </tr>`).join('')}</tbody>
        </table></div>
      </div>`;
  },

  /* --- النسخ الاحتياطي --- */
  async backup(main) {
    if (!isAdmin()) { main.innerHTML = '<div class="empty">🔒 هذه الصفحة متاحة للمدير فقط</div>'; return; }
    const [rows, st] = await Promise.all([
      api('/backup'), api('/backup/status').catch(() => null)]);
    main.innerHTML = `
      <div class="card">
        <h3>النسخ الاحتياطي لقاعدة البيانات</h3>
        <button class="btn success" onclick="makeBackup()">💾 إنشاء نسخة احتياطية الآن</button>
        <button class="btn ghost" onclick="verifyBackups()">🩺 فحص السلامة</button>
        <button class="btn ghost" onclick="pruneNow()">🧹 تنظيف النسخ حسب السياسة</button>
        ${st ? `<p style="margin:12px 0 0; color:#64748b; font-size:13px">📁 ${st.files} ملف (${st.total_mb} م.ب) · الاحتفاظ بآخر ${st.retention} من كل نوع · حرّ ${st.disk_free_mb ?? '—'} م.ب</p>` : ''}
        <div style="overflow-x:auto; margin-top:18px"><table>
          <thead><tr><th>الملف</th><th>الحجم (KB)</th><th>تاريخ الإنشاء</th><th></th><th></th></tr></thead>
          <tbody>${rows.map(f => `<tr>
            <td><strong>${esc(f.file)}</strong></td><td>${f.size_kb}</td><td>${fmtDate(f.created_at)}</td>
            <td><button class="btn sm ghost" onclick="download('/backup/${encodeURIComponent(f.file)}','${esc(f.file)}')">⬇️ تنزيل</button></td>
            <td>${f.restorable ? `<button class="btn sm danger" onclick="restoreBackup('${esc(f.file)}')">♻️ استعادة</button>` : ''}</td>
          </tr>`).join('') || '<tr><td colspan="5" class="empty">لا توجد نسخ بعد</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- شاشة المحاسبة: شريط التبويبات + حاوية المحتوى --- */
  async accounting(main) {
    main.innerHTML = `
      <div class="tabbar" id="acc-tabs" role="tablist">
        ${ACC_TAB_LIST.map(([k, label]) => `<button type="button" role="tab"
          class="tab${k === ACC_TAB ? ' active' : ''}" data-tab="${k}"
          aria-selected="${k === ACC_TAB}" onclick="setAccTab('${k}')">${tr(label)}</button>`).join('')}
      </div>
      <div id="acc-body"><div class="empty">جارٍ التحميل…</div></div>`;
    await setAccTab(ACC_TAB);
  },

  /* --- الرعاية والتشغيل --- */
  clinical(main) { return renderOps(main, 'clinical'); },
  support(main) { return renderOps(main, 'support'); },
  governance(main) { return renderOps(main, 'governance'); },

  /* --- لوحة التحكم --- */
  async dashboard(main) {
    const s = await api('/dashboard/stats');
    s.operations = await api('/clinical/overview');
    const statuses = s.appointments_by_status || {};
    const maxVal = Math.max(1, ...Object.values(statuses));
    const stLabels = { pending: 'معلّقة', confirmed: 'مؤكدة', cancelled: 'ملغاة', completed: 'مكتملة' };
    main.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="num">${s.total_patients}</div><div class="lbl">المرضى</div></div>
        <div class="stat green"><div class="num">${s.total_doctors}</div><div class="lbl">الأطباء</div></div>
        <div class="stat amber"><div class="num">${s.appointments_today}</div><div class="lbl">مواعيد اليوم</div></div>
        <div class="stat red"><div class="num">${s.pending_appointments}</div><div class="lbl">مواعيد معلّقة</div></div>
        <div class="stat"><div class="num">${s.beds_occupied}/${s.beds_total}</div><div class="lbl">أسرّة مشغولة</div></div>
        <div class="stat green"><div class="num">${s.revenue_paid.toLocaleString()}</div><div class="lbl">إيرادات محصّلة (ر.س)</div></div>
        <div class="stat red"><div class="num">${s.revenue_unpaid.toLocaleString()}</div><div class="lbl">مستحقات غير محصّلة</div></div>
        <div class="stat"><div class="num">${s.total_departments}</div><div class="lbl">الأقسام</div></div>
        <div class="stat amber"><div class="num">${s.operations.nursing_pending || 0}</div><div class="lbl">مهام تمريض مفتوحة</div></div>
        <div class="stat red"><div class="num">${s.operations.surgeries_active || 0}</div><div class="lbl">عمليات نشطة</div></div>
        <div class="stat"><div class="num">${s.operations.safety_open || 0}</div><div class="lbl">حوادث تحتاج متابعة</div></div>
        <div class="stat green"><div class="num">${s.operations.maintenance_open || 0}</div><div class="lbl">أوامر صيانة</div></div>
      </div>
      <div class="card">
        <h3>توزيع المواعيد حسب الحالة</h3>
        ${isAdmin() || isDoctor() ? `<div style="margin-bottom:14px"><button class="btn ghost" onclick="downloadReport()">📄 تحميل تقرير PDF</button></div>` : ''}
        <div class="bars">
          ${Object.keys(statuses).length ? Object.entries(statuses).map(([k, v]) => `
            <div class="bar-wrap">
              <div class="val">${v}</div>
              <div class="bar" style="height:${Math.round(v / maxVal * 110)}px"></div>
              <div class="lbl">${stLabels[k] || k}</div>
            </div>`).join('') : '<div class="empty">لا توجد مواعيد بعد</div>'}
        </div>
      </div>`;
  },

  /* --- المرضى: بحث على الخادم + فلاتر + ترقيم + أعمدة محسوبة --- */
  async patients(main) {
    const st = getPatientListState();
    const qs = new URLSearchParams();
    if (st.search) qs.set('search', st.search);
    if (st.blood) qs.set('blood_type', st.blood);
    if (st.alert) qs.set('alert', 'has');
    if (st.sort) {
      qs.set('sort', st.sort);
      qs.set('dir', st.sortDir);      /* بلا الاتجاه كان السهم يكذب على المستخدم */
    }
    qs.set('limit', String(PAGE_SIZE));
    qs.set('offset', String(st.page * PAGE_SIZE));

    let rows = [], total = st.total;
    try {
      const res = await fetch(API + '/patients/?' + qs.toString(), {
        headers: { 'Authorization': 'Bearer ' + TOKEN } });
      if (!res.ok) throw new Error('تعذّر تحميل القائمة');
      rows = await res.json();
      total = Number(res.headers.get('X-Total-Count') || rows.length);
    } catch (e) { main.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`; return; }

    setPatientListState({ total });
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const from = total ? st.page * PAGE_SIZE + 1 : 0;
    const to = Math.min(total, (st.page + 1) * PAGE_SIZE);
    const th = (key, label, extra = '') =>
      `<th class="${extra}" onclick="sortPatients('${key}')" title="اضغط للترتيب">${label}${
        st.sort === key ? (st.sortDir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`;
    const canAdd = isAdmin() || !isDoctor();
    const opt = (v, l, sel) => `<option value="${v}" ${sel ? 'selected' : ''}>${l}</option>`;

    main.innerHTML = `
      <div class="card">
        <h3>المرضى <span class="count-badge">${total}</span></h3>
        <div class="toolbar">
          <input id="q" placeholder="🔍 بحث بالاسم/الهاتف/الهوية/البريد…" value="${esc(st.search)}"
                 oninput="searchPatients(this.value)">
          <select id="flt-blood" onchange="filterPatients()">
            ${opt('', 'كل فصائل الدم', !st.blood)}
            ${['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-']
              .map(b => opt(b, b, st.blood === b)).join('')}
          </select>
          <label class="chk"><input type="checkbox" id="flt-alert" ${st.alert ? 'checked' : ''}
                 onchange="filterPatients()"> ⚠️ من له تحذير</label>
          ${st.search || st.blood || st.alert
            ? `<button class="btn ghost sm" onclick="resetPatients()">✖️ مسح الفلاتر</button>` : ''}
          <span style="flex:1"></span>
          <button class="btn ghost" onclick="download('/patients/export.csv','patients.csv')">⬆️ تصدير CSV</button>
          ${canAdd ? `<label class="btn ghost" style="cursor:pointer;margin:0">⬇️ استيراد CSV
            <input type="file" accept=".csv,text/csv" style="display:none" onchange="importPatients(this)"></label>` : ''}
        </div>
        ${canAdd ? patientAddForm() : ''}
        <div style="overflow-x:auto"><table id="tbl">
          <thead><tr>
            <th>#</th>
            ${th('name', 'المريض')}
            <th>العمر</th>
            <th>الهاتف</th>
            <th>الدم</th>
            <th>التأمين</th>
            <th>آخر زيارة</th>
            <th>الموعد القادم</th>
            <th title="يُحسب من الفواتير وصرف الصيدلية — الترتيب به غير مدعوم">المتبقي</th>
            <th></th>
          </tr></thead>
          <tbody>${rows.map(p => `<tr class="clickable" onclick="openPatientChart(${p.id})">
            <td>${p.id}</td>
            <td><strong>${esc(p.full_name)}</strong>
              ${p.has_alerts ? '<br><small class="warn-tag" title="حساسية أو تحذير طبي">⚠️ تحذير</small>' : ''}
              ${p.nationality ? `<br><small>${esc(p.nationality)}</small>` : ''}</td>
            <td>${p.age != null ? p.age + ' سنة' : '—'}</td>
            <td>${esc(p.phone)}</td>
            <td>${esc(p.blood_type || '—')}</td>
            <td>${p.insurer ? esc(p.insurer) +
              (p.insurance_grade ? `<br><small>${esc(p.insurance_grade)}${
                p.insurance_copay != null ? ' · تحمّل ' + p.insurance_copay + '%' : ''}</small>` : '')
              : '—'}</td>
            <td>${p.last_visit ? fmtDate(p.last_visit) : '—'}</td>
            <td>${p.upcoming ? `<span class="pill confirmed">${fmtDate(p.upcoming)}</span>` : '—'}</td>
            <td>${p.outstanding > 0
              ? `<b style="color:#dc3545">${p.outstanding.toLocaleString()}</b>` : '—'}</td>
            <td class="actions" onclick="event.stopPropagation()">
              <button class="btn sm primary" onclick="openPatientChart(${p.id})">🗂️ الملف</button>
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('patients',${p.id},'patients')">حذف</button>` : ''}
            </td>
          </tr>`).join('') || `<tr><td colspan="11" class="empty">${
            (st.search || st.blood || st.alert) ? 'لا نتائج مطابقة للفلاتر' : 'لا يوجد مرضى'}</td></tr>`}</tbody>
        </table></div>
        <div class="pager">
          <span>عرض ${from}–${to} من ${total}</span>
          <div class="actions">
            <button class="btn sm ghost" ${st.page === 0 ? 'disabled' : ''}
              onclick="gotoPatientPage(${st.page - 1})">◀ السابق</button>
            <span class="pill">${st.page + 1} / ${pages}</span>
            <button class="btn sm ghost" ${st.page >= pages - 1 ? 'disabled' : ''}
              onclick="gotoPatientPage(${st.page + 1})">التالي ▶</button>
          </div>
        </div>
      </div>`;
  },

  /* --- الأطباء --- */
  async doctors(main) {
    const [rows, depts, stats] = await Promise.all([
      api('/doctors/'), api('/departments/'),
      api('/doctors/stats').catch(() => null)]);
    DOCTORS_CACHE = rows; DOCTORS_DEPTS = depts;
    const form = isAdmin() ? `
      <details class="addbox"><summary>➕ إضافة طبيب جديد</summary>
      <div class="form-grid">
        <div class="field"><label>الاسم الكامل *</label><input id="f-name"></div>
        <div class="field"><label>التخصص *</label><input id="f-spec"></div>
        <div class="field"><label>رقم الترخيص *</label><input id="f-lic"></div>
        <div class="field"><label>الهاتف *</label><input id="f-phone"></div>
        <div class="field"><label>البريد الإلكتروني *</label><input id="f-email" type="email"></div>
        <div class="field"><label>العنوان</label><input id="f-addr"></div>
        <div class="field"><label>القسم</label><select id="f-dept"><option value="">—</option>
          ${depts.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addDoctor()">حفظ الطبيب</button>
      </details>` : '';
    const statCards = stats ? `
      <div class="stats" style="margin-bottom:16px">
        <div class="stat"><div class="num">${stats.total}</div><div class="lbl">إجمالي الأطباء</div></div>
        <div class="stat green"><div class="num">${stats.available}</div><div class="lbl">أطباء متاحون</div></div>
        <div class="stat amber"><div class="num">${stats.unavailable}</div><div class="lbl">غير متاحين</div></div>
        <div class="stat"><div class="num">${stats.specialties}</div><div class="lbl">تخصصات</div></div>
        <div class="stat"><div class="num">${stats.appointments}</div><div class="lbl">مواعيد مرتبطة</div></div>
      </div>` : '';
    const canToggle = d => isAdmin() || (isDoctor() && USER && d.email === USER.email);
    main.innerHTML = `
      ${statCards}
      <div class="card">
        <h3>الأطباء (${rows.length})</h3>
        <div class="toolbar">
          <input id="q" placeholder="🔍 بحث بالاسم/التخصص/الترخيص…" oninput="filterDoctors()">
          <select id="flt-dept" onchange="filterDoctors()"><option value="">كل الأقسام</option>
            ${depts.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}
            <option value="none">بدون قسم</option></select>
          <select id="flt-avail" onchange="filterDoctors()"><option value="">كل الحالات</option>
            <option value="1">✅ متاح</option><option value="0">⛔ غير متاح</option></select>
          <button class="btn ghost" onclick="doctorsPerformance()">📊 أداء الشهر</button>
        </div>
        ${form}
        <div style="overflow-x:auto"><table id="tbl">
          <thead><tr><th>#</th><th>الاسم</th><th>التخصص</th><th>الترخيص</th><th>الهاتف</th><th>القسم</th><th>متاح</th><th></th></tr></thead>
          <tbody>${rows.map(d => `<tr data-dept="${d.department_id == null ? 'none' : d.department_id}" data-avail="${d.is_available ? '1' : '0'}">
            <td>${d.id}</td><td><strong>${esc(d.full_name)}</strong></td><td>${esc(d.specialty)}</td>
            <td>${esc(d.license_number)}</td><td>${esc(d.phone)}</td>
            <td>${esc(d.department ? d.department.name : '-')}</td>
            <td>${d.is_available ? '✅' : '⛔'}</td>
            <td>
              ${isAdmin() ? `<button class="btn sm ghost" onclick="editDoctor(${d.id})">✏️ تعديل</button>` : ''}
              <button class="btn sm ghost" onclick="doctorReport(${d.id})">📈 تقرير</button>
              ${canToggle(d) ? `<button class="btn sm ghost" onclick="doctorSchedule(${d.id})" title="نوبات العمل">🗓️</button>` : ''}
              ${canToggle(d) ? `<button class="btn sm ghost" onclick="toggleDoctorAvail(${d.id},${d.is_available})">${d.is_available ? '⛔ تعطيل' : '✅ تمكين'}</button>` : ''}
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('doctors',${d.id},'doctors')">حذف</button>` : ''}
            </td>
          </tr>`).join('') || '<tr><td colspan="8" class="empty">لا يوجد أطباء</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- المواعيد --- */
  async appointments(main) {
    const [rows, patients, doctors] = await Promise.all([
      api('/appointments/'), api('/patients/'), api('/doctors/')]);
    CAL_MODE = false;
    main.innerHTML = `
      <div class="card">
        <h3>المواعيد (${rows.length})</h3>
        <div class="toolbar">
          <input type="date" id="flt-date" onchange="loadAppts()">
          <select id="flt-status" onchange="loadAppts()">
            <option value="">كل الحالات</option><option value="pending">معلّقة</option>
            <option value="confirmed">مؤكدة</option><option value="completed">مكتملة</option>
            <option value="cancelled">ملغاة</option>
          </select>
          <button class="btn ghost" id="cal-btn" onclick="toggleCal()">🗓️ تقويم</button>
        </div>
        <div id="cal-box" style="display:none;margin-top:12px"></div>
        <div id="queue-box" style="margin:12px 0"></div>
        <details class="addbox"><summary>➕ حجز موعد جديد</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-pat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>الطبيب *</label><select id="f-doc">
            ${doctors.map(d => `<option value="${d.id}">${esc(d.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>التاريخ والوقت *</label><input id="f-date" type="datetime-local"></div>
          <div class="field"><label>السبب</label><input id="f-reason"></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="addAppt()">حجز الموعد</button>
        </details>
        <div id="appt-table" style="overflow-x:auto"><table id="tbl">
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الطبيب</th><th>السبب</th><th>الحالة</th><th>الطابور</th><th></th></tr></thead>
          <tbody id="appt-body"></tbody>
        </table></div>
      </div>`;
    window._apptCache = { patients, doctors };
    await loadAppts();
  },

  /* --- السجلات الطبية --- */
  async records(main) {
    const [rows, patients, doctors, atts] = await Promise.all([
      api('/medical-records/'), api('/patients/'), api('/doctors/'), api('/attachments/')]);
    // مرفقات كل سجل
    const attMap = {};
    atts.forEach(a => { if (a.record_id) (attMap[a.record_id] = attMap[a.record_id] || []).push(a); });
    const fmtSize = b => b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.round(b / 1024) + ' KB';
    main.innerHTML = `
      <div class="card">
        <h3>السجلات الطبية (${rows.length})</h3>
        <details class="addbox"><summary>➕ إضافة سجل طبي</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-pat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          ${isDoctor() ? '' : `<div class="field"><label>الطبيب</label><select id="f-doc">
            <option value="">—</option>${doctors.map(d => `<option value="${d.id}">${esc(d.full_name)}</option>`).join('')}</select></div>`}
          <div class="field" style="grid-column:1/-1"><label>التشخيص *</label><input id="f-dx"></div>
          <div class="field" style="grid-column:1/-1"><label>الوصفة الطبية</label><textarea id="f-rx" rows="2"></textarea></div>
          <div class="field" style="grid-column:1/-1"><label>ملاحظات</label><textarea id="f-notes" rows="2"></textarea></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="addRecord()">حفظ السجل</button>
        </details>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الطبيب</th><th>التشخيص</th><th></th></tr></thead>
          <tbody>${rows.map(r => `
          <tr>
            <td>${r.id}</td><td>${fmtDate(r.created_at)}</td>
            <td>${esc(r.patient.full_name)}</td><td>${esc(r.doctor ? r.doctor.full_name : '-')}</td>
            <td>${esc(r.diagnosis)}</td>
            <td class="actions">
              ${(attMap[r.id] || []).length ? `<button class="btn sm ghost" onclick="toggleRecordAtts(${r.id})">📎 ${attMap[r.id].length}</button>` : ''}
              <button class="btn sm ghost" onclick="download('/medical-records/${r.id}/pdf','record_${r.id}.pdf')">📄 PDF</button>
              ${(isAdmin() || (isDoctor() && r.doctor && USER.email === r.doctor.email)) ? `<button class="btn sm danger" onclick="del('medical-records',${r.id},'records')">حذف</button>` : ''}
            </td>
          </tr>
          <tr id="att-row-${r.id}" style="display:none"><td colspan="6" style="background:#f8fafd">
            <strong>📎 مرفقات هذا السجل:</strong>
            ${(attMap[r.id] || []).map(a => `<div style="margin:6px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
              <span>${a.content_type.includes('image') ? '🖼️' : '📄'} ${esc(a.original_name)}</span>
              <small>(${fmtSize(a.size_bytes)})</small>
              <button class="btn sm ghost" onclick="previewAtt(${a.id})">👁️ معاينة</button>
              <button class="btn sm ghost" onclick="download('/attachments/${a.id}/file','${esc(a.original_name)}')">⬇️ تنزيل</button>
            </div>`).join('') || '<em>لا مرفقات</em>'}
          </td></tr>`).join('') || '<tr><td colspan="6" class="empty">لا توجد سجلات</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- الأقسام --- */
  async departments(main) {
    const rows = await api('/departments/');
    const form = isAdmin() ? `
      <details class="addbox"><summary>➕ إضافة قسم</summary>
      <div class="form-grid">
        <div class="field"><label>اسم القسم *</label><input id="f-name"></div>
        <div class="field"><label>الدور</label><input id="f-floor"></div>
        <div class="field"><label>الوصف</label><input id="f-desc"></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addDept()">حفظ القسم</button>
      </details>` : '';
    main.innerHTML = `
      <div class="card">
        <h3>الأقسام (${rows.length})</h3>
        ${form}
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>الاسم</th><th>الدور</th><th>الوصف</th><th>الأسرّة</th>${isAdmin() ? '<th></th>' : ''}</tr></thead>
          <tbody>${rows.map(d => `<tr>
            <td>${d.id}</td><td><strong>${esc(d.name)}</strong></td><td>${esc(d.floor || '-')}</td>
            <td>${esc(d.description || '-')}</td><td>${d.beds.length}</td>
            ${isAdmin() ? `<td><button class="btn sm danger" onclick="del('departments',${d.id},'departments')">حذف</button></td>` : ''}
          </tr>`).join('') || '<tr><td colspan="6" class="empty">لا توجد أقسام</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- الأسرّة --- */
  async beds(main) {
    const [rows, depts, patients] = await Promise.all([
      api('/beds/'), api('/departments/'), api('/patients/')]);
    const stLabel = { available: 'متاح', occupied: 'مشغول', maintenance: 'صيانة' };
    const form = isAdmin() ? `
      <details class="addbox"><summary>➕ إضافة سرير</summary>
      <div class="form-grid">
        <div class="field"><label>رقم السرير *</label><input id="f-num"></div>
        <div class="field"><label>القسم *</label><select id="f-dept">
          ${depts.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div>
      </div>
      <button class="btn success" style="margin-top:12px" onclick="addBed()">حفظ السرير</button>
      </details>` : '';
    main.innerHTML = `
      <div class="card">
        <h3>الأسرّة (${rows.length})</h3>
        ${form}
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>السرير</th><th>القسم</th><th>الحالة</th><th>المريض</th><th>إجراء</th>${isAdmin() ? '<th></th>' : ''}</tr></thead>
          <tbody>${rows.map(b => `<tr>
            <td>${b.id}</td><td><strong>${esc(b.bed_number)}</strong></td>
            <td>${esc(depts.find(d => d.id === b.department_id)?.name || '-')}</td>
            <td>${pill(b.status)}</td>
            <td>${esc(patients.find(p => p.id === b.patient_id)?.full_name || '—')}</td>
            <td>
              <select onchange="updateBed(${b.id}, this.value)" style="padding:5px;border-radius:6px;border:1px solid #ddd">
                ${Object.entries(stLabel).map(([k, v]) => `<option value="${k}" ${b.status === k ? 'selected' : ''}>${v}</option>`).join('')}
              </select>
            </td>
            ${isAdmin() ? `<td><button class="btn sm danger" onclick="del('beds',${b.id},'beds')">حذف</button></td>` : ''}
          </tr>`).join('') || '<tr><td colspan="7" class="empty">لا توجد أسرّة</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },

  /* --- الفواتير --- */
  async invoices(main) {
    const [rows, patients, appts, recs] = await Promise.all([
      api('/invoices/'), api('/patients/'), api('/appointments/'), api('/medical-records/')]);
    const stLabel = { unpaid: 'غير مدفوعة', paid: 'مدفوعة', partial: 'جزئية' };
    const optAppts = appts.map(a =>
      `<option value="${a.id}">#${a.id} — ${esc(a.patient.full_name)} — ${fmtDate(a.appointment_date)}</option>`).join('');
    const optRecs = recs.map(r =>
      `<option value="${r.id}">#${r.id} — ${esc(r.patient.full_name)} — ${esc(r.diagnosis)}</option>`).join('');
    main.innerHTML = `
      <div class="card">
        <h3>الفواتير (${rows.length})</h3>
        <div class="toolbar" style="margin-bottom:6px">
          <button class="btn ghost" onclick="download('/invoices/export.csv','invoices.csv')">⬆️ تصدير CSV</button>
        </div>
        <details class="addbox"><summary>➕ إنشاء فاتورة</summary>
        <div class="form-grid">
          <div class="field"><label>المريض *</label><select id="f-pat">
            ${patients.map(p => `<option value="${p.id}">${esc(p.full_name)}</option>`).join('')}</select></div>
          <div class="field"><label>المبلغ (ر.س) *</label><input id="f-amt" type="number" step="0.01" min="1"></div>
          <div class="field"><label>الخصم (ر.س)</label><input id="f-disc" type="number" step="0.01" min="0" value="0"></div>
          <div class="field"><label>الضريبة %</label><input id="f-tax" type="number" step="0.1" min="0" max="100" value="0"></div>
          <div class="field"><label>الحالة</label><select id="f-st">
            <option value="unpaid">غير مدفوعة</option><option value="paid">مدفوعة</option><option value="partial">جزئية</option></select></div>
          <div class="field"><label>الوصف *</label><input id="f-desc"></div>
          <div class="field"><label>🔗 ربط بموعد</label><select id="f-appt"><option value="">—</option>${optAppts}</select></div>
          <div class="field"><label>🔗 ربط بسجل طبي</label><select id="f-rec"><option value="">—</option>${optRecs}</select></div>
          <div class="field"><label>🏢 شركة التأمين</label><input id="f-ins" placeholder="اختياري — مطلوب للدفع بالتأمين"></div>
          <div class="field"><label>📄 رقم الوثيقة</label><input id="f-pol"></div>
        </div>
        <button class="btn success" style="margin-top:12px" onclick="addInvoice()">إنشاء الفاتورة</button>
        </details>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>#</th><th>التاريخ</th><th>المريض</th><th>الوصف</th><th>الإجمالي</th><th>الحالة</th><th>الدفع</th><th></th></tr></thead>
          <tbody>${rows.map(i => `<tr>
            <td>${i.id}${i.appointment_id ? ' 🔗' : ''}${i.record_id ? ' 📋' : ''}</td>
            <td>${fmtDate(i.created_at)}</td><td>${esc(i.patient.full_name)}</td>
            <td>${esc(i.description)}${i.insurer ? `<br><small>🏢 ${esc(i.insurer)}${i.policy_number ? ' — #' + esc(i.policy_number) : ''}</small>` : ''}</td>
            <td><strong>${(i.total != null ? i.total : i.amount).toLocaleString()} ر.س</strong>${(i.discount || i.tax_rate) ? `<br><small>أساسي ${i.amount.toLocaleString()}${i.discount ? ' − خصم ' + i.discount.toLocaleString() : ''}${i.tax_rate ? ' + ضريبة ' + i.tax_rate + '%' : ''}</small>` : ''}${i.paid_amount ? `<br><small style="color:#28a745">مدفوع ${i.paid_amount.toLocaleString()}</small>` : ''}</td>
            <td>${pill(i.status)}</td>
            <td>${i.paid_at ? `${esc(i.payment_method || '-')} · ${fmtDate(i.paid_at)}` : '—'}</td>
            <td class="actions">
              ${i.status !== 'paid' ? `<button class="btn sm success" onclick="payInvoice(${i.id})">💰 دفع</button>` : ''}
              <button class="btn sm ghost" onclick="printInvoice(${i.id})">🖨️ طباعة</button>
              <button class="btn sm ghost" onclick="download('/invoices/${i.id}/pdf','invoice_${i.id}.pdf')">📄 PDF</button>
              ${isAdmin() ? `<button class="btn sm danger" onclick="del('invoices',${i.id},'invoices')">حذف</button>` : ''}
            </td>
          </tr>`).join('') || '<tr><td colspan="8" class="empty">لا توجد فواتير</td></tr>'}</tbody>
        </table></div>
      </div>`;
  },
};

/* --- تقويم المواعيد الشهري --- */
let CAL_MODE = false, CAL_Y = null, CAL_M = null, CAL_DATA = [];
const CAL_MONTHS = {
  ar: ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس',
       'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'],
  en: ['January', 'February', 'March', 'April', 'May', 'June',
       'July', 'August', 'September', 'October', 'November', 'December'],
};
const CAL_DOW = {
  ar: ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'],
  en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
};

async function toggleCal() {
  CAL_MODE = !CAL_MODE;
  const cb = document.getElementById('cal-box');
  const tb = document.getElementById('appt-table');
  const qb = document.getElementById('queue-box');
  const btn = document.getElementById('cal-btn');
  if (!cb || !tb) return;
  if (CAL_MODE) {
    tb.style.display = 'none';
    if (qb) qb.style.display = 'none';
    cb.style.display = 'block';
    if (btn) btn.textContent = '📋 ' + tr('الجدول');
    if (CAL_Y === null) { const n = new Date(); CAL_Y = n.getFullYear(); CAL_M = n.getMonth(); }
    try {
      if (!CAL_DATA.length) CAL_DATA = await api('/appointments/');
      renderCalendar();
    } catch (e) { toast(e.message, true); }
  } else {
    tb.style.display = '';
    if (qb) qb.style.display = '';
    cb.style.display = 'none';
    if (btn) btn.textContent = '🗓️ ' + tr('تقويم');
  }
}

function calNav(step) {
  CAL_M += step;
  if (CAL_M < 0) { CAL_M = 11; CAL_Y--; }
  if (CAL_M > 11) { CAL_M = 0; CAL_Y++; }
  renderCalendar();
}

function renderCalendar() {
  const cb = document.getElementById('cal-box');
  if (!cb) return;
  const L = LANG === 'en' ? 'en' : 'ar';
  const months = CAL_MONTHS[L], dows = CAL_DOW[L];
  const first = new Date(CAL_Y, CAL_M, 1);
  const startDow = first.getDay();
  const daysIn = new Date(CAL_Y, CAL_M + 1, 0).getDate();
  const today = new Date();
  const byDay = {};
  CAL_DATA.forEach(a => {
    const d = new Date(a.appointment_date);
    if (isNaN(d.getTime())) return;
    if (d.getFullYear() !== CAL_Y || d.getMonth() !== CAL_M) return;
    const k = d.getDate();
    (byDay[k] = byDay[k] || []).push({
      a,
      hhmm: String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'),
    });
  });
  const head = `
    <div class="cal-head">
      <button class="btn ghost sm" onclick="calNav(-1)" title="${tr('الشهر السابق')}">‹</button>
      <span class="cal-title">${months[CAL_M]} ${CAL_Y}</span>
      <button class="btn ghost sm" onclick="calNav(1)" title="${tr('الشهر التالي')}">›</button>
      <button class="btn sm ghost" onclick="toggleCal()" style="margin-inline-start:auto">📋 ${tr('الجدول')}</button>
    </div>`;
  const dowsRow = `<div class="cal-dow">${dows.map(d => `<span>${d}</span>`).join('')}</div>`;
  let cells = '';
  for (let i = 0; i < startDow; i++) cells += `<div class="cal-cell empty"></div>`;
  for (let day = 1; day <= daysIn; day++) {
    const items = byDay[day] || [];
    const isToday = today.getFullYear() === CAL_Y && today.getMonth() === CAL_M
      && today.getDate() === day;
    cells += `<div class="cal-cell${isToday ? ' today' : ''}">
      <div class="cal-daynum">${day}</div>
      ${items.slice(0, 3).map(({ a, hhmm }) => `<div class="cal-chip ${esc(a.status)}" title="${esc(hhmm + ' — ' + (a.reason || '') + ' — ' + a.patient.full_name)}">${hhmm} ${esc(a.patient.full_name)}</div>`).join('')}
      ${items.length > 3 ? `<div class="cal-more">+${items.length - 3}</div>` : ''}
    </div>`;
  }
  const tail = (7 - ((startDow + daysIn) % 7)) % 7;
  for (let i = 0; i < tail; i++) cells += `<div class="cal-cell empty"></div>`;
  cb.innerHTML = head + dowsRow + `<div class="cal-grid">${cells}</div>`;
}

/* --- استعادة النسخ الاحتياطي (للمدير) --- */
async function restoreBackup(name) {
  const msg = 'استعادة "' + name + '"؟ سيُستبدل محتوى القاعدة الحالية — ستُصنع نسخة أمان تلقائيًا.';
  if (!confirm(msg)) return;
  try {
    const r = await api('/backup/' + encodeURIComponent(name) + '/restore', { method: 'POST' });
    toast('تمت الاستعادة: ' + r.restored + ' (نسخة الأمان: ' + r.safety_copy + ')');
    await navigate('backup');
  } catch (e) { toast(e.message, true); }
}

/* --- إدارة المستخدمين (للمدير) --- */
async function saveUser() {
  const g = id => ((document.getElementById(id) || {}).value || '').trim();
  const payload = {
    username: g('u-username'), full_name: g('u-fullname'), email: g('u-email'),
    role: ((document.getElementById('u-role') || {}).value || 'موظف استقبال'),
    password: ((document.getElementById('u-pass') || {}).value || ''),
  };
  if (!payload.username || !payload.full_name || !payload.email || !payload.password) {
    toast('الرمز والاسم والبريد وكلمة المرور مطلوبان', true);
    return;
  }
  try {
    await api('/auth/register', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم إنشاء المستخدم ✅');
    await navigate('users');
  } catch (e) { toast(e.message, true); }
}

async function toggleUser(id) {
  try {
    await api('/auth/users/' + id + '/toggle', { method: 'PUT' });
    toast('تم تحديث الحساب ✅');
    await navigate('users');
  } catch (e) { toast(e.message, true); }
}

async function setRole(id, role) {
  try {
    await api('/auth/users/' + id + '/role', { method: 'PUT', body: JSON.stringify({ role }) });
    toast('تم تغيير الصلاحية ✅');
    await navigate('users');
  } catch (e) { toast(e.message, true); navigate('users'); }
}

/* ========== عمليات إضافية ========== */
async function loadAppts() {
  const date = document.getElementById('flt-date')?.value;
  const st = document.getElementById('flt-status')?.value;
  let q = '/appointments/?';
  if (date) q += 'date=' + date + '&';
  if (st) q += 'status=' + st + '&';
  const rows = await api(q);
  const c = window._apptCache || { patients: [], doctors: [] };

  // بطاقة طابور الوصول اليوم
  const qbox = document.getElementById('queue-box');
  if (qbox) {
    try {
      const queue = await api('/appointments/queue');
      qbox.innerHTML = queue.length ? `
        <div class="card" style="margin:0;background:#f8fafd;padding:14px">
          <strong>🎫 طابور اليوم (${queue.length})</strong>
          — في الخدمة الآن: <strong>${esc(queue[0].patient.full_name)}</strong> (رقم ${queue[0].queue_number})
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
            ${queue.map((a, idx) => `<span class="pill ${idx === 0 ? 'confirmed' : 'pending'}" title="${fmtDate(a.checked_in_at)}">
              #${a.queue_number} ${esc(a.patient.full_name)}</span>`).join('')}
          </div>
        </div>` : '';
    } catch (e) { qbox.innerHTML = ''; }
  }

  document.getElementById('appt-body').innerHTML = rows.map(a => `<tr>
    <td>${a.id}</td><td>${fmtDate(a.appointment_date)}</td>
    <td>${esc(a.patient.full_name)}</td><td>${esc(a.doctor.full_name)}</td>
    <td>${esc(a.reason || '-')}</td><td>${pill(a.status)}</td>
    <td>${a.queue_number ? '<strong>#' + a.queue_number + '</strong>' : '—'}${a.checked_in_at ? `<br><small>✅ وصل</small>` : ''}</td>
    <td class="actions">
      ${!a.checked_in_at && a.status !== 'cancelled' && a.status !== 'completed' ? `<button class="btn sm ghost" onclick="checkIn(${a.id})">🎫 وصول</button>` : ''}
      ${a.status === 'pending' ? `<button class="btn sm success" onclick="setApptStatus(${a.id},'confirmed')">تأكيد</button>` : ''}
      ${a.status === 'confirmed' ? `<button class="btn sm success" onclick="setApptStatus(${a.id},'completed')">✔ إتمام</button>` : ''}
      ${a.status !== 'cancelled' && a.status !== 'completed' ? `<button class="btn sm danger" onclick="setApptStatus(${a.id},'cancelled')">إلغاء</button>` : ''}
      ${isAdmin() ? `<button class="btn sm danger" onclick="del('appointments',${a.id},'appointments')">حذف</button>` : ''}
    </td></tr>`).join('') || '<tr><td colspan="8" class="empty">لا توجد مواعيد</td></tr>';
}

async function checkIn(id) {
  try {
    await api('/appointments/' + id + '/checkin', { method: 'POST' });
    toast('تم تسجيل الوصول 🎫'); await loadAppts();
  } catch (e) { toast(e.message, true); }
}

async function setApptStatus(id, status) {
  try {
    await api('/appointments/' + id, { method: 'PUT', body: JSON.stringify({ status }) });
    toast('تم تحديث الحالة ✅'); await loadAppts();
  } catch (e) { toast(e.message, true); }
}

function filterTable(tblId, term) {
  const rows = document.querySelectorAll('#' + tblId + ' tbody tr');
  rows.forEach(r => { r.style.display = r.textContent.includes(term) ? '' : 'none'; });
}

function printInvoice(id) {
  fetch(API + `/invoices/${id}/print`, { headers: { 'Authorization': 'Bearer ' + TOKEN } })
    .then(r => r.text())
    .then(html => {
      const w = window.open('', '_blank');
      w.document.write(html); w.document.close();
      setTimeout(() => w.print(), 400);
    }).catch(e => toast('فشل فتح نافذة الطباعة', true));
}

async function makeBackup() {
  try { const r = await api('/backup', { method: 'POST' }); toast(r.message + ' ✅'); await navigate('backup'); }
  catch (e) { toast(e.message, true); }
}

async function verifyBackups() {
  try {
    const r = await api('/backup/verify?limit=20');
    if (!r.bad.length) toast(`🩺 سليمات ${r.ok}/${r.checked} نسخة ✅`);
    else toast(`⚠️ ${r.bad.length} من ${r.checked} تالفة: ${r.bad.map(b => b.file).join('، ')}`, true);
    await navigate('backup');
  } catch (e) { toast(e.message, true); }
}

async function pruneNow() {
  try {
    const r = await api('/backup/prune', { method: 'POST' });
    toast(r.message + ' ✅');
    await navigate('backup');
  } catch (e) { toast(e.message, true); }
}

async function readNotif(id) {
  try { await api('/notifications/' + id + '/read', { method: 'PUT' }); await navigate('notifications'); }
  catch (e) { toast(e.message, true); }
}

function toggleRecordAtts(id) {
  const row = document.getElementById('att-row-' + id);
  if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
}

async function readAll() {
  try { await api('/notifications/read-all', { method: 'PUT' }); toast('تم ✓'); await navigate('notifications'); }
  catch (e) { toast(e.message, true); }
}

async function uploadAtt() {
  const fileInput = document.getElementById('f-file');
  if (!fileInput.files.length) return toast('اختر ملفًا أولًا', true);
  const fd = new FormData();
  fd.append('patient_id', V('f-pat'));
  if (V('f-rec')) fd.append('record_id', V('f-rec'));
  fd.append('file', fileInput.files[0]);
  try {
    const res = await fetch(API + '/attachments/', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + TOKEN }, body: fd });
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'فشل الرفع'); }
    toast('تم رفع الملف ✅'); await navigate('attachments');
  } catch (e) { toast(e.message, true); }
}

async function previewAtt(id) {
  try {
    const blob = await apiBlob('/attachments/' + id + '/preview');
    const url = URL.createObjectURL(blob);
    const w = window.open(url, '_blank');
    if (!w) { toast('اسمح بالنوافذ المنبثقة للمعاينة', true); return; }
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (e) { toast(e.message, true); }
}

async function downloadReport() {
  const month = prompt('أدخل الشهر (YYYY-MM) أو اتركه فارغًا للفترة الحالية:');
  if (month === null) return;
  const m = month.trim();
  if (m && !/^\d{4}-\d{2}$/.test(m)) return toast('الصيغة يجب أن تكون YYYY-MM', true);
  await download('/dashboard/report/pdf' + (m ? '?month=' + m : ''), `report_${m || 'current'}.pdf`);
}

async function importPatients(input) {
  const file = input.files[0];
  input.value = '';
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(API + '/patients/import', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + TOKEN }, body: fd });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'فشل الاستيراد');
    const errs = (d.errors || []).slice(0, 3)
      .map(e => (e.row > 0 ? `سطر ${e.row}: ` : '') + e.error).join(' | ');
    toast(`✅ أُضيف ${d.created} — مكرّر ${d.skipped}` + (errs ? ` — أخطاء: ${errs}` : ''),
      (d.errors || []).length > 0);
    await navigate('patients');
  } catch (e) { toast(e.message, true); }
}

/* ========== عمليات الإضافة والحذف ========== */
async function post(path, body, view) {
  try {
    await api(path, { method: 'POST', body: JSON.stringify(body) });
    toast('تم الحفظ بنجاح ✅');
    await navigate(view);
  } catch (e) { toast(e.message, true); }
}

async function del(resource, id, view) {
  if (!confirm('هل أنت متأكد من الحذف؟ لا يمكن التراجع.')) return;
  try {
    await api(`/${resource}/${id}`, { method: 'DELETE' });
    toast('تم الحذف ✅'); await navigate(view);
  } catch (e) { toast(e.message, true); }
}

const V = id => document.getElementById(id)?.value?.trim();

function addPatient() {
  if (!V('f-name') || !V('f-email') || !V('f-phone') || !V('f-dob')) return toast('املأ الحقول المطلوبة (*)', true);
  post('/patients/', {
    full_name: V('f-name'), date_of_birth: V('f-dob'), gender: V('f-gender'),
    phone: V('f-phone'), email: V('f-email'), address: V('f-addr') || null,
    blood_type: V('f-blood') || null,
    national_id: V('f-nat') || null,
    insurer: V('f-ins') || null,
    policy_number: V('f-pol') || null,
    // حقول الملف الشخصي/الإداري والتأمين والتحذيرات
    nationality: V('f-nat2') || null,
    smoking_status: V('f-smoke') || null,
    emergency_contact_name: V('f-emg') || null,
    emergency_contact_phone: V('f-emgph') || null,
    insurance_grade: V('f-grade') || null,
    insurance_copay: V('f-copay') ? Number(V('f-copay')) : null,
    allergies: V('f-allergy') || null,
    medical_warnings: V('f-warn') || null
  }, 'patients');
}

function addDoctor() {
  if (!V('f-name') || !V('f-spec') || !V('f-lic') || !V('f-phone') || !V('f-email')) return toast('املأ الحقول المطلوبة (*)', true);
  post('/doctors/', {
    full_name: V('f-name'), specialty: V('f-spec'), license_number: V('f-lic'),
    phone: V('f-phone'), email: V('f-email'), address: V('f-addr') || null,
    department_id: V('f-dept') ? Number(V('f-dept')) : null
  }, 'doctors');
}

/* ========== الأطباء: فلترة + تعديل + توافر ========== */
let DOCTORS_CACHE = [], DOCTORS_DEPTS = [];

function filterDoctors() {
  const term = (document.getElementById('q')?.value || '').trim();
  const dept = document.getElementById('flt-dept')?.value || '';
  const av = document.getElementById('flt-avail')?.value || '';
  document.querySelectorAll('#tbl tbody tr').forEach(r => {
    if (r.dataset.dept === undefined) return; // صف الرسائل (لا يوجد أطباء)
    const okT = !term || r.textContent.includes(term);
    const okD = !dept || r.dataset.dept === dept;
    const okA = !av || r.dataset.avail === av;
    r.style.display = (okT && okD && okA) ? '' : 'none';
  });
}

function editDoctor(id) {
  const d = (DOCTORS_CACHE || []).find(x => x.id === id);
  if (!d) return toast('الطبيب غير موجود', true);
  openModal('✏️ تعديل بيانات الطبيب', `
    <div class="form-grid">
      <div class="field"><label>الاسم الكامل *</label><input id="e-name" value="${esc(d.full_name)}"></div>
      <div class="field"><label>التخصص *</label><input id="e-spec" value="${esc(d.specialty)}"></div>
      <div class="field"><label>رقم الترخيص *</label><input id="e-lic" value="${esc(d.license_number)}"></div>
      <div class="field"><label>الهاتف *</label><input id="e-phone" value="${esc(d.phone)}"></div>
      <div class="field"><label>البريد الإلكتروني *</label><input id="e-email" type="email" value="${esc(d.email)}"></div>
      <div class="field"><label>العنوان</label><input id="e-addr" value="${esc(d.address || '')}"></div>
      <div class="field"><label>القسم</label><select id="e-dept"><option value="">—</option>
        ${(DOCTORS_DEPTS || []).map(x => `<option value="${x.id}" ${d.department_id === x.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
    </div>
    <button class="btn success" style="margin-top:12px" onclick="saveDoctor(${id})">حفظ التعديلات</button>`);
}

async function saveDoctor(id) {
  if (!V('e-name') || !V('e-spec') || !V('e-lic') || !V('e-phone') || !V('e-email'))
    return toast('املأ الحقول المطلوبة (*)', true);
  try {
    await api('/doctors/' + id, {
      method: 'PUT',
      body: JSON.stringify({
        full_name: V('e-name'), specialty: V('e-spec'), license_number: V('e-lic'),
        phone: V('e-phone'), email: V('e-email'), address: V('e-addr') || null,
        department_id: V('e-dept') ? Number(V('e-dept')) : null
      })
    });
    toast('تم حفظ التعديلات ✅');
    closeModal();
    await navigate('doctors');
  } catch (e) { toast(e.message, true); }
}

async function toggleDoctorAvail(id, current) {
  try {
    await api(`/doctors/${id}/availability`, {
      method: 'PUT', body: JSON.stringify({ is_available: !current })
    });
    toast((!current ? 'أصبح الطبيب متاحًا ✅' : 'أُوقف توافر الطبيب ⛔'));
    await navigate('doctors');
  } catch (e) { toast(e.message, true); }
}

/* تقرير أداء الطبيب الشهري — مواعيد الشهر ونسبة إتمامه وسجلاته */
function doctorReport(id) {
  const d = (DOCTORS_CACHE || []).find(x => x.id === id);
  if (!d) return toast('الطبيب غير موجود', true);
  openModal('📈 تقرير الأداء الشهري — ' + esc(d.full_name), `
    <div class="toolbar" style="margin-bottom:10px">
      <input type="month" id="rp-month" value="${new Date().toISOString().slice(0, 7)}"
             onchange="loadDoctorReport(${id})">
      <button class="btn ghost" onclick="loadDoctorReport(${id})">🔄 تحديث</button>
    </div>
    <div id="rp-body"><div class="empty">جارٍ التحميل…</div></div>
    <div class="row2" style="margin-top:12px">
      <button class="btn ghost" onclick="exportDoctorReport(${id},'csv')">⬇️ CSV</button>
      <button class="btn ghost" onclick="exportDoctorReport(${id},'pdf')">🖨️ PDF</button>
      <button class="btn ghost" onclick="exportDoctorReport(${id},'license')">🪪 بطاقة الترخيص</button>
    </div>`, true);
  loadDoctorReport(id);
}

async function loadDoctorReport(id) {
  const box = document.getElementById('rp-body');
  const m = V('rp-month') || new Date().toISOString().slice(0, 7);
  if (!box) return;
  box.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  try {
    const r = await api(`/doctors/${id}/performance?month=${encodeURIComponent(m)}`);
    const pct = Math.round((r.completion_rate || 0) * 100);
    box.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="num">${r.total}</div><div class="lbl">مواعيد الشهر</div></div>
        <div class="stat green"><div class="num">${r.completed}</div><div class="lbl">مكتملة</div></div>
        <div class="stat amber"><div class="num">${r.cancelled}</div><div class="lbl">ملغاة</div></div>
        <div class="stat"><div class="num">${pct}%</div><div class="lbl">نسبة الإتمام</div></div>
        <div class="stat"><div class="num">${r.patients}</div><div class="lbl">مرضى مرتبطون</div></div>
        <div class="stat"><div class="num">${r.records}</div><div class="lbl">سجلات طبية</div></div>
      </div>
      <p style="margin:8px 0 0;color:#64748b">معلّقة: ${r.pending} · مؤكّدة: ${r.confirmed} — الشهر ${esc(r.month)}</p>`;
  } catch (e) {
    box.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`;
  }
}

/* تصدير تقرير الطبيب: CSV / PDF / بطاقة الترخيص */
function exportDoctorReport(id, kind) {
  const m = V('rp-month') || new Date().toISOString().slice(0, 7);
  if (kind === 'license') return download(`/doctors/${id}/license.pdf`, `license_doctor_${id}.pdf`);
  if (kind === 'pdf') return download(`/doctors/${id}/performance/report.pdf?month=${encodeURIComponent(m)}`, `doctor_${id}_report_${m}.pdf`);
  return download(`/doctors/${id}/performance/export.csv?month=${encodeURIComponent(m)}`, `doctor_${id}_report_${m}.csv`);
}

/* تقرير مقارن لجميع الأطباء — ترتيب حسب نسبة الإتمام ثم حجم العمل */
async function doctorsPerformance() {
  const def = new Date().toISOString().slice(0, 7);
  openModal('📊 أداء جميع الأطباء الشهري', `
    <div class="toolbar" style="margin-bottom:10px">
      <input type="month" id="pm-month" value="${def}" onchange="loadDoctorsPerformance()">
      <button class="btn ghost" onclick="loadDoctorsPerformance()">🔄 تحديث</button>
      <button class="btn ghost" onclick="downloadDoctorsPerfCSV()">⬇️ CSV</button>
    </div>
    <div id="pm-body"><div class="empty">جارٍ التحميل…</div></div>`, true);
  loadDoctorsPerformance();
}

async function loadDoctorsPerformance() {
  const box = document.getElementById('pm-body');
  const m = V('pm-month') || new Date().toISOString().slice(0, 7);
  if (!box) return;
  box.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  try {
    const rows = await api(`/doctors/performance?month=${encodeURIComponent(m)}`);
    if (!rows.length) { box.innerHTML = '<div class="empty">لا يوجد أطباء</div>'; return; }
    box.innerHTML = `<div style="overflow-x:auto"><table>
      <thead><tr><th>#</th><th>الطبيب</th><th>التخصص</th><th>القسم</th><th>إجمالي</th>
      <th>مكتملة</th><th>ملغاة</th><th>الإتمام</th><th>مرضى</th><th>سجلات</th></tr></thead>
      <tbody>${rows.map((r, i) => `<tr>
        <td>${i + 1}</td><td><strong>${esc(r.full_name)}</strong></td>
        <td>${esc(r.specialty)}</td><td>${esc(r.department || '-')}</td>
        <td>${r.total}</td><td>${r.completed}</td><td>${r.cancelled}</td>
        <td>${Math.round((r.completion_rate || 0) * 100)}%</td>
        <td>${r.patients}</td><td>${r.records}</td>
      </tr>`).join('')}</tbody></table></div>
      <p style="margin:8px 0 0;color:#64748b">الترتيب: نسبة الإتمام ثم حجم العمل — الشهر ${esc(m)}</p>`;
  } catch (e) {
    box.innerHTML = `<div class="empty" style="color:#dc3545">⚠️ ${esc(e.message)}</div>`;
  }
}

function downloadDoctorsPerfCSV() {
  const m = V('pm-month') || new Date().toISOString().slice(0, 7);
  return download(`/doctors/performance/export.csv?month=${encodeURIComponent(m)}`, `doctors_performance_${m}.csv`);
}

/* نوبات العمل الأسبوعية — جدول 7 أيام يُحفظ استبدالًا */
async function doctorSchedule(id) {
  const d = (DOCTORS_CACHE || []).find(x => x.id === id);
  if (!d) return toast('الطبيب غير موجود', true);
  const DAYS = ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة'];
  let entries = [];
  try { entries = await api(`/doctors/${id}/schedule`); }
  catch (e) { return toast(e.message, true); }
  const by = {};
  entries.forEach(e => { by[e.day_of_week] = e; });
  const rows = DAYS.map((name, day) => {
    const e = by[day];
    return `<tr>
      <td><label style="display:flex;gap:6px;align-items:center;font-weight:bold">
        <input type="checkbox" id="sc-on-${day}" ${e && e.is_active !== false ? 'checked' : ''}> ${name}</label></td>
      <td><input type="time" id="sc-s-${day}" value="${e ? e.start_time.slice(0, 5) : '09:00'}"></td>
      <td><input type="time" id="sc-e-${day}" value="${e ? e.end_time.slice(0, 5) : '15:00'}"></td>
      <td><input id="sc-l-${day}" style="width:100%" placeholder="الحجرة/العيادة"
           value="${e && e.location ? esc(e.location) : ''}"></td>
    </tr>`;
  }).join('');
  openModal('🗓️ نوبات العمل — ' + esc(d.full_name), `
    <div style="overflow-x:auto"><table>
      <thead><tr><th>اليوم</th><th>من</th><th>إلى</th><th>المكان</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <p style="margin:8px 0 0;color:#64748b">علّم الأيام العاملة ثم احفظ — يُستبدل الأسبوع كاملًا.</p>
    <div class="row2" style="margin-top:12px">
      <button class="btn success" onclick="saveDoctorSchedule(${id})">💾 حفظ الأسبوع</button>
      <button class="btn ghost" onclick="closeModal()">إلغاء</button>
    </div>`);
}

async function saveDoctorSchedule(id) {
  const entries = [];
  for (let day = 0; day < 7; day++) {
    if (!document.getElementById('sc-on-' + day)?.checked) continue;
    entries.push({
      day_of_week: day,
      start_time: V('sc-s-' + day),
      end_time: V('sc-e-' + day),
      location: V('sc-l-' + day) || null
    });
  }
  try {
    await api(`/doctors/${id}/schedule`, { method: 'PUT', body: JSON.stringify({ entries }) });
    toast('حُفظت نوبات الأسبوع ✅');
    closeModal();
  } catch (e) { toast(e.message, true); }
}

function addAppt() {
  if (!V('f-date')) return toast('اختر التاريخ والوقت', true);
  post('/appointments/', {
    patient_id: Number(V('f-pat')), doctor_id: Number(V('f-doc')),
    appointment_date: V('f-date'), reason: V('f-reason') || null
  }, 'appointments');
}

function addRecord() {
  if (!V('f-dx')) return toast('التشخيص مطلوب', true);
  const body = {
    patient_id: Number(V('f-pat')), diagnosis: V('f-dx'),
    prescription: V('f-rx') || null, notes: V('f-notes') || null
  };
  if (V('f-doc')) body.doctor_id = Number(V('f-doc'));
  post('/medical-records/', body, 'records');
}

function addDept() {
  if (!V('f-name')) return toast('اسم القسم مطلوب', true);
  post('/departments/', { name: V('f-name'), floor: V('f-floor') || null, description: V('f-desc') || null }, 'departments');
}

function addBed() {
  if (!V('f-num')) return toast('رقم السرير مطلوب', true);
  post('/beds/', { bed_number: V('f-num'), department_id: Number(V('f-dept')) }, 'beds');
}

async function updateBed(id, status) {
  try { await api('/beds/' + id, { method: 'PUT', body: JSON.stringify({ status }) }); toast('تم تحديث السرير ✅'); await navigate('beds'); }
  catch (e) { toast(e.message, true); }
}

function addInvoice() {
  if (!V('f-amt') || !V('f-desc')) return toast('المبلغ والوصف مطلوبان', true);
  const body = {
    patient_id: Number(V('f-pat')), amount: Number(V('f-amt')),
    description: V('f-desc'), status: V('f-st'),
    discount: V('f-disc') ? Number(V('f-disc')) : 0,
    tax_rate: V('f-tax') ? Number(V('f-tax')) : 0
  };
  if (V('f-appt')) body.appointment_id = Number(V('f-appt'));
  if (V('f-rec')) body.record_id = Number(V('f-rec'));
  if (V('f-ins')) body.insurer = V('f-ins');
  if (V('f-pol')) body.policy_number = V('f-pol');
  post('/invoices/', body, 'invoices');
}

async function payInvoice(id) {
  const method = prompt('طريقة الدفع (cash / card / insurance):', 'cash');
  if (method === null) return;
  const m = method.trim().toLowerCase() || 'cash';
  if (!['cash', 'card', 'insurance'].includes(m))
    return toast('اختر: cash أو card أو insurance', true);
  const amtStr = prompt('المبلغ (اتركه فارغًا لدفع المتبقي كاملًا):', '');
  if (amtStr === null) return;
  const body = { method: m };
  if (amtStr.trim()) {
    const amt = Number(amtStr);
    if (!amt || amt <= 0) return toast('أدخل مبلغًا صحيحًا أكبر من صفر', true);
    body.amount = amt;
  }
  try {
    await api('/invoices/' + id + '/pay', { method: 'POST', body: JSON.stringify(body) });
    toast('تم الدفع 💰');
    await navigate('invoices');
  } catch (e) { toast(e.message, true); }
}

function addStaff() {
  if (!V('f-name') || !V('f-pos') || !V('f-phone') || !V('f-email') || !V('f-hire')) return toast('املأ الحقول المطلوبة (*)', true);
  post('/staff/', {
    full_name: V('f-name'), position: V('f-pos'), phone: V('f-phone'),
    email: V('f-email'), hire_date: V('f-hire'), salary: V('f-sal') ? Number(V('f-sal')) : null
  }, 'hr');   /* الإضافة تتم داخل تبويب القائمة في شؤون الموظفين — نعود إليها */
}

/* ========== عمليات المحاور الجديدة ========== */
function addLabOrder() {
  if (!V('f-test')) return toast('اسم التحليل مطلوب', true);
  const body = {
    patient_id: Number(V('f-pat')), test_type: V('f-type') || 'lab',
    test_name: V('f-test'), price: V('f-price') ? Number(V('f-price')) : 0
  };
  if (V('f-doc')) body.doctor_id = Number(V('f-doc'));
  if (V('f-lnotes')) body.notes = V('f-lnotes');
  post('/lab-orders/', body, 'lab');
}

async function setLabStatus(id, status) {
  try {
    await api('/lab-orders/' + id, { method: 'PUT', body: JSON.stringify({ status }) });
    toast('تم تحديث الطلب ✅'); await navigate('lab');
  } catch (e) { toast(e.message, true); }
}

async function setLabResult(id) {
  const result = prompt('أدخل نتيجة التحليل:');
  if (result === null || !result.trim()) return;
  try {
    await api('/lab-orders/' + id, {
      method: 'PUT', body: JSON.stringify({ status: 'ready', result: result.trim() }) });
    toast('تم حفظ النتيجة ✅'); await navigate('lab');
  } catch (e) { toast(e.message, true); }
}

function addMedication(view) {
  if (!V('f-code') || !V('f-mname')) return toast('الرمز والاسم مطلوبان', true);
  post('/medications/', {
    code: V('f-code'), name: V('f-mname'),
    quantity: V('f-qty') ? Number(V('f-qty')) : 0,
    unit: V('f-unit') || 'علبة',
    price: V('f-mprice') ? Number(V('f-mprice')) : 0,
    min_quantity: V('f-minq') ? Number(V('f-minq')) : 10,
    expiry_date: V('f-exp') ? new Date(V('f-exp')).toISOString() : null
  }, view || 'pharmacy');
}

async function restock(id) {
  const qty = prompt('كمية التوريد:', '10');
  if (qty === null || !qty.trim()) return;
  const n = Number(qty);
  if (!n || n <= 0) return toast('أدخل كمية صحيحة', true);
  try {
    await api('/inventory/' + id + '/restock', {
      method: 'POST', body: JSON.stringify({ quantity: n }) });
    toast('تم التوريد 📦'); await navigate(CURRENT_VIEW);
  } catch (e) { toast(e.message, true); }
}

async function adjustStock(id) {
  const v = prompt('الرصيد الفعلي بعد الجرد:', '');
  if (v === null || !v.trim()) return;
  const n = Number(v);
  if (!Number.isInteger(n) || n < 0) return toast('أدخل عدداً صحيحاً (0 فأكثر)', true);
  try {
    await api('/inventory/' + id + '/adjust', {
      method: 'PUT', body: JSON.stringify({ quantity: n }) });
    toast('تم الجرد ✅'); await navigate(CURRENT_VIEW);
  } catch (e) { toast(e.message, true); }
}

/* ========== الصيدلية: سلة الصرف، الوصفات، الإرجاع، الإتلاف ========== */

/* سطر واحد لسلة الصرف أو لبند وصفة (نفس البنية والحقول) */
function basketRowHTML(opts) {
  const o = opts !== undefined ? opts : PH_OPTS;
  return `<tr>
    <td><select class="bk-med" style="min-width:170px">${o}</select></td>
    <td><input class="bk-qty" type="number" min="1" value="1" style="width:70px"></td>
    <td><input class="bk-dose" placeholder="قرص بعد الأكل" style="width:130px"></td>
    <td><input class="bk-freq" placeholder="3 مرات يوميًا" style="width:130px"></td>
    <td><input class="bk-dur" placeholder="5 أيام" style="width:100px"></td>
    <td><input class="bk-inst" placeholder="تعليمات إضافية" style="width:140px"></td>
    <td><button class="btn sm danger" onclick="this.closest('tr').remove()">✕</button></td>
  </tr>`;
}

function addBasketRow() {
  const tb = document.getElementById('basket-rows');
  if (tb) tb.insertAdjacentHTML('beforeend', basketRowHTML());
}

function addRxItemRow() {
  const tb = document.getElementById('rx-rows');
  if (tb) tb.insertAdjacentHTML('beforeend', basketRowHTML());
}

/* قراءة بنود جدول (سلة أو وصفة) — يرجع null عند بند ناقص */
function readItems(tbodyId) {
  const rows = [...document.querySelectorAll('#' + tbodyId + ' tr')];
  const items = [];
  for (const r of rows) {
    const med = Number((r.querySelector('.bk-med') || {}).value);
    const qty = Number((r.querySelector('.bk-qty') || {}).value);
    if (!med) return null;
    if (!qty || qty < 1) return null;
    const val = cls => (r.querySelector(cls) || {}).value?.trim() || null;
    items.push({ medication_id: med, quantity: qty,
                 dosage: val('.bk-dose'), frequency: val('.bk-freq'),
                 duration: val('.bk-dur'), instructions: val('.bk-inst') });
  }
  return items;
}

/* صرف السلة كلها — all-or-nothing على الخادم */
async function dispenseBatch() {
  const items = readItems('basket-rows');
  if (!items) return toast('أكمل كل بنود السلة (دواء + كمية ≥ 1)', true);
  if (!items.length) return toast('السلة فارغة — أضف بندًا أولًا', true);
  try {
    const res = await api('/dispenses/batch', { method: 'POST',
      body: JSON.stringify({ patient_id: Number(V('f-dpat')), items,
                             notes: V('f-basket-notes') || null }) });
    toast(`تم صرف ${res.count} بند — الإجمالي ${res.total} ر.س ✅`);
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

/* بحث بالباركود/الرمز: يختار الدواء في آخر سطر بالسلة */
function quickFind() {
  const code = (V('f-ph-code') || V('f-basket-code') || '').trim().toLowerCase();
  if (!code) return toast('امسح الباركود أو أدخل الرمز أولًا', true);
  const m = PH_MEDS.find(x => String(x.code).toLowerCase() === code)
         || PH_MEDS.find(x => String(x.code).toLowerCase().includes(code));
  if (!m) return toast('لا يوجد دواء بهذا الرمز', true);
  if (m.expiry_date && new Date(m.expiry_date) < new Date())
    return toast(`«${m.name}» منتهي الصلاحية — لا يمكن صرفه`, true);
  if (m.quantity <= 0) return toast(`«${m.name}» نافد من المخزون`, true);
  const tb = document.getElementById('basket-rows');
  if (!tb) return;
  if (!tb.querySelector('tr')) tb.insertAdjacentHTML('beforeend', basketRowHTML());
  const sel = tb.querySelector('tr:last-child .bk-med');
  if (sel) { sel.value = String(m.id); sel.focus(); }
  toast(`تم اختيار «${m.name}» — المتوفر ${m.quantity}`);
}

/* فلترة جدول الأدوية (بحث + حالة) بدون إعادة تحميل */
function filterPharmacy() {
  PH.q = (V('f-ph-q') || '').toLowerCase();
  PH.status = V('f-ph-status') || '';
  let shown = 0;
  document.querySelectorAll('#ph-meds tbody tr[data-status]').forEach(tr => {
    const okQ = !PH.q || (tr.dataset.text || '').includes(PH.q);
    const okS = !PH.status || tr.dataset.status === PH.status;
    tr.style.display = (okQ && okS) ? '' : 'none';
    if (okQ && okS) shown++;
  });
  const c = document.getElementById('ph-count');
  if (c) c.textContent = shown;
}

/* فلترة جدول الوصفات حسب الحالة (عرض فقط — بدون إعادة تحميل) */
function filterRxRows() {
  const want = V('f-rx-status') || '';
  document.querySelectorAll('#rx-list tbody tr[data-rxstatus]').forEach(tr => {
    tr.style.display = (!want || tr.dataset.rxstatus === want) ? '' : 'none';
  });
}

/* الانتقال إلى فلترة الوصفات المعلّقة من بطاقة rx-stale */
function showStaleRx() {
  const sel = document.getElementById('f-rx-status');
  if (sel) { sel.value = 'PENDING'; filterRxRows(); }
  const list = document.getElementById('rx-list');
  if (list) list.scrollIntoView({ behavior: 'smooth' });
}

/* فلترة المختبر: بحث + حالة معًا (data-status) */
function filterLabRows() {
  const q = (V('f-lab-q') || '').toLowerCase();
  const want = V('f-lab-status') || '';
  document.querySelectorAll('#tbl tbody tr[data-status]').forEach(tr => {
    const okQ = !q || tr.textContent.toLowerCase().includes(q);
    const okS = !want || tr.dataset.status === want;
    tr.style.display = (okQ && okS) ? '' : 'none';
  });
}

/* إرجاع صرف سابق — السبب إلزامي */
async function returnDispense(id) {
  const reason = prompt('سبب الإرجاع (إلزامي):');
  if (reason === null) return;
  if (!reason.trim()) return toast('سبب الإرجاع إلزامي', true);
  try {
    await api('/dispenses/' + id + '/return', { method: 'POST',
      body: JSON.stringify({ reason: reason.trim() }) });
    toast('تم الإرجاع وإعادة الكمية للمخزون ↩');
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

/* إتلاف كمية منتهية (للمدير) — حركة disposal */
async function disposeMed(id) {
  const qty = prompt('الكمية المُتلفة:', '1');
  if (qty === null || !qty.trim()) return;
  const n = Number(qty);
  if (!Number.isInteger(n) || n <= 0) return toast('أدخل عددًا صحيحًا أكبر من صفر', true);
  const note = (prompt('سبب الإتلاف (اختياري):') || '').trim() || null;
  try {
    await api('/inventory/' + id + '/dispose', { method: 'POST',
      body: JSON.stringify({ quantity: n, note }) });
    toast('تم الإتلاف وتسجيل حركته 🗑️');
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

/* إنشاء وصفة (طبيب/مدير) */
async function createRx() {
  const items = readItems('rx-rows');
  if (!items) return toast('أكمل كل بنود الوصفة (دواء + كمية ≥ 1)', true);
  if (!items.length) return toast('أضف بن وصفة واحدًا على الأقل', true);
  try {
    await api('/prescriptions/', { method: 'POST',
      body: JSON.stringify({ patient_id: Number(V('f-rx-pat')),
                             notes: V('f-rx-notes') || null, items }) });
    toast('تم إنشاء الوصفة 📋');
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

/* صرف كل الأبنية المعلَّقة في وصفة — دفعة واحدة */
async function dispenseRx(id) {
  if (!confirm('صرف كل الأبنية المعلَّقة في هذه الوصفة دفعة واحدة؟')) return;
  try {
    const rows = await api('/prescriptions/' + id + '/dispense',
                           { method: 'POST', body: JSON.stringify({}) });
    toast(`تم صرف ${rows.length} بند من الوصفة 💊`);
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

/* إلغاء وصفة (تبقى محفوظة كملغاة) */
async function cancelRx(id) {
  if (!confirm('إلغاء هذه الوصفة؟')) return;
  try {
    await api('/prescriptions/' + id, { method: 'PUT',
      body: JSON.stringify({ status: 'CANCELLED' }) });
    toast('أُلغيت الوصفة');
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

/* توريد بالكمية المقترحة من شاشة إعادة الطلب */
async function restockSuggested(id, qty) {
  if (!confirm(`توريد ${qty} وحدة بالكمية المقترحة؟`)) return;
  try {
    await api('/inventory/' + id + '/restock',
              { method: 'POST', body: JSON.stringify({ quantity: qty }) });
    toast('تم التوريد بالكمية المقترحة 📦');
    await navigate('pharmacy');
  } catch (e) { toast(e.message, true); }
}

function addPayroll() {
  if (!V('f-period') || !V('f-base')) return toast('الفترة والراتب الأساسي مطلوبان', true);
  if (!/^\d{4}-\d{2}$/.test(V('f-period'))) return toast('صيغة الفترة: YYYY-MM', true);
  post('/payroll/', {
    staff_id: Number(V('f-staff')), period: V('f-period'),
    base_salary: Number(V('f-base')),
    bonus: V('f-bonus') ? Number(V('f-bonus')) : 0,
    deduction: V('f-ded') ? Number(V('f-ded')) : 0,
    notes: V('f-pnotes') || null
  }, 'hr');
}

async function payPayroll(id) {
  if (!confirm('تأكيد صرف هذا الراتب؟')) return;
  try {
    await api('/payroll/' + id + '/pay', { method: 'POST' });
    toast('تم صرف الراتب 💵'); await navigate('hr');
  } catch (e) { toast(e.message, true); }
}

async function changePassword() {
  const cur = prompt('كلمة المرور الحالية:');
  if (cur === null) return;
  const nw = prompt('كلمة المرور الجديدة (8 أحرف على الأقل):');
  if (nw === null) return;
  const nw2 = prompt('تأكيد كلمة المرور الجديدة:');
  if (nw2 === null) return;
  if (nw !== nw2) return toast('كلمتا المرور غير متطابقتين', true);
  if (nw.length < 8) return toast('كلمة المرور قصيرة (8 أحرف على الأقل)', true);
  try {
    await api('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: cur, new_password: nw }) });
    toast('تم تغيير كلمة المرور ✅');
  } catch (e) { toast(e.message, true); }
}

/* ========== بحث سريع Ctrl+K ========== */
let gsTimer = null, gsItems = [], gsActive = 0;

function openGSearch() {
  if (!TOKEN || !USER) return;
  const back = document.getElementById('gsearch-back');
  if (!back) return;
  back.style.display = 'flex';
  const inp = document.getElementById('gsearch-input');
  inp.value = '';
  document.getElementById('gsearch-results').innerHTML =
    '<div class="gs-empty">اكتب حرفًا واحدًا على الأقل لبدء البحث…</div>';
  gsItems = []; gsActive = 0;
  inp.focus();
}

function closeGSearch() {
  const back = document.getElementById('gsearch-back');
  if (back) back.style.display = 'none';
}

async function gsRun() {
  const q = document.getElementById('gsearch-input').value.trim();
  const box = document.getElementById('gsearch-results');
  if (!q) {
    box.innerHTML = '<div class="gs-empty">اكتب حرفًا واحدًا على الأقل لبدء البحث…</div>';
    gsItems = []; gsActive = 0;
    return;
  }
  try {
    const r = await api('/search/?q=' + encodeURIComponent(q));
    gsItems = (r && r.results) || [];
    gsActive = 0;
    box.innerHTML = gsItems.length
      ? gsItems.map((it, i) => `
        <div class="gs-item${i === 0 ? ' active' : ''}" onclick="gsGo(${i})">
          <div class="gs-ic">${it.icon}</div>
          <div class="gs-body">
            <div class="gs-t">${esc(it.title)}</div>
            <div class="gs-s">${esc(it.subtitle || '')}</div>
          </div>
          <span class="gs-tag">${esc(it.type_label || it.type)}</span>
        </div>`).join('')
      : '<div class="gs-empty">لا توجد نتائج لـ «' + esc(q) + '»</div>';
  } catch (e) {
    box.innerHTML = '<div class="gs-empty">⚠️ ' + esc(e.message) + '</div>';
  }
}

function gsGo(i) {
  const it = gsItems[i];
  if (!it) return;
  closeGSearch();
  navigate(it.view);
}

document.addEventListener('keydown', (e) => {
  const back = document.getElementById('gsearch-back');
  const open = !!(back && back.style.display !== 'none');
  if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault();
    if (open) closeGSearch(); else openGSearch();
    return;
  }
  if (!open) return;
  if (e.key === 'Escape') { closeGSearch(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (!gsItems.length) return;
    gsActive = (gsActive + (e.key === 'ArrowDown' ? 1 : gsItems.length - 1)) % gsItems.length;
    document.querySelectorAll('#gsearch-results .gs-item').forEach((el, idx) => {
      el.classList.toggle('active', idx === gsActive);
      if (idx === gsActive) el.scrollIntoView({ block: 'nearest' });
    });
    return;
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    gsGo(gsActive);
  }
});

/* ========== بدء التشغيل ========== */
initLang();
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {}));
}
if (TOKEN && USER) enterApp();
