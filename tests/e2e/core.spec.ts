import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError, openView } from './views';

test.describe('الشاشات الأساسية 🧭', () => {
  test('لوحة التحكم: بطاقات الإحصاء وتوزيع المواعيد', async ({ page }) => {
    await login(page);

    await expect(page.locator('#page-title')).toHaveText('لوحة التحكم');
    await expect(page.locator('#main .stats .stat').first()).toBeVisible();
    await expect(page.locator('#main h3').filter({ hasText: 'توزيع المواعيد حسب الحالة' })).toBeVisible();
    await expectNoUiError(page);
  });

  test('المرضى: الجدول والبحث الفوري', async ({ page }) => {
    await login(page);
    await openView(page, 'patients');

    const rows = page.locator('#tbl tbody tr');
    expect(await rows.count()).toBeGreaterThan(0);

    // بحث بلا نتائج يخفي كل الصفوف، والحذف يعيدها
    await page.fill('#q', 'نص غير موجود-xyz');
    await expect(page.locator('#tbl tbody tr:visible')).toHaveCount(0);
    await page.fill('#q', '');
    expect(await page.locator('#tbl tbody tr:visible').count()).toBeGreaterThan(0);
    await expectNoUiError(page);
  });

  test('المواعيد: الفلترة بالحالة', async ({ page }) => {
    await login(page);
    await openView(page, 'appointments');

    // body يُملأ بعد إظهار البطاقة (loadAppts غير متزامن) — انتظر الصفوف
    await expect(page.locator('#appt-body tr').first()).toBeVisible();

    // كل صف معروض يحمل الحالة المختارة بعد إعادة التحميل (الخلاية = .pill.completed)
    await page.selectOption('#flt-status', 'completed');
    await expect.poll(async () => {
      const total = await page.locator('#appt-body tr td:nth-child(6) .pill').count();
      const done = await page.locator('#appt-body tr td:nth-child(6) .pill.completed').count();
      return total > 0 && total === done;
    }, { timeout: 10_000 }).toBe(true);
    await expectNoUiError(page);
  });

  test('الصيدلية: عدّاد الأدوية وجدول المخزون', async ({ page }) => {
    await login(page);
    await openView(page, 'pharmacy');

    await expect(page.locator('#main h3').filter({ hasText: 'مخزون الأدوية' })).toBeVisible();
    const count = Number(await page.locator('#ph-count').innerText());
    expect(count).toBeGreaterThan(0);
    await expectNoUiError(page);
  });

  test('المخزون: بطاقات القيمة والحركات', async ({ page }) => {
    await login(page);
    await openView(page, 'inventory');

    expect(await page.locator('#main .stats .stat').count()).toBeGreaterThanOrEqual(6);
    await expect(page.locator('#main h3').filter({ hasText: 'حركات المخزون' })).toBeVisible();
    await expectNoUiError(page);
  });

  test('تنقّل سريع بين خمس شاشات دون تداخل محتوى', async ({ page }) => {
    await login(page);

    for (const view of ['patients', 'pharmacy', 'inventory', 'appointments', 'dashboard'] as const) {
      await openView(page, view);
      await expectNoUiError(page);
    }
    // آخر شاشة فتحت هي المعروضة فعليًا (يمنع سلوك الكتابة فوق المتفاوتة السرعة)
    await expect(page.locator('#page-title')).toHaveText('لوحة التحكم');
    await expect(page.locator('#main h3').filter({ hasText: 'توزيع المواعيد حسب الحالة' })).toBeVisible();
  });
});
