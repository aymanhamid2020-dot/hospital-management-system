import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { authHeader, login } from './helpers';
import { expectNoUiError, openView } from './views';

const TAG = Date.now().toString(36).slice(-5).toUpperCase();
const TABS = ['list', 'services', 'schedule', 'summary'] as const;

/** قسم مستقل لكل اختبار (قسم واحد لا يخدم عيادتين) */
async function ownDepartment(request: APIRequestContext, name: string): Promise<number> {
  const h = await authHeader(request);
  const created = await request.post('/departments/', {
    headers: h, data: { name: `${name}-${Date.now().toString(36).slice(-4)}` } });
  expect(created.status()).toBeLessThan(300);
  return (await created.json()).id as number;
}

/** ينشئ قسمًا ثم يعيد تحميل الصفحة حتى يدخل في قائمة «القسم المرتبط» */
async function freshDepartment(page: Page, request: APIRequestContext, name: string) {
  const id = await ownDepartment(request, name);
  await page.reload();
  await openView(page, 'clinics');
  await expect(page.locator('#cl-body .card').first()).toBeVisible();
  return id;
}

test.describe('إدارة العيادات 🏥', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openView(page, 'clinics');
    await expect(page.locator('#cl-body .card').first()).toBeVisible();
  });

  test('التبويبات الأربعة تفتح وتعرض محتواها', async ({ page, request }) => {
    // عيادة مرتبطة بقسم تكفي حتى تُبنى نماذج تبويبا الخدمات والدوام
    const deptId = await freshDepartment(page, request, `قسم تبويبات ${TAG}`);
    await page.fill('#cl-code', `CLT${TAG}`);
    await page.fill('#cl-name', `عيادة تبويبات ${TAG}`);
    await page.selectOption('#cl-dept', String(deptId));
    await page.click('button:has-text("➕ إنشاء عيادة")');
    await expect(page.locator('#cl-body tr', { hasText: `CLT${TAG}` })).toBeVisible();

    await expect(page.locator('#cl-tabs .tab')).toHaveCount(TABS.length);
    const markers: Record<string, string> = {
      list: 'العيادات',
      services: 'خدمات العيادات وأسعارها',
      schedule: 'جدول الدوام الأسبوعي',
      summary: 'ملخص العيادات',
    };
    for (const t of TABS) {
      await page.click(`#cl-tabs .tab[data-tab="${t}"]`);
      await expect(page.locator('#cl-tabs .tab.active')).toHaveAttribute('data-tab', t);
      await expect(page.locator('#cl-body h3').filter({ hasText: markers[t] }).first())
        .toBeVisible();
      await expectNoUiError(page);
    }
  });

  test('إنشاء عيادة مرتبطة بقسم، ثم خدمة ووردية، تظهر في مركز الأقسام', async ({ page, request }) => {
    const h = await authHeader(request);
    const deptId = await freshDepartment(page, request, `قسم اختبار ${TAG}`);

    // 1) إنشاء عيادة مرتبطة بقسم
    await page.fill('#cl-code', `CL${TAG}`);
    await page.fill('#cl-name', `عيادة الاختبار ${TAG}`);
    await page.fill('#cl-specialty', 'باطنية');
    await page.fill('#cl-fee', '150');
    await page.selectOption('#cl-dept', String(deptId));
    await page.click('button:has-text("➕ إنشاء عيادة")');
    const row = page.locator('#cl-body tr', { hasText: `CL${TAG}` });
    await expect(row).toBeVisible();
    await expectNoUiError(page);

    // 2) خدمة بسعر — تُحفظ في كتالوج القسم المرتبط
    await page.click('#cl-tabs .tab[data-tab="services"]');
    const clinicName = `عيادة الاختبار ${TAG}`;
    const clinicValue = await page
      .locator('#cs-clinic option', { hasText: clinicName }).first().getAttribute('value');
    expect(clinicValue).toBeTruthy();
    await page.selectOption('#cs-clinic', clinicValue!);
    await page.fill('#cs-name', `كشفية ${TAG}`);
    await page.fill('#cs-price', '150');
    await page.click('button:has-text("➕ إضافة خدمة")');
    await expect(page.locator('#cl-body tr', { hasText: `كشفية ${TAG}` })).toBeVisible();
    await expectNoUiError(page);

    // نفس الخدمة مرئية في مركز الأقسام ⇒ مصدر واحد بلا نسخ
    const hub = await (await request.get(`/department-hub/${deptId}/services`, { headers: h })).json();
    expect(hub.some((s: { name: string }) => s.name === `كشفية ${TAG}`)).toBeTruthy();

    // 3) وردية دوام بسعة
    await page.click('#cl-tabs .tab[data-tab="schedule"]');
    const slotClinic = await page
      .locator('#csh-clinic option', { hasText: clinicName }).first().getAttribute('value');
    await page.selectOption('#csh-clinic', slotClinic!);
    await page.selectOption('#csh-day', '0');
    await page.selectOption('#csh-session', 'morning');
    await page.fill('#csh-from', '09:00');
    await page.fill('#csh-to', '13:00');
    await page.fill('#csh-room', `عيادة ${TAG}`);
    await page.fill('#csh-max', '12');
    await page.click('button:has-text("➕ إضافة وردية")');
    await expect(page.locator('#cl-body')).toContainText('الأحد');
    await expect(page.locator('#cl-body')).toContainText('صباحية');
    await expect(page.locator('#cl-body')).toContainText('السعة الأسبوعية 12 مريض');
    await expectNoUiError(page);

    // 4) الملخص يعرض السعة الأسبوعية
    await page.click('#cl-tabs .tab[data-tab="summary"]');
    await expect(page.locator('.stat', { hasText: 'السعة الأسبوعية' })).toBeVisible();
    await expectNoUiError(page);

    // 5) الحذف ينظّف سجل العيادة (خدمات القسم تبقى ملك القسم)
    page.on('dialog', d => d.accept());
    await page.click('#cl-tabs .tab[data-tab="list"]');
    await page.locator('#cl-body tr', { hasText: `CL${TAG}` })
      .locator('button:has-text("حذف")').click();
    await expect(page.locator('#cl-body tr', { hasText: `CL${TAG}` })).toHaveCount(0);
    await expectNoUiError(page);
  });

  test('الكود المكرر يُرفض برسالة واضحة بدل إنشاء عيادة ثانية', async ({ page, request }) => {
    await page.fill('#cl-code', `CLD${TAG}`);
    await page.fill('#cl-name', `عيادة مكرّرة ${TAG}`);
    await page.click('button:has-text("➕ إنشاء عيادة")');
    await expect(page.locator('#cl-body tr', { hasText: `CLD${TAG}` })).toBeVisible();

    await page.fill('#cl-code', `CLD${TAG}`);
    await page.fill('#cl-name', `نسخة ثانية ${TAG}`);
    await page.click('button:has-text("➕ إنشاء عيادة")');
    await expect(page.locator('.toast, .toast.error')).toContainText(/مستخدم مسبق/);
    await expectNoUiError(page);
  });

  test('كود العيادة الفارغ لا يُرسَل', async ({ page }) => {
    await page.fill('#cl-name', `بلا كود ${TAG}`);
    await page.click('button:has-text("➕ إنشاء عيادة")');
    await expect(page.locator('#cl-body tr', { hasText: `بلا كود ${TAG}` })).toHaveCount(0);
  });
});
