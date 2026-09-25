import { test, expect } from '@playwright/test';
import { login, openDoctors } from './helpers';

/**
 * لقطات رسمية لصفحة الأطباء — تُحدَّث في docs/screenshots/doctors-e2e/
 * تُشغَّل: npm run screenshots  (الخادم على 127.0.0.1:8001)
 */
const OUT = 'docs/screenshots/doctors-e2e';

test.describe('لقطات صفحة الأطباء 📸', () => {
  test('01 — قائمة الأطباء بالوضع الداكن', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await login(page);
    await openDoctors(page);

    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('dark');
    await page.screenshot({ path: `${OUT}/01-doctors-dark.png`, fullPage: true });
  });

  test('02 — نافذة التقرير المقارن', async ({ page }) => {
    await login(page);
    await openDoctors(page);
    await page.click('#main button:has-text("أداء الشهر")');

    await expect(page.locator('#modal-back')).toHaveClass(/show/);
    await expect(page.locator('#modal-title')).toContainText('أداء جميع الأطباء');
    await expect(page.locator('#pm-body table tbody tr').first()).toBeVisible();
    await page.screenshot({ path: `${OUT}/02-compare.png`, fullPage: true });
  });

  test('03 — نافذة نوبات العمل الأسبوعية', async ({ page }) => {
    await login(page);
    await openDoctors(page);
    await page.locator('#tbl tbody tr').first()
      .locator('button[title="نوبات العمل"]').click();

    await expect(page.locator('#modal-back')).toHaveClass(/show/);
    await expect(page.locator('#modal-body tbody tr')).toHaveCount(7);
    await page.screenshot({ path: `${OUT}/03-schedule.png`, fullPage: true });
  });

  test('04 — نافذة تقرير الأداء الشهري', async ({ page }) => {
    await login(page);
    await openDoctors(page);
    await page.locator('#tbl tbody tr').first()
      .locator('button:has-text("تقرير")').click();

    await expect(page.locator('#modal-back')).toHaveClass(/show/);
    await expect(page.locator('#modal-title')).toContainText('تقرير الأداء الشهري');
    await expect(page.locator('#rp-body .stat').first()).toBeVisible();
    await page.screenshot({ path: `${OUT}/04-report.png`, fullPage: true });
  });
});
