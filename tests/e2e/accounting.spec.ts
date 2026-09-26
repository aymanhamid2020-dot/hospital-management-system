import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError, openView } from './views';

/** شاشة المحاسبة: ستة تبويبات — كل تبويب يجمع كل ما يرتبط به */
const TABS = ['overview', 'debtors', 'invoices', 'ledger', 'reports'] as const;
// «المبيعات» شاشة مستقلة في القائمة — تُختبر في sales.spec.ts لا هنا

/** علامة مميّزة لكل تبويب تُثبت أن محتواه هو المعروض */
const MARKERS: Record<(typeof TABS)[number], string> = {
  overview: 'منحنى الإيراد',
  debtors: 'كشف حساب مريض',
  invoices: 'الفواتير',
  ledger: 'الدفتر العام',
  reports: 'التقارير المالية',
};

/** التبويب المعروض فعليًا */
const active = (page: import('@playwright/test').Page) =>
  page.locator('#acc-tabs .tab.active').first();

test.describe('شاشة المحاسبة وتبويباتها 💰', () => {
  test('خمسة تبويبات + نظرة عامة بالملخّص المالي', async ({ page }) => {
    await login(page);
    await openView(page, 'accounting');

    await expect(page.locator('#acc-tabs .tab')).toHaveCount(TABS.length);
    await expect(active(page)).toHaveAttribute('data-tab', 'overview');
    await expect(page.locator('#main .stats .stat').first()).toBeVisible();
    expect(await page.locator('#main .stats .stat').count()).toBeGreaterThanOrEqual(6);
    await expect(page.locator('#acc-tabs .tab').filter({ hasText: 'المدينون' })).toBeVisible();
    await expectNoUiError(page);
  });

  test('كل تبويب يعرض محتواه ولا تتداخل اللوحات', async ({ page }) => {
    await login(page);
    await openView(page, 'accounting');

    for (const tab of TABS) {
      await page.click(`#acc-tabs .tab[data-tab="${tab}"]`);
      await expect(active(page)).toHaveAttribute('data-tab', tab);

      // محتوى التبويب وحده داخل حاوية واحدة، وبلا رسالة فشل عرض
      await expect(page.locator('#acc-body')).toHaveCount(1);
      await expect(page.locator('#acc-body')).not.toHaveText('جارٍ التحميل…');
      await expect(page.locator('#acc-body h3').filter({ hasText: MARKERS[tab] }).first())
        .toBeVisible();
      await expectNoUiError(page);
    }
  });

  test('اختصارات القائمة تفتح التبويب المقابل', async ({ page }) => {
    await login(page);

    const shortcuts: Array<[view: string, tab: string]> = [
      ['accounts', 'overview'],
      ['invoices', 'invoices'],
      ['accounting', 'overview'],
    ];

    for (const [view, tab] of shortcuts) {
      await page.click(`.sidebar a[data-view="${view}"]`);
      await expect(page.locator('#page-title')).toHaveText('المحاسبة');
      await expect(active(page)).toHaveAttribute('data-tab', tab);
      await expectNoUiError(page);
    }
  });

  test('تبويب التقارير: مركز تنزيل تقارير المحاسبة', async ({ page }) => {
    await login(page);
    await openView(page, 'accounting');
    await page.click('#acc-tabs .tab[data-tab="reports"]');

    await expect(page.locator('#acc-body h3').filter({ hasText: 'التقارير المالية' })).toBeVisible();
    await expect(page.locator('#f-rep-patient')).toBeVisible();
    await expect(page.locator('#acc-body button:has-text("تقرير المبيعات PDF")')).toBeVisible();
    await expect(page.locator('#acc-body button:has-text("كشف الرواتب PDF")')).toBeVisible();
    await expect(page.locator('#acc-body button:has-text("كشف حساب مريض PDF")')).toBeVisible();
    await expectNoUiError(page);
  });
});
