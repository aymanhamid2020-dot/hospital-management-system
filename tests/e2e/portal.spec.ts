import { test, expect } from '@playwright/test';
import { login } from './helpers';
import { expectNoUiError } from './views';

/** يفتح شاشة «الرعاية والتشغيل» ثم بطاقة حسابات البوابة */
async function openPortalAccounts(page: import('@playwright/test').Page) {
  await login(page);
  await page.click('.sidebar a[data-view="clinical"]');
  await page.click('.stat:has-text("حسابات بوابة")');
  await expect(page.locator('#ops-table')).toBeVisible({ timeout: 15_000 });
}

test.describe('بوابة المريض 👤', () => {
  test('صفحة البوابة تشرح أين يُنشأ الحساب', async ({ page }) => {
    await page.goto('/patient-portal.html');
    await expect(page.locator('#login h2')).toContainText('بوابة المريض');
    await expect(page.locator('#login p').first())
      .toContainText('يُنشئه موظف الاستقبال أو المدير');
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();

    // دخول خاطئ يعرض رسالة عربية ولا يفتح اللوحة
    await page.fill('#username', 'no_such_user_xyz');
    await page.fill('#password', 'WrongPass123!');
    await page.click('button:has-text("تسجيل الدخول")');
    await expect(page.locator('#error')).toContainText('غير صحيحة', { timeout: 15_000 });
    await expect(page.locator('#dashboard')).toBeHidden();
  });

  test('المدير ينشئ حسابًا للمرضى', async ({ page }) => {
    await openPortalAccounts(page);

    const row = page.locator('#ops-table tbody tr').first();
    await expect(row).toContainText('—');

    await page.click('button:has-text("إضافة")');
    await expect(page.locator('#modal-body')).toContainText('إنشاء حساب بوابة مريض');
    await expect(page.locator('#pa-patient')).toBeVisible();
    await expect(page.locator('#pa-user')).toBeVisible();
    await expect(page.locator('#pa-pass')).toBeVisible();

    // التحقق محليًا: كلمة مرور قصيرة تُرفض قبل الإرسال
    const first = await page.locator('#pa-patient option').first().getAttribute('value');
    await page.selectOption('#pa-patient', first!);
    await page.fill('#pa-user', 'e2e_portal');
    await page.fill('#pa-pass', 'short');
    await page.click('button:has-text("حفظ الحساب")');
    await expect(page.locator('.toast')).toContainText('8 أحرف فأكثر');
    await expect(page.locator('#modal-back')).toHaveClass(/show/);

    // بكلمة صحيحة يُنشأ الحساب ويُغلق النموذج
    await page.fill('#pa-pass', 'E2ePortal123!');
    await page.click('button:has-text("حفظ الحساب")');
    await expect(page.locator('.toast')).toContainText('أُنشئ حساب البوابة');
    await expect(page.locator('#modal-back')).not.toHaveClass(/show/);
    await expect(page.locator('#ops-table')).toContainText('e2e_portal');

    // صف الحساب يعرض زرّي كلمة المرور والتعطيل
    const acc = page.locator('#ops-table tbody tr', { hasText: 'e2e_portal' });
    await expect(acc.locator('button:has-text("كلمة المرور")')).toBeVisible();
    await expect(acc.locator('button:has-text("تعطيل")')).toBeVisible();
    await expectNoUiError(page);
  });
});
