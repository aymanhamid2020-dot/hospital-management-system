import { test, expect } from '@playwright/test';
import { authHeader, login } from './helpers';
import { expectNoUiError } from './views';

/** يفتح بطاقة حسابات البوابة داخل شاشة «الجودة والموارد» */
async function openPortalAccounts(page: import('@playwright/test').Page) {
  await login(page);
  await page.click('.sidebar a[data-view="governance"]');
  await page.click('.stat:has-text("حسابات بوابة المريض")');
  await expect(page.locator('#ops-table')).toBeVisible({ timeout: 15_000 });
}

/** معرّف حساب البوابة من اسمه عبر API (للتحقق والتنظيف) */
async function accountIdByName(request: any, username: string): Promise<number> {
  const res = await request.get('/patient-portal/accounts', { headers: await authHeader(request) });
  expect(res.ok(), 'تعذّر قراءة قائمة حسابات البوابة').toBeTruthy();
  const hit = (await res.json()).find((a: any) => a.username === username);
  return hit ? (hit.id as number) : 0;
}

test.describe('بوابة المريض 👤', () => {
  test('صفحة البوابة تشرح أين يُنشأ الحساب', async ({ page }) => {
    await page.goto('/patient-portal.html');
    await expect(page.locator('#login h2')).toContainText('بوابة المريض');
    await expect(page.locator('#login p').first())
      .toContainText('يُنشئه موظف الاستقبال أو المدير');
    // المسار المذكور يجب أن يطابق موضع البطاقة الفعلي في الشريط الجانبي
    await expect(page.locator('#login p').first()).toContainText('الجودة والموارد');
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();

    // دخول خاطئ يعرض رسالة عربية ولا يفتح اللوحة
    await page.fill('#username', 'no_such_user_xyz');
    await page.fill('#password', 'WrongPass123!');
    await page.click('button:has-text("تسجيل الدخول")');
    await expect(page.locator('#error')).toContainText('غير صحيحة', { timeout: 15_000 });
    await expect(page.locator('#dashboard')).toBeHidden();
  });

  test('المدير ينشئ حسابًا لمريض ويُعطّله', async ({ page, request }) => {
    await openPortalAccounts(page);
    // اسم فريد لكل تشغيل: الخادم يعمل على قاعدة العرض والاسم فريد على مستوى النظام
    const username = `e2e_portal_${Date.now().toString(36)}`;
    let accountId = 0;

    try {
      await expect(page.locator('.toolbar h3')).toContainText('حسابات بوابة المريض');
      // في قاعدة بلا حسابات يظهر «لا توجد سجلات» — لا صفوف وهمية
      if (await page.locator('#ops-table .empty').count() === 0) {
        await expect(page.locator('#ops-table tbody tr').first()).toContainText(/نشط|معطّل/);
      }

      await page.click('button:has-text("إضافة")');
      // العنوان في #modal-title والجسم في #modal-body (openModal يفصلهما)
      await expect(page.locator('#modal-title')).toContainText('إنشاء حساب بوابة مريض');
      await expect(page.locator('#modal-body')).toContainText('لا تسجيل ذاتي');
      await expect(page.locator('#pa-patient')).toBeVisible();
      await expect(page.locator('#pa-user')).toBeVisible();
      await expect(page.locator('#pa-pass')).toBeVisible();
      // القائمة تعرض المرضى بلا حساب فقط، فلا خيار «كل المرضى لديهم حسابات»
      expect(await page.locator('#pa-patient option[value=""]').count(),
        'كل المرضى لديهم حسابات بوابة').toBe(0);

      // التحقق محليًا قبل الإرسال: كلمة مرور قصيرة تُرفض ولا تُغلق النافذة
      const first = await page.locator('#pa-patient option').first().getAttribute('value');
      await page.selectOption('#pa-patient', first!);
      await page.fill('#pa-user', username);
      await page.fill('#pa-pass', 'short');
      await page.click('button:has-text("حفظ الحساب")');
      await expect(page.locator('.toast')).toContainText('8 أحرف فأكثر');
      await expect(page.locator('#modal-back')).toHaveClass(/show/);

      // بكلمة صحيحة يُنشأ الحساب ويُغلق النموذج وتُعاد القائمة
      await page.fill('#pa-pass', 'E2ePortal123!');
      await page.click('button:has-text("حفظ الحساب")');
      await expect(page.locator('.toast')).toContainText('أُنشئ حساب البوابة');
      await expect(page.locator('#modal-back')).not.toHaveClass(/show/);

      const acc = page.locator('#ops-table tbody tr', { hasText: username });
      await expect(acc).toHaveCount(1);
      await expect(acc).toContainText('نشط');
      await expect(acc).toContainText('لم يدخل بعد');   // لم يسجّل المريض دخولًا بعد
      await expect(acc.locator('button:has-text("كلمة المرور")')).toBeVisible();
      await expect(acc.locator('button:has-text("تعطيل")')).toBeVisible();

      accountId = await accountIdByName(request, username);
      expect(accountId, 'الحساب لم يُحفظ في قاعدة البيانات').toBeGreaterThan(0);

      // تعطيل الدخول: تأكيد المتصفح ثم PATCH ثم إعادة العرض
      page.once('dialog', d => d.accept());
      await acc.locator('button:has-text("تعطيل")').click();
      await expect(page.locator('.toast')).toContainText('الحساب');
      await expect(page.locator('#ops-table tbody tr', { hasText: username }))
        .toContainText('معطّل');
      await expectNoUiError(page);
    } finally {
      // لا تُخلَّف بيانات تجريبية في قاعدة العرض
      if (accountId) {
        const del = await request.delete(`/patient-portal/accounts/${accountId}`,
          { headers: await authHeader(request) });
        expect(del.status(), 'تعذّر تنظيف حساب البوابة التجريبي').toBe(204);
      }
    }
  });
});
