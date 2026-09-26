import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError } from './views';

/** يفتح شاشة الأطباء وينقر «🗂️ الملف» لأول صف */
async function openFirstDoctorChart(page: import('@playwright/test').Page) {
  await page.click('#tbl tbody tr:first-child button:has-text("الملف")');
  await expect(page.locator('#doc-tabs')).toBeVisible({ timeout: 15_000 });
}

test.describe('ملف الطبيب 🩺', () => {
  test('التبويبات الخمسة تفتح وتعرض المحتوى', async ({ page }) => {
    await login(page);
    await page.click('.sidebar a[data-view="doctors"]');
    await expect(page.locator('#tbl tbody tr').first()).toBeVisible();

    // الجدول يعرض عمودي الدرجة وسعر الكشف
    await expect(page.locator('#tbl thead th').filter({ hasText: 'الدرجة' })).toBeVisible();
    await expect(page.locator('#tbl thead th').filter({ hasText: 'سعر الكشف' })).toBeVisible();

    await openFirstDoctorChart(page);

    for (const label of ['الملف المهني', 'المواعيد والجداول', 'الصلاحيات والتوقيع',
                         'الحسابات والعمولات', 'الأداء والإحصائيات']) {
      await expect(page.locator('#doc-tabs .tab').filter({ hasText: label })).toBeVisible();
    }

    // (1) الملف المهني
    await expect(page.locator('#doc-body h3').filter({ hasText: 'أوقات الكشف' })).toBeVisible();
    await expect(page.locator('#doc-body').getByText('الدرجة العلمية')).toBeVisible();

    // (2) المواعيد والجداول
    await page.click('#doc-tabs .tab:has-text("المواعيد والجداول")');
    await expect(page.locator('#doc-body h3').filter({ hasText: 'أوقات الدوام' })).toBeVisible();
    await expect(page.locator('#doc-body h3').filter({ hasText: 'المناوبات' })).toBeVisible();
    await expect(page.locator('#doc-body h3').filter({ hasText: 'الإجازات' })).toBeVisible();
    await expect(page.locator('#doc-body h3').filter({ hasText: 'حظر الحجز' })).toBeVisible();

    // (3) الصلاحيات والتوقيع
    await page.click('#doc-tabs .tab:has-text("الصلاحيات والتوقيع")');
    await expect(page.locator('#doc-body h3').filter({ hasText: 'صلاحيات النظام' })).toBeVisible();
    await expect(page.locator('#pm-view_emergency')).toBeVisible();
    await expect(page.locator('#up-signature')).toBeAttached();

    // (4) الحسابات والعمولات
    await page.click('#doc-tabs .tab:has-text("الحسابات والعمولات")');
    await expect(page.locator('#doc-body .stat').filter({ hasText: 'إجمالي الإيراد' })).toBeVisible();
    await expect(page.locator('#doc-body').getByText('بنود العمولة')).toBeVisible();

    // (5) الأداء والإحصائيات
    await page.click('#doc-tabs .tab:has-text("الأداء والإحصائيات")');
    await expect(page.locator('#doc-body .stat').filter({ hasText: 'مرضى جدد' })).toBeVisible();
    await expect(page.locator('#doc-body .stat').filter({ hasText: 'نسبة الإلغاء' })).toBeVisible();

    // لا رسالة فشل في أي تبويب
    await expect(page.locator('#doc-body .empty[style*="dc3545"]')).toHaveCount(0);
    await expectNoUiError(page);
  });

  test('حفظ الملف المهني يغيّر الدرجة العلمية', async ({ page }) => {
    await login(page);
    await page.click('.sidebar a[data-view="doctors"]');
    await openFirstDoctorChart(page);

    const before = await page.locator('#dp-rank').inputValue();
    const next = before === 'استشاري' ? 'أخصائي' : 'استشاري';
    await page.selectOption('#dp-rank', next);
    await page.fill('#dp-branch', 'فرع الاختبار');
    await page.click('button:has-text("حفظ الملف المهني")');
    await expect(page.locator('.toast')).toContainText('حُفظ الملف المهني');

    // النافذة تعيد القراءة من الخادم
    await expect.poll(async () =>
      await page.locator('#dp-rank').inputValue(), { timeout: 10_000 }).toBe(next);
    await expect(page.locator('#dp-branch')).toHaveValue('فرع الاختبار');
    await expectNoUiError(page);
  });
});
