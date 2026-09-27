import { test, expect } from '@playwright/test';
import { login, authHeader } from './helpers';
import { expectNoUiError } from './views';

/**
 * شاشة إدخال النتيجة صارت **ورقة تقرير فحص** يقرأها الطبيب ويحدّد العلاج:
 * المريض ورقم ملفه + بيانات الفحص من الدليل (الرمز/المجموعة/الأنبوب/الصيام
 * وحالته مفعّلًا) + النطاق المرجعي + موضع القيمة فيه لحظيًّا +
 * التفسير النوعي + ورقة المعاينة قبل الحفظ.
 */
test.describe('تقرير فحص المختبر 🧪', () => {
  test('بطاقة الفحص والقراءة الحيّة وورقة المعاينة', async ({ page, request }) => {
    const headers = await authHeader(request);
    const uniq = Date.now().toString().slice(-7);

    // — بيانات تجريبية: فحص بنطاق معلوم وطلب عيّنته مستلمة —
    const pr = await request.post('/patients/', {
      headers,
      data: {
        full_name: `مريض تقرير ${uniq}`, date_of_birth: '1992-01-01',
        gender: 'ذكر', phone: `055${uniq}`,
        email: `labrep${uniq}@example.com`,
      },
    });
    expect(pr.ok(), await pr.text()).toBeTruthy();
    const patient = await pr.json();
    expect(patient.file_no, 'رقم ملف المريض غير مُولَّد').toBeGreaterThan(0);

    const tr = await request.post('/lab-tests/', {
      headers,
      data: {
        code: `REP${uniq}`, name: `فحص تقرير ${uniq}`, category: 'lab',
        price: 40, fasting_hours: 8, tube_type: 'EDTA', specimen_type: 'دم',
        specimen_group: 'دم كامل', unit: 'g/dL', ref_min: 12, ref_max: 17,
      },
    });
    expect(tr.ok(), await tr.text()).toBeTruthy();
    const cat = await tr.json();

    const or = await request.post('/lab-orders/', {
      headers,
      data: { patient_id: patient.id, test_name: cat.name, lab_test_id: cat.id },
    });
    expect(or.ok(), await or.text()).toBeTruthy();
    const order = await or.json();

    expect((await request.post(`/lab-orders/${order.id}/collect`, {
      headers, data: { specimen_type: 'دم' } })).ok()).toBeTruthy();
    expect((await request.post(`/lab-orders/${order.id}/receive`, {
      headers, data: { accepted: true } })).ok()).toBeTruthy();

    // — فتح شاشة المختبر ثم قسم «إدخال النتائج» —
    await login(page);
    await page.click('.sidebar a[data-view="lab"]');
    await expect(page.locator('#page-title')).toHaveText('المختبر والأشعة');
    await page.click('#main .tabbar [data-sub="results"]');
    await expect(page.locator('#lab-body')).not.toContainText('جارٍ التحميل');

    const row = page.locator('#lab-body #tbl tbody tr')
      .filter({ hasText: patient.full_name })
      .filter({ hasText: cat.name });
    await expect(row, 'الطلب غير معروض في قائمة النتائج').toHaveCount(1);

    // رقم الملف يظهر في قائمة النتائج ليعرف الطبيب أي مريض يقرأ
    await expect(row.first()).toContainText(`📁 ملف ${patient.file_no}`);
    await row.first().locator('button', { hasText: /إدخال النتيجة|تعديل النتيجة/ })
      .first().click();

    // — بطاقة الفحص داخل نافذة الإدخال —
    const modal = page.locator('#modal-back.show');
    await expect(modal).toBeVisible();
    const sheet = modal.locator('.lab-sheet');
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText(patient.full_name);
    await expect(sheet).toContainText(`📁 ملف ${patient.file_no}`);
    await expect(sheet).toContainText(cat.code);
    await expect(sheet).toContainText('دم كامل');
    await expect(sheet).toContainText('EDTA');
    await expect(sheet).toContainText('8 ساعة');
    await expect(sheet).toContainText('حالة الاختبار في الدليل');
    await expect(sheet.locator('.pill.reviewed')).toContainText('active');

    // — القراءة الحيّة: القيمة تُقارَن بالنطاق لحظة الكتابة —
    await expect(modal.locator('#m-interp .pill')).toHaveText('⏳ بانتظار القيمة');
    await modal.locator('#m-value').fill('19.4');
    await modal.locator('#m-result').fill('19.4');
    await expect(modal.locator('#m-interp .pill')).toHaveText('⬆️ مرتفعة');
    await expect(modal.locator('#m-interp .lab-interp-range'))
      .toContainText('12 – 17 g/dL');
    await expect(modal.locator('#m-interp .lab-interp-range'))
      .toHaveCSS('direction', 'ltr');
    await expect(modal.locator('#m-interp .lab-bar-dot')).toHaveCount(1);
    await expect(modal.locator('#m-interp .lab-bar-zone')).toHaveCount(1);
    // لون الشارة والشريط دلالة لا زينة: مرتفعة ⇒ برتقالي
    await expect(modal.locator('#m-interp .pill'))
      .toHaveCSS('background-color', 'rgb(255, 229, 208)');
    await expect(modal.locator('#m-interp .lab-bar-dot'))
      .toHaveCSS('background-color', 'rgb(253, 126, 20)');
    await expect(modal.locator('#m-interp .lab-qual'))
      .toContainText('تفسير نوعي:');

    // — ورقة المعاينة: نفس ما ستحمله PDF بعد الحفظ —
    await modal.locator('button:has-text("معاينة تقرير الفحص")').click();
    const report = page.locator('#modal-back.show .lab-report');
    await expect(report).toBeVisible();
    await expect(report).toContainText('ورقة نتيجة فحص');
    await expect(report.locator('.lab-sheet')).toContainText(cat.code);
    await expect(report.locator('.lab-report-rows')).toContainText('النطاق المرجعي');
    // النطاق معزول باتجاه ltr — وإلا انعكس عرضه إلى «17 – 12» في خلية عربية
    const rangeCell = report.locator('.lab-report-rows .kv', { hasText: 'النطاق المرجعي' });
    await expect(rangeCell.locator('bdi')).toHaveAttribute('dir', 'ltr');
    await expect(rangeCell).toContainText('12 – 17 g/dL');
    await expect(report.locator('.lab-report-result')).toContainText('19.4');
    await expect(report.locator('.lab-report-head .pill')).toHaveText('⬆️ مرتفعة');
    await expect(report.locator('.lab-bar-dot')).toHaveCount(1);
    await expect(report.locator('.lab-signs')).toContainText('فني المختبر');
    await expect(report.locator('.lab-signs')).toContainText('مراجعة الطبيب');

    await expectNoUiError(page);
  });

  test('حفظ النتيجة يعيد القيمة إلى الجدول في خلية التقرير', async ({ page, request }) => {
    const headers = await authHeader(request);
    const uniq = Date.now().toString().slice(-7) + 'b';

    const pr = await request.post('/patients/', {
      headers,
      data: {
        full_name: `مريض حفظ ${uniq}`, date_of_birth: '1988-06-06',
        gender: 'أنثى', phone: `056${uniq}`,
        email: `labsave${uniq}@example.com`,
      },
    });
    expect(pr.ok(), await pr.text()).toBeTruthy();
    const patient = await pr.json();

    const tr = await request.post('/lab-tests/', {
      headers,
      data: {
        code: `SAV${uniq}`, name: `فحص حفظ ${uniq}`, category: 'lab',
        price: 30, tube_type: 'سيرم', specimen_type: 'دم', unit: 'mg/dL',
        ref_min: 70, ref_max: 99,
      },
    });
    expect(tr.ok(), await tr.text()).toBeTruthy();
    const cat = await tr.json();

    const or = await request.post('/lab-orders/', {
      headers,
      data: { patient_id: patient.id, test_name: cat.name, lab_test_id: cat.id },
    });
    expect(or.ok(), await or.text()).toBeTruthy();
    const order = await or.json();
    expect((await request.post(`/lab-orders/${order.id}/collect`, {
      headers, data: { specimen_type: 'دم' } })).ok()).toBeTruthy();
    expect((await request.post(`/lab-orders/${order.id}/receive`, {
      headers, data: { accepted: true } })).ok()).toBeTruthy();

    await login(page);
    await page.click('.sidebar a[data-view="lab"]');
    await page.click('#main .tabbar [data-sub="results"]');
    await expect(page.locator('#lab-body')).not.toContainText('جارٍ التحميل');

    const row = page.locator('#lab-body #tbl tbody tr')
      .filter({ hasText: cat.name }).first();
    await row.locator('button', { hasText: /إدخال النتيجة|تعديل النتيجة/ })
      .first().click();

    const modal = page.locator('#modal-back.show');
    await modal.locator('#m-value').fill('120');
    await modal.locator('#m-result').fill('120');
    await modal.locator('button:has-text("حفظ النتيجة")').click();

    // الاحتفاظ بالمسودة عند العودة من المعاينة ثم الحفظ يعيدنا للقائمة
    await expect(page.locator('#modal-back')).not.toHaveClass(/show/);
    await expect(page.locator('#page-title')).toHaveText('المختبر والأشعة');
    await page.click('#main .tabbar [data-sub="results"]');
    await expect(page.locator('#lab-body')).not.toContainText('جارٍ التحميل');

    const saved = page.locator('#lab-body #tbl tbody tr')
      .filter({ hasText: cat.name }).first();
    await expect(saved).toContainText('120');
    await expect(saved).toContainText('mg/dL');
    await expect(saved).toContainText('خارج النطاق');

    // الخادم يحفظ القيمة الرقمية منفصلة عن النص — تُفتح من جديد وهي نفسها
    const res = await request.get(`/lab-orders/${order.id}`, { headers });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.value).toBe(120);
    expect(body.abnormal).toBe(true);

    await expectNoUiError(page);
  });
});
