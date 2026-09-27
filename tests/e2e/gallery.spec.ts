import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError, openView } from './views';

/**
 * 📸 معرض لقطات الشاشات الأساسية — يُحدَّث في docs/screenshots/gallery/
 * يُشغَّل: npx playwright test tests/e2e/gallery.spec.ts (الخادم على 8001)
 */
const OUT = 'docs/screenshots/gallery';

const SHOTS: Array<[file: string, view: Parameters<typeof openView>[1]]> = [
  ['01-dashboard', 'dashboard'],
  ['02-patients', 'patients'],
  ['03-appointments', 'appointments'],
  ['04-pharmacy', 'pharmacy'],
  ['05-inventory', 'inventory'],
  ['06-lab', 'lab'],
  ['07-invoices', 'invoices'],
  ['08-clinical', 'clinical'],
  ['09-accounting', 'accounting'],
];

test.describe('معرض لقطات الشاشات 🖼️', () => {
  for (const [file, view] of SHOTS) {
    test(`${file} — ${view}`, async ({ page }) => {
      await login(page);
      await openView(page, view);
      await expectNoUiError(page);
      await page.screenshot({ path: `${OUT}/${file}.png`, fullPage: true });
    });
  }

  /* شاشة الطوارئ: تُصوَّر على حالة مفتوحة إن وُجدت حتى تظهر مساحة العمل
     والمنتقي المصنَّف والفاتورة، وإلا كافية بقائمة الحالات */
  test('10-emergency — حالة مفتوحة بالمنتقي والفاتورة', async ({ page }) => {
    await login(page);
    await openView(page, 'er');
    await expectNoUiError(page);
    if (await page.locator('.er-item').count()) {
      await page.locator('.er-item').first().click();
      await expect(page.locator('#er-work h3').first()).toContainText('حالة #');
      await expectNoUiError(page);
    }
    await page.screenshot({ path: `${OUT}/10-emergency.png`, fullPage: true });
  });
});
