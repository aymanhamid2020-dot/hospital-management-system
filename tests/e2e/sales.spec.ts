import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError, openView } from './views';

/** شاشة المبيعات: قائمة مستقلة بستة تبويبات لدورة الإيراد */
test.describe('شاشة المبيعات المستقلة 🛒', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openView(page, 'sales');
    await expect(page.locator('#rc-body .card').first()).toBeVisible();
  });

  test('المبيعات شاشة مستقلة بتبويبات وليست تبويبًا في المحاسبة', async ({ page }) => {
    const link = page.locator('.sidebar a[data-view="sales"]');
    await expect(link).toHaveCount(1);
    await expect(link).toContainText('المبيعات');
    await expect(link).not.toHaveAttribute('data-tab', /.*/);
    await expect(page.locator('#page-title')).toHaveText('المبيعات');
    await expect(page.locator('#rc-tabs .tab')).toHaveCount(6);
    await expect(page.locator('#rc-tabs .tab.active')).toHaveAttribute('data-tab', 'pos');
    await expect(page.locator('#acc-tabs')).toHaveCount(0);
    await expect(page.locator('.sidebar a[data-view="accounting"]')).toHaveCount(1);
    await expectNoUiError(page);
  });

  test('تبويب البيع يعرض السجل والفواتير وفلاتر البحث', async ({ page }) => {
    await expect(page.locator('#rc-body h3').filter({ hasText: 'نقطة البيع والفواتير' })).toBeVisible();
    await expect(page.locator('#f-acc-period')).toBeVisible();
    await expect(page.locator('#f-acc-method')).toBeVisible();
    await expect(page.locator('#f-acc-status')).toBeVisible();
    await expect(page.locator('#rc-body table').first()).toBeVisible();
    await expectNoUiError(page);
  });

  test('فلترة بفترة بلا عمليات تُظهر رسالة الفراغ', async ({ page }) => {
    await page.fill('#f-acc-period', '2099-01');
    await expect(page.locator('#rc-body table').first().locator('tbody .empty'))
      .toHaveText('لا مبيعات في هذه الفترة');
    await page.click('#rc-body button:has-text("مسح")');
    await expect(page.locator('#rc-body table').first().locator('tbody .empty')).toHaveCount(0);
    await expectNoUiError(page);
  });

  test('الانتقال بين المبيعات والمحاسبة عبر القائمة', async ({ page }) => {
    await page.click('.sidebar a[data-view="accounting"]');
    await expect(page.locator('#page-title')).toHaveText('المحاسبة');
    await expect(page.locator('#acc-tabs .tab')).toHaveCount(5);
    await page.click('.sidebar a[data-view="sales"]');
    await expect(page.locator('#page-title')).toHaveText('المبيعات');
    await expect(page.locator('#rc-tabs .tab.active')).toHaveAttribute('data-tab', 'pos');
    await expectNoUiError(page);
  });
});
