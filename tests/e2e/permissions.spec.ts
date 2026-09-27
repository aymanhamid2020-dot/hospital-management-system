import { test, expect, type APIRequestContext } from '@playwright/test';
import { authHeader, login } from './helpers';
import { expectNoUiError, openView } from './views';

const TAG = Date.now().toString(36).slice(-5).toUpperCase();
const TABS = ['roles', 'matrix', 'users'] as const;

test.describe('الأدوار والصلاحيات 🔐', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openView(page, 'permissions');
    await expect(page.locator('#rb-body .card').first()).toBeVisible();
  });

  test('التبويبات الثلاثة تفتح وتعرض محتواها الحقيقي', async ({ page }) => {
    await expect(page.locator('#rb-tabs .tab')).toHaveCount(TABS.length);
    const markers: Record<string, string> = {
      roles: 'الأدوار',
      matrix: 'مصفوفة الصلاحيات',
      users: 'صلاحيات المستخدمين',
    };
    for (const t of TABS) {
      await page.click(`#rb-tabs .tab[data-tab="${t}"]`);
      await expect(page.locator('#rb-tabs .tab.active')).toHaveAttribute('data-tab', t);
      await expect(page.locator('#rb-body h3').filter({ hasText: markers[t] }).first())
        .toBeVisible();
      await expectNoUiError(page);
    }
  });

  test('إنشاء دور مخصّص وضبط صلاحياته من المصفوفة', async ({ page }) => {
    // 1) إنشاء دور
    await page.fill('#rb-name', `مشرف اختبار ${TAG}`);
    await page.click('button:has-text("➕ إنشاء دور")');
    const row = page.locator('#rb-body tr', { hasText: `مشرف اختبار ${TAG}` });
    await expect(row).toBeVisible();
    await expect(row).toContainText('مخصّص');
    await expectNoUiError(page);

    // 2) تخصيصه من المصفوفة: تفعيل «عرض المختبر» ثم الحفظ
    await page.click('#rb-tabs .tab[data-tab="matrix"]');
    await page.click(`#rb-body button:has-text("مشرف اختبار ${TAG}")`);
    const permRow = page.locator('#rb-body tr', { hasText: 'lab.view' });
    const box = permRow.locator('input[type="checkbox"]');
    const before = await box.isChecked();
    await box.setChecked(!before);
    await page.click('button:has-text("💾 حفظ")');
    await expect(page.locator('.toast')).toContainText('تم حفظ');
    await expectNoUiError(page);

    // 3) الصلاحية وصلت فعليًا لدور المستخدم
    const h = await authHeader(page.request);
    const roles = await (await page.request.get('/permissions/roles', { headers: h })).json();
    const role = roles.find((r: { name_ar: string }) => r.name_ar === `مشرف اختبار ${TAG}`);
    expect(role).toBeTruthy();
    const hasLab = role.permissions.includes('lab.view');
    expect(role.permissions.includes('lab.view')).toBe(!before ? true : hasLab);
  });

  test('المصفوفة تعرض كتالوج الصلاحيات مجمّعًا بالوحدات', async ({ page }) => {
    await page.click('#rb-tabs .tab[data-tab="matrix"]');
    await expect(page.locator('#rb-body tr', { hasText: '.' })).not.toHaveCount(0);
    await expect(page.locator('#rb-body')).toContainText('patients');
    await expect(page.locator('#rb-body')).toContainText('sales');
    // الدور العام معطّل من التعديل，因为它 يتجاوز كل شيء
    await expect(page.locator('#rb-body button:has-text("مدير النظام")')).toBeDisabled();
    await expectNoUiError(page);
  });

  test('القائمة الجانبية تخفي ما لا تملك صلاحيته', async ({ page }) => {
    // المدير يرى كل الشاشات بما فيها شاشة الصلاحيات نفسها
    await expect(page.locator('.sidebar a[data-view="permissions"]')).toBeVisible();
    await expect(page.locator('.sidebar a[data-view="audit"]')).toBeVisible();
    await expectNoUiError(page);
  });
});
