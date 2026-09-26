import { test, expect } from '@playwright/test';
import { authHeader, login } from './helpers';
import { expectNoUiError, openView } from './views';

const TABS: [string, string][] = [
  ['directory', 'دليل الأقسام والهيكل'],
  ['team', 'الأطباء والكادر'],
  ['rooms', 'الغرف والأسرّة'],
  ['services', 'الخدمات والأسعار'],
  ['schedule', 'الجداول والمواعيد'],
  ['analytics', 'التقارير والإحصائيات'],
];

const tag = () => 'dpt' + Date.now().toString(36);

test.describe('مركز الأقسام (ستة تبويبات)', () => {
  test('التبويبات الستة تعرض محتوى كل قسم', async ({ page }) => {
    await login(page);
    await openView(page, 'departments');

    for (const [key, label] of TABS) {
      await expect(page.locator(`[data-depttab="${key}"]`)).toContainText(label);
    }
    await expect(page.locator('[data-depttab]')).toHaveCount(6);
    // الافتراضي: دليل الأقسام (شجرة)
    await expect(page.locator('#dept-hub h3').first()).toContainText('دليل الأقسام');

    for (const [key] of TABS) {
      await page.click(`[data-depttab="${key}"]`);
      await expect(page.locator(`[data-depttab="${key}"]`)).toHaveClass(/active/);
      // الأقسام 2-6 تحتاج اختيار قسم؛ نختار أول قسم متاح
      const pick = page.locator('#dept-hub #dept-pick');
      if (await pick.count()) {
        const value = await pick.first().locator('option:not([value="0"])').first()
          .getAttribute('value');
        if (value) await pick.first().selectOption(value);
      }
      await expect(page.locator('#dept-hub .card').first()).toBeVisible();
      await expectNoUiError(page);
    }

    // تبويب الغرف يعرض الأسرّة مدمجة (لا شاشة منفصلة)
    await page.click('[data-depttab="rooms"]');
    const pick = page.locator('#dept-hub #dept-pick').first();
    const value = await pick.locator('option:not([value="0"])').first().getAttribute('value');
    await pick.selectOption(String(value));
    await expect(page.locator('#dept-hub')).toContainText('الأسرّة وتوزيعها على الغرف');
  });

  test('إضافة غرفة وخدمة ووردية من الواجهة', async ({ page, request }) => {
    test.setTimeout(90_000);
    const headers = await authHeader(request);
    const roomName = 'غرفة E2E ' + tag();
    const serviceName = 'خدمة E2E ' + tag();
    let deptId = 0;
    let roomId = 0;
    let serviceId = 0;
    let slotId = 0;

    try {
      await login(page);
      await openView(page, 'departments');
      // 1) غرفة جديدة في تبويب الغرف (الشريط يبدأ بدليل الأقسام)
      await page.click('[data-depttab="rooms"]');
      const pick = page.locator('#dept-hub #dept-pick').first();
      deptId = Number(await pick.locator('option:not([value="0"])').first()
        .getAttribute('value'));
      expect(deptId, 'لا يوجد قسم للاختبار').toBeGreaterThan(0);
      await page.fill('#rm-name', roomName);
      await page.selectOption('#rm-cat', 'icu');
      await page.fill('#rm-cap', '2');
      await page.click('button:has-text("إضافة غرفة")');
      await expect(page.locator('#dept-hub')).toContainText(roomName, { timeout: 20_000 });
      const rooms = await (await request.get(`/department-hub/${deptId}/rooms`,
        { headers })).json();
      roomId = rooms.find((r: any) => r.name === roomName)?.id ?? 0;
      expect(roomId, 'لم تُحفظ الغرفة').toBeGreaterThan(0);
      expect(rooms.find((r: any) => r.id === roomId).category).toBe('icu');

      // 2) خدمة بسعرها ونسبها
      await page.click('[data-depttab="services"]');
      await page.fill('#sv-name', serviceName);
      await page.fill('#sv-price', '900');
      await page.fill('#sv-doc', '30');
      await page.fill('#sv-ins', '70');
      await page.click('button:has-text("إضافة خدمة")');
      await expect(page.locator('#dept-hub')).toContainText(serviceName, { timeout: 20_000 });
      const svcs = await (await request.get(`/department-hub/${deptId}/services`,
        { headers })).json();
      const svc = svcs.find((s: any) => s.name === serviceName);
      serviceId = svc?.id ?? 0;
      expect(serviceId).toBeGreaterThan(0);
      expect(svc.doctor_amount).toBe(270);   // 30% من 900
      expect(svc.insurance_amount).toBe(630);

      // 3) وردية صباحية في الجدول
      await page.click('[data-depttab="schedule"]');
      await page.selectOption('#sl-day', '0');
      await page.selectOption('#sl-session', 'morning');
      await page.fill('#sl-open', '09:00');
      await page.fill('#sl-close', '13:00');
      await page.click('button:has-text("إضافة وردية")');
      await expect(page.locator('#dept-hub')).toContainText('09:00', { timeout: 20_000 });
      const slots = await (await request.get(`/department-hub/${deptId}/schedule`,
        { headers })).json();
      const slot = slots.find((s: any) => s.open_time === '09:00');
      slotId = slot?.id ?? 0;
      expect(slotId, 'لم تُحفظ الوردية').toBeGreaterThan(0);
    } finally {
      if (roomId) await request.delete(`/department-hub/${deptId}/rooms/${roomId}`, { headers });
      if (serviceId) await request.delete(`/department-hub/${deptId}/services/${serviceId}`, { headers });
      if (slotId) await request.delete(`/department-hub/${deptId}/schedule/${slotId}`, { headers });
    }
  });
});
