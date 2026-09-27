import { test, expect, type Page } from '@playwright/test';
import { authHeader, login } from './helpers';
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

  test('الدور المعطّل لا يُسند عند الإنشاء ولا يُسقط من صف حامله', async ({ page, request }) => {
    const h = await authHeader(request);
    /* 1) دور مخصّص ثم تعطيله */
    const created = await (await request.post('/permissions/roles', {
      headers: h, data: { name_ar: `دور معطّل ${TAG}` } })).json();
    expect(created.key, 'تعذّر إنشاء الدور').toBeTruthy();
    const off = await request.put(`/permissions/roles/${created.id}`,
      { headers: h, data: { is_active: false } });
    expect(off.ok()).toBeTruthy();

    /* 2) مستخدم يحمل ذلك الدور */
    const uname = `off${TAG}`;
    const reg = await request.post('/auth/register', {
      headers: h,
      data: {
        username: uname, email: `${uname}@t.com`,
        full_name: `موظف بدور معطّل ${TAG}`, password: 'Secret123', role: created.key,
      },
    });
    expect(reg.ok(), `تعذّر إنشاء حامل الدور: ${await reg.text()}`).toBeTruthy();
    const uid = (await reg.json()).id as number;

    try {
      await login(page);
      await openView(page, 'users');
      await expect(page.locator('#main table tbody tr').first()).toBeVisible();

      /* نموذج الإنشاء: الدور المعطّل خارج القائمة */
      const addValues = await page.locator('#u-role option').evaluateAll(
        els => els.map(e => (e as HTMLOptionElement).value));
      expect(addValues).not.toContain(created.key);

      /* حامله: يبقى ظاهرًا بدوره وموسومًا ⛔ */
      const row = page.locator('#main table tbody tr').filter({ hasText: uname });
      await expect(row).toHaveCount(1);
      const sel = row.locator('select');
      await expect(sel).toHaveValue(created.key);
      await expect(sel.locator('option:checked')).toContainText('⛔');
      /* والشريط يعلن عدد الأدوار المتاحة منفصلًا عن المعطّلة */
      await expect(page.locator('#main')).toContainText('متاحًا');
      await expectNoUiError(page);
    } finally {
      await request.delete(`/auth/users/${uid}`, { headers: h });
      await request.delete(`/permissions/roles/${created.id}`, { headers: h });
    }
  });

  test('جدول الأدوار يفتح شاشة المستخدمين مُصفّاة على الدور نفسه', async ({ page, request }) => {
    const h = await authHeader(request);
    /* نختار دورًا له مستخدمون فعلًا (يختلف باختلاف البذور) */
    const users = await (await request.get('/auth/users', { headers: h })).json();
    const roles = await (await request.get('/permissions/roles', { headers: h })).json();
    const keys = new Set<string>(roles.map((r: { key: string }) => r.key));
    const counts = new Map<string, number>();
    for (const u of users as Array<{ role: string }>) {
      if (u.role !== 'admin') counts.set(u.role, (counts.get(u.role) || 0) + 1);
    }
    const picked = [...counts.entries()]
      .filter(([k]) => keys.has(k))
      .sort((a, b) => b[1] - a[1])[0];
    expect(picked, 'لا يوجد دور مستخدم غير المدير').toBeTruthy();
    const [key, expected] = picked!;

    await login(page);
    await openView(page, 'permissions');
    await expect(page.locator('#rb-body .card').first()).toBeVisible();

    const roleRow = page.locator('#rb-body tr')
      .filter({ has: page.locator('code', { hasText: new RegExp(`^${key}$`) }) });
    await expect(roleRow).toBeVisible();
    await roleRow.locator(`button[data-key="${key}"]`).click();

    /* وصلنا شاشة المستخدمين مُصفّاة */
    await expect(page.locator('#page-title')).toHaveText('المستخدمون');
    await expect(page.locator('#main').getByText('مُصفّى على دور')).toBeVisible();
    const rows = page.locator('#main table tbody tr');
    await expect(rows).toHaveCount(expected);
    const vals = await rows.locator('select').evaluateAll(
      els => els.map(e => (e as HTMLSelectElement).value));
    expect(vals.every(v => v === key), 'كل صف مُصفّى يحمل الدور نفسه').toBeTruthy();

    /* إزالة الفلتر تُرجع القائمة كاملة */
    const total = (users as unknown[]).length;
    await page.click('button:has-text("✕ إزالة الفلتر")');
    await expect(rows).toHaveCount(total);          /* ينتظر اكتمال إعادة الرسم */
    await expect(page.locator('#main').getByText('مُصفّى على دور')).toHaveCount(0);
    await expectNoUiError(page);
  });
});
