import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError, openView } from './views';

test.describe('شاشة المبيعات المستقلة 🛒', () => {
  test('المبيعات لم تعد تبويبًا في المحاسبة بل شاشة في القائمة', async ({ page }) => {
    await login(page);

    // 1) رابط مستقل في القائمة وبلا data-tab (لم يعد اختصارًا لتبويب)
    const link = page.locator('.sidebar a[data-view="sales"]');
    await expect(link).toHaveCount(1);
    await expect(link).toContainText('المبيعات');
    await expect(link).not.toHaveAttribute('data-tab', /.*/);

    // 2) فتحه يعرض شاشة المبيعات بذاتها (لا شريط تبويبات المحاسبة)
    await openView(page, 'sales');
    await expect(page.locator('#page-title')).toHaveText('المبيعات');
    await expect(page.locator('#acc-tabs')).toHaveCount(0);
    await expect(page.locator('#main h3', { hasText: 'سجل المبيعات' })).toBeVisible();
    await expect(page.locator('#main .pill', { hasText: 'شاشة مستقلة' })).toBeVisible();
    // الرابط مميّز في القائمة
    await expect(link).toHaveClass(/active/);
    await expectNoUiError(page);

    // 3) شاشة المحاسبة صارت بخمسة تبويبات بلا «المبيعات»
    await page.click('.sidebar a[data-view="accounting"]');
    await expect(page.locator('#page-title')).toHaveText('المحاسبة');
    await expect(page.locator('#acc-tabs .tab')).toHaveCount(5);
    await expect(page.locator('#acc-tabs .tab', { hasText: 'المبيعات' })).toHaveCount(0);
    await expect(page.locator('#acc-tabs .tab.active')).toHaveAttribute('data-tab', 'overview');
    await expectNoUiError(page);
  });

  test('فلاتر السجل والتسديد تعمل في الشاشة المستقلة', async ({ page }) => {
    await login(page);
    await openView(page, 'sales');

    await expect(page.locator('#f-acc-period')).toBeVisible();
    await expect(page.locator('#f-acc-method')).toBeVisible();
    await expect(page.locator('#f-acc-status')).toBeVisible();
    await expect(page.locator('#main table')).toBeVisible();

    // فلترة بفترة بلا عمليات: رسالة فراغ بدل صفوف قديمة
    await page.fill('#f-acc-period', '2099-01');
    await page.click('#main button:has-text("تطبيق")');
    await expect(page.locator('#page-title')).toHaveText('المبيعات');
    await expect(page.locator('#main table tbody .empty'))
      .toHaveText('لا توجد مبيعات في هذه الفترة');

    // مسح الفلاتر يعيد السجل
    await page.click('#main button:has-text("مسح")');
    await expect(page.locator('#main h3', { hasText: 'سجل المبيعات' })).toBeVisible();
    await expectNoUiError(page);
  });

  test('زر الذهاب للمحاسبة من شاشة المبيعات', async ({ page }) => {
    await login(page);
    await openView(page, 'sales');
    await page.click('#main button:has-text("الذهاب للمحاسبة")');
    await expect(page.locator('#page-title')).toHaveText('المحاسبة');
    await expect(page.locator('#acc-tabs .tab.active')).toHaveAttribute('data-tab', 'overview');
    await expectNoUiError(page);
  });
});
