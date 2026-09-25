import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError } from './views';

/** يفتح شاشة المرضى ثم نافذة 🗂️ ملف المريض لأول صف */
async function openChart(page: import('@playwright/test').Page) {
  await login(page);
  await page.click('.sidebar a[data-view="patients"]');
  await expect(page.locator('#main h3').filter({ hasText: 'المرضى' })).toBeVisible();
  await page.locator('#tbl tbody tr').first().locator('button:has-text("الملف")').first().click();
  await expect(page.locator('#modal-back')).toHaveClass(/show/);
  await expect(page.locator('#chart-tabs .tab')).toHaveCount(6);
}

/** الأقسام الستة وعناوين محتواها */
const SECTIONS = [
  ['الملف الشخصي', 'البيانات الشخصية'],
  ['السجل الطبي', 'العلامات الحيوية'],
  ['المواعيد والزيارات', 'سجل الزيارات السابقة'],
  ['الفحوصات والوصفات', 'المختبر والأشعة'],
  ['الحسابات والتأمين', 'مطالبات التأمين'],
  ['المرفقات', 'المرفقات والوثائق'],
] as const;

test.describe('ملف المريض 🗂️', () => {
  test('ستة أقسام تُفتح من جدول المرضى', async ({ page }) => {
    await openChart(page);

    for (const [tab, heading] of SECTIONS) {
      await expect(page.locator('#chart-tabs .tab', { hasText: tab })).toHaveCount(1);
      await page.click(`#chart-tabs .tab:has-text("${tab}")`);
      await expect(page.locator('#chart-body h3').filter({ hasText: heading }).first())
        .toBeVisible();
      // لا رسالة فشل عرض في أي قسم
      await expect(page.locator('#chart-body .empty[style*="dc3545"]')).toHaveCount(0);
    }

    // حقول الملف الشخصي والتأمين موجودة في تبويبه
    await page.click('#chart-tabs .tab:has-text("الملف الشخصي")');
    for (const f of ['nationality', 'smoking_status', 'emergency_contact_name',
                     'emergency_contact_phone', 'insurance_grade', 'insurance_copay',
                     'allergies', 'medical_warnings', 'chronic_conditions']) {
      await expect(page.locator(`[data-pf="${f}"]`)).toBeVisible();
    }
    await expectNoUiError(page);
  });

  test('تسجيل علامة حيوية من شاشة الملف', async ({ page }) => {
    await openChart(page);
    await page.click('#chart-tabs .tab:has-text("السجل الطبي")');
    await expect(page.locator('#chart-body h3').filter({ hasText: 'العلامات الحيوية' })).toBeVisible();

    await page.click('#chart-body summary:has-text("تسجيل قياس جديد")');
    await page.fill('#v-sys', '128');
    await page.fill('#v-dia', '82');
    await page.fill('#v-temp', '37.1');
    await page.fill('#v-pulse', '75');
    await page.fill('#v-weight', '78');
    await page.fill('#v-height', '174');
    await page.click('#chart-body button:has-text("حفظ القياس")');

    // الصف الجديد يظهر بضغطه وكمرافقه محسوبة
    const row = page.locator('#chart-body table tbody tr', { hasText: '128/82' }).first();
    await expect(row).toBeVisible();
    await expect(row).toContainText('25.8');   // BMI = 78 / 1.74²
    await expectNoUiError(page);
  });
});

