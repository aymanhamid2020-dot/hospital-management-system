import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError } from './views';

test.describe('الطوارئ 🚑', () => {
  test('فتح ملف ← منتقي مصنَّف ← طلب ← فاتورة ببنود ← تحصيل', async ({ page }) => {
    await login(page);

    // فتح الشاشة من القائمة الجانبية
    await page.click('.sidebar a[data-view="er"]');
    await expect(page.locator('#page-title')).toHaveText('الطوارئ');
    await expect(page.locator('.er-shell')).toBeVisible();
    await expect(page.locator('.er-list')).toBeVisible();
    await expectNoUiError(page);

    // الشكوى إلزامية: الحفظ بقيم فارغة يرفض ولا يُغلق النافذة
    await page.click('.er-side button:has-text("فتح ملف")');
    await expect(page.locator('#er-npat')).toBeVisible();
    await page.click('#modal-body button:has-text("فتح الملف")');
    await expect(page.locator('#toast')).toContainText('الشكوى');
    await expect(page.locator('#er-ncomp')).toBeVisible();

    // الحفظ بقيمة صحيحة يفتح الملف ويعرض مساحة العمل
    await page.fill('#er-ncomp', 'ألم صدري مفاجئ مع ضيق تنفس');
    await page.click('#modal-body button:has-text("فتح الملف")');
    await expect(page.locator('.er-item.on')).toBeVisible();
    await expect(page.locator('#er-work h3').first()).toContainText('حالة #');

    // المنتقي المصنَّف: شرائح المجموعات + قائمة قابلة للتمرير + بحث
    await expect(page.locator('#er-pick .tp-chip').first()).toBeVisible();
    await expect(page.locator('#er-pick .tp-chip').first()).toContainText('الكل');
    const total = await page.locator('#er-pick .tp-row').count();
    expect(total, 'الدليل غير مُحمَّل داخل المنتقي').toBeGreaterThan(100);

    await page.fill('#er-pick .tp-q', 'CBC');
    await expect.poll(async () => page.locator('#er-pick .tp-row').count())
      .toBeLessThan(total);
    const filtered = await page.locator('#er-pick .tp-row').count();
    expect(filtered).toBeGreaterThan(0);

    // اختيار متعدد يُظهر وسمًا ثم يُضاف إلى الحالة
    await page.click('#er-pick .tp-row >> nth=0');
    await expect(page.locator('#er-pick .tp-tag')).toHaveCount(1);
    await page.click('button:has-text("إضافة الفحوصات المحدَّدة")');
    await expect(page.locator('#er-work table tbody tr')).toHaveCount(1);
    await expect(page.locator('#er-work .pill', { hasText: 'لم يُفوتر' })).toHaveCount(1);

    // فتح فاتورة التحصيل: كشفية + الفحوصات في سطور واحدة
    await page.click('button:has-text("فتح فاتورة التحصيل")');
    await expect(page.locator('.er-tot')).toBeVisible();
    await expect(page.locator('.er-tot').getByText('المتبقي')).toBeVisible();
    await expect(page.locator('#er-method')).toBeVisible();

    // التحصيل يفتح بوابة المختبر
    await page.click('button:has-text("💳 تحصيل")');
    await expect(page.locator('.er-badges').getByText('مدفوعة')).toBeVisible();
    await expect(page.locator('.er-tot').getByText('المتبقي')).toContainText('0');
    await expectNoUiError(page);
  });
});
