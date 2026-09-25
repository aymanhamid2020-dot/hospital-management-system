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

    // ثمانية تبويبات: البيانات السبع + الرواتب
    await expect(page.locator('#hr-editor .tabbar .tab')).toHaveCount(8);

    const payrollTab = page.locator('#hr-editor .tabbar .tab', { hasText: '💵 الرواتب' });
    await expect(payrollTab).toHaveCount(1);
    await payrollTab.click();

    // لوحة قيود الرواتب كاملة داخل تبويب الملف: كشف + إضافة + تقارير
    await expect(page.locator('#hr-payroll h3').filter({ hasText: 'كشف الرواتب' }).first())
      .toBeVisible();
    await expect(page.locator('#hr-payroll button:has-text("كشف الرواتب PDF")')).toBeVisible();
    await expect(page.locator('#hr-payroll button:has-text("كشف الرواتب CSV")')).toBeVisible();
    await expect(page.locator('#hr-payroll summary:has-text("إضافة قيد راتب")')).toBeVisible();

    // شاشة المحاسبة لم يبقَ فيها تبويب رواتب
    await page.click('.sidebar a[data-view="accounting"]');
    await expect(page.locator('#acc-tabs .tab')).toHaveCount(6);
    await expect(page.locator('#acc-tabs .tab', { hasText: 'الرواتب' })).toHaveCount(0);

    await expectNoUiError(page);
  });
});
