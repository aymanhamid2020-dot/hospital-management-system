import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError } from './views';

/**
 * الرواتب صارت تبويبًا داخل شؤون الموظفين:
 * لا قائمة جانبية مستقلة، ولا تبويب داخل المحاسبة — والوظيفة كاملة داخل ملف الموظف.
 */
test.describe('شؤون الموظفين 🗂️', () => {
  test('حذف قائمة الرواتب ونقلها إلى تبويب داخل الملف', async ({ page }) => {
    await login(page);

    // لم تبقَ قائمة جانبية مستقلة للرواتب
    await expect(page.locator('.sidebar a[data-view="payroll"]')).toHaveCount(0);

    await page.click('.sidebar a[data-view="hr"]');
    await expect(page.locator('#page-title')).toHaveText('شؤون الموظفين');
    await expect(page.locator('#hr-editor')).toBeVisible();

    // تسعة تبويبات: القائمة + البيانات السبع + الرواتب
    await expect(page.locator('#hr-editor .tabbar .tab')).toHaveCount(9);

    const payrollTab = page.locator('#hr-editor .tabbar .tab', { hasText: '💵 الرواتب' });
    await expect(payrollTab).toHaveCount(1);
    await payrollTab.click();

    // لوحة قيود الرواتب كاملة داخل تبويب الملف: كشف + إضافة + تقارير
    await expect(page.locator('#hr-payroll h3').filter({ hasText: 'كشف الرواتب' }).first())
      .toBeVisible();
    await expect(page.locator('#hr-payroll button:has-text("كشف الرواتب PDF")')).toBeVisible();
    await expect(page.locator('#hr-payroll button:has-text("كشف الرواتب CSV")')).toBeVisible();
    await expect(page.locator('#hr-payroll summary:has-text("إضافة قيد راتب")')).toBeVisible();

    // شاشة المحاسبة: خمسة تبويبات (بلا رواتب وبلا مبيعات — الأخيرة شاشة مستقلة)
    await page.click('.sidebar a[data-view="accounting"]');
    await expect(page.locator('#acc-tabs .tab')).toHaveCount(5);
    await expect(page.locator('#acc-tabs .tab', { hasText: 'الرواتب' })).toHaveCount(0);

    await expectNoUiError(page);
  });

  test('اختيار موظف آخر لا يُفرغ تبويب الرواتب', async ({ page }) => {
    await login(page);
    await page.click('.sidebar a[data-view="hr"]');
    await expect(page.locator('#hr-editor')).toBeVisible();

    const people = page.locator('#hr-list .hr-person');
    test.skip((await people.count()) < 2, 'يحتاج موظفين اثنين على الأقل');

    await page.click('#hr-editor .tabbar .tab:has-text("💵 الرواتب")');
    await expect(page.locator('#hr-payroll h3').filter({ hasText: 'كشف الرواتب' }).first())
      .toBeVisible();

    // إعادة بناء المحرّر عند تبديل الموظف كانت تُبقي حاوية الرواتب فارغة
    await people.nth(1).click();
    await expect(page.locator('#hr-payroll h3').filter({ hasText: 'كشف الرواتب' }).first())
      .toBeVisible();

    await expectNoUiError(page);
  });

  test('قائمة الموظفين تبويبًا أولًا + ربط الهاتف والإيميل ببيانات الموظف', async ({ page }) => {
    await login(page);

    // شاشة الموظفون المستقلة لم تعد موجودة في القائمة الجانبية
    await expect(page.locator('.sidebar a[data-view="staff"]')).toHaveCount(0);

    await page.click('.sidebar a[data-view="hr"]');
    await expect(page.locator('#page-title')).toHaveText('شؤون الموظفين');

    // أول فتح: التبويب الأول «قائمة الموظفين» — الجدول + نموذج الإضافة داخل الشاشة
    const tabs = page.locator('#hr-editor .tabbar .tab');
    await expect(tabs).toHaveCount(9);
    await expect(tabs.first()).toContainText('قائمة الموظفين');
    await expect(page.locator('#hr-roster table')).toBeVisible();
    await expect(page.locator('#hr-roster summary')).toContainText('إضافة موظف');

    const firstRow = page.locator('#hr-roster tbody tr').first();
    const phone = (await firstRow.locator('td').nth(3).innerText()).trim();
    const email = (await firstRow.locator('td').nth(4).innerText()).trim();
    test.skip(!phone, 'الموظف الأول بلا هاتف مسجّل');

    // اختيار الموظف يفتح تبويب بياناته — والحقلان معروضان من عموديه بلا طلب إدخال جديد
    await page.click('#hr-list .hr-person');
    await expect(page.locator('#hr-editor .tabbar .tab.active')).toContainText('البيانات الشخصية');
    await expect(page.locator('input[data-hr="personal.phone"]')).toHaveValue(phone);
    if (email) await expect(page.locator('input[data-hr="personal.email"]')).toHaveValue(email);

    await expectNoUiError(page);
  });
});
