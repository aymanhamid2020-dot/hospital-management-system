import { test, expect, type Page } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError, openView } from './views';

const TAG = Date.now().toString(36).slice(-5).toUpperCase();
const USERNAME = `uadm${TAG}`;

/** ترتيب عناصر القائمة الجانبية: العناوين كـ`#النص` والشاشات بمعرّفها */
async function sidebarOrder(page: Page): Promise<string[]> {
  return page.$$eval('.sidebar .nav-title, .sidebar a[data-view]',
    els => els.map(e => e.getAttribute('data-view') || `#${(e.textContent || '').trim()}`));
}

test.describe('إدارة المستخدمين 👤', () => {
  test('القسم الجديد يضم الشاشتين ويُخرجهما من مجموعتهما السابقة', async ({ page }) => {
    await login(page);
    const order = await sidebarOrder(page);
    const iHr = order.indexOf('#الموارد البشرية والإدارة');
    const iGroup = order.indexOf('#إدارة المستخدمين');
    const iNext = order.indexOf('#النظام والحوكمة');
    expect(iHr).toBeGreaterThan(-1);
    expect(iGroup).toBeGreaterThan(iHr);
    expect(iNext).toBe(iGroup + 3);
    /* محتوى القسم: الأدوار ثم المستخدمون، ولا شيء منهما في المجموعة القديمة */
    expect(order.slice(iGroup + 1, iNext)).toEqual(['permissions', 'users']);
    expect(order.slice(iHr + 1, iGroup)).toEqual(['hr', 'governance']);
    await expectNoUiError(page);
  });

  test('شاشة المستخدمين تقرأ أدوارها من المصفوفة وتعرض زر الحذف', async ({ page }) => {
    await login(page);
    await openView(page, 'users');
    await expect(page.locator('#main table tbody tr').first()).toBeVisible();
    await expect(page.locator('#main')).toContainText('مصفوفة الأدوار والصلاحيات');

    /* نموذج الإنشاء: كل الأدوار ما عدا المدير (لا يُمنح عند الإنشاء) */
    const addOpts = await page.locator('#u-role option').allTextContents();
    expect(addOpts.length).toBeGreaterThanOrEqual(9);
    expect(addOpts.some(t => t.includes('مدير النظام'))).toBe(false);
    expect(addOpts.some(t => t.includes('موظف استقبال'))).toBe(true);

    /* أي صف حذفه مفعّل ⇒ قائمته تشمل «مدير النظام» (رقمنة من الشاشة) */
    const row = page.locator('#main table tbody tr')
      .filter({ has: page.locator('button:not([disabled]):has-text("حذف")') }).first();
    await expect(row).toBeVisible();
    const rowOpts = await row.locator('select option').allTextContents();
    expect(rowOpts.some(t => t.includes('مدير النظام'))).toBe(true);

    /* حساب المدير نفسه: الحذف معطّل */
    const adminRow = page.locator('#main table tbody tr')
      .filter({ has: page.locator('td', { hasText: /^admin$/ }) }).first();
    await expect(adminRow).toBeVisible();
    await expect(adminRow.locator('button:has-text("حذف")')).toBeDisabled();
    await expectNoUiError(page);
  });

  test('إنشاء مستخدم بدور من المصفوفة ثم حذفه من الشاشة', async ({ page }) => {
    await login(page);
    await openView(page, 'users');

    await page.click('.addbox summary');
    await page.fill('#u-username', USERNAME);
    await page.fill('#u-fullname', `مستخدم واجهة ${TAG}`);
    await page.fill('#u-email', `${USERNAME}@test.com`);
    await page.selectOption('#u-role', 'nurse');
    await page.fill('#u-pass', 'Secret123');
    await page.click('button:has-text("إنشاء الحساب")');

    const row = page.locator('#main table tbody tr').filter({ hasText: USERNAME });
    await expect(row).toHaveCount(1);
    await expect(row.locator('select')).toHaveValue('nurse');

    page.once('dialog', d => d.accept());
    await row.locator('button:has-text("حذف")').click();
    await expect(page.locator('#main table tbody tr').filter({ hasText: USERNAME }))
      .toHaveCount(0, { timeout: 15_000 });
    await expect(page.locator('.toast').filter({ hasText: 'تم حذف المستخدم' })).toHaveCount(1);
    await expectNoUiError(page);
  });
});
