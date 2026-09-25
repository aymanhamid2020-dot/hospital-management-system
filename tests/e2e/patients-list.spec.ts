import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError } from './views';

/** فتح شاشة المرضى والانتظار حتى يكتمل أول تحميل */
async function openPatients(page: import('@playwright/test').Page) {
  await login(page);
  await page.click('.sidebar a[data-view="patients"]');
  await expect(page.locator('#page-title')).toHaveText('المرضى');
  await expect(page.locator('#tbl tbody tr').first()).toBeVisible();
}

/** شريط «عرض X–Y من Z» (Locator ليعمل مع toContainText) */
const shown = (page: import('@playwright/test').Page) =>
  page.locator('.pager > span');

/** العدد الكلي من شريط الترقيم */
async function shownTotal(page: import('@playwright/test').Page): Promise<number> {
  const txt = await shown(page).innerText();
  return Number((txt.match(/من (\d+)/) || [])[1] || 0);
}

test.describe('قائمة المرضى 🧑‍🤝‍🧑', () => {
  test('البحث يمرّ على الخادم ويرشّح الجدول', async ({ page }) => {
    await openPatients(page);

    const firstName = (await page.locator('#tbl tbody tr td:nth-child(2) strong').first().innerText()).trim();

    // بحث باسم مريض موجود ⇒ يصبح هو النتيجة الوحيدة
    await page.fill('#q', firstName);
    await expect.poll(async () =>
      (await page.locator('#tbl tbody tr').count()), { timeout: 10_000 }).toBe(1);
    await expect(page.locator('#tbl tbody tr').first()).toContainText(firstName);

    // بحث بلا نتائج يعرض رسالة الفلاتر لا «لا يوجد مرضى»
    await page.fill('#q', 'zzz-no-such-patient-zzz');
    await expect(page.locator('#tbl tbody .empty'))
      .toHaveText('لا نتائج مطابقة للفلاتر');
    await expect(shown(page)).toContainText('عرض 0–0 من 0');

    // زر المسح يعيد القائمة كاملة
    await page.click('button:has-text("مسح الفلاتر")');
    await expect.poll(async () =>
      (await page.locator('#tbl tbody tr').count()), { timeout: 10_000 }).toBeGreaterThan(1);
    await expect(page.locator('#q')).toHaveValue('');
    await expectNoUiError(page);
  });

  test('الفلاتر: فصيلة الدم + من له تحذير', async ({ page }) => {
    await openPatients(page);

    // فصيلة دم من القائمة ⇒ كل صف معروض يحملها
    await page.selectOption('#flt-blood', 'O+');
    await expect.poll(async () => {
      const rows = page.locator('#tbl tbody tr');
      const n = await rows.count();
      if (n === 0) return false;
      const cells = await rows.locator('td:nth-child(5)').allInnerTexts();
      return cells.every(c => c.trim() === 'O+');
    }, { timeout: 10_000 }).toBe(true);

    // فلتر التحذير: كل صف ظاهر يحمل شارة ⚠️ تحذير
    await page.selectOption('#flt-blood', '');
    await page.check('#flt-alert');
    // انتظار اكتمال الفلترة: إمّا صفوف تحذيرية أو رسالة «لا نتائج»
    const noRows = page.locator('#tbl tbody .empty');
    await expect(noRows.or(page.locator('#tbl tbody .warn-tag').first()))
      .toBeVisible({ timeout: 10_000 });
    if (await noRows.isVisible()) {
      test.skip(true, 'لا يوجد مرضى لديهم تحذيرات في هذه البيانات — فلتر التنبيه غير قابل للاختبار');
    }
    await expect.poll(async () => {
      const rows = page.locator('#tbl tbody tr');
      const n = await rows.count();
      if (n === 0) return false;
      const tags = await rows.locator('.warn-tag').count();
      return tags === n;
    }, { timeout: 10_000 }).toBe(true);

    await page.click('button:has-text("مسح الفلاتر")');
    await expect(page.locator('#flt-alert')).not.toBeChecked();
    await expectNoUiError(page);
  });

  test('الترقيم يعمل والصفوف لا تتكرر', async ({ page }) => {
    await openPatients(page);

    const total = await shownTotal(page);
    test.skip(total <= 25, 'أقل من صفحة واحدة — الترقيم غير قابل للاختبار');

    const page1 = await page.locator('#tbl tbody tr td:first-child').allInnerTexts();
    await page.click('button:has-text("التالي")');
    await expect(shown(page)).toContainText('عرض 26–');
    const page2 = await page.locator('#tbl tbody tr td:first-child').allInnerTexts();
    expect(page1.some(id => page2.includes(id)), 'تكرار صفوف بين الصفحتين').toBeFalsy();

    await page.click('button:has-text("السابق")');
    await expect(shown(page)).toContainText('عرض 1–');
    await expectNoUiError(page);
  });

  test('النقر على صف مريض يفتح ملفه', async ({ page }) => {
    await openPatients(page);
    await page.locator('#tbl tbody tr').first().locator('td:nth-child(2)').click();
    // الملف داخل الشاشة: تبويب «الملف الشخصي» مفعّل بدل النافذة المنبثقة
    await expect(page.locator('#pat-tabs .tab.active')).toContainText('الملف الشخصي');
    await expect(page.locator('#modal-back')).not.toHaveClass(/show/);
    await expect(page.locator('#chart-tabs .tab')).toHaveCount(6);

    // شريط التبويبات يعود بالكامل إلى القائمة (الجدول والفلاتر والصفحات)
    await page.click('#pat-tabs .tab:has-text("قائمة المرضى")');
    await expect(page.locator('#tbl')).toBeVisible();
    await expect(page.locator('.pager')).toBeVisible();
    await expectNoUiError(page);
  });

  test('أعمدة العمر والتأمين معروضة', async ({ page }) => {
    await openPatients(page);
    for (const h of ['المريض', 'العمر', 'الهاتف', 'الدم', 'التأمين',
                     'آخر زيارة', 'الموعد القادم', 'المتبقي']) {
      await expect(page.locator('#tbl thead th', { hasText: h })).toHaveCount(1);
    }
    // عمود العمر يحمل «سنة» لصف واحد على الأقل
    await expect.poll(async () =>
      (await page.locator('#tbl tbody td:nth-child(3)').allInnerTexts())
        .filter(t => t.includes('سنة')).length, { timeout: 10_000 }).toBeGreaterThan(0);
    await expectNoUiError(page);
  });

  test('نموذج الإضافة يشمل حقول الملف الشخصي والتأمين', async ({ page }) => {
    await openPatients(page);
    await page.click('summary:has-text("إضافة مريض جديد")');
    for (const id of ['f-name', 'f-nat2', 'f-smoke', 'f-emg', 'f-emgph', 'f-grade',
                      'f-copay', 'f-allergy', 'f-warn']) {
      await expect(page.locator(`#${id}`)).toBeVisible();
    }
    // حفظ مريض بحساسية ⇒ يظهر عليه شارة التحذير فورًا في القائمة
    const u = Date.now().toString().slice(-7);
    await page.fill('#f-name', `مريض واجهة ${u}`);
    await page.fill('#f-dob', '1991-04-04');
    await page.fill('#f-phone', '055' + u);
    await page.fill('#f-email', `ui_${u}@test.com`);
    await page.fill('#f-allergy', 'بنسلين');
    await page.click('button:has-text("حفظ المريض")');

    await expect.poll(async () => {
      await page.fill('#q', `مريض واجهة ${u}`);
      await page.waitForTimeout(700);
      const row = page.locator('#tbl tbody tr').first();
      return (await row.count()) ? (await row.locator('.warn-tag').count()) : 0;
    }, { timeout: 15_000 }).toBe(1);
  });
});
