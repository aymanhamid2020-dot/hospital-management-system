import { expect, type Page } from '@playwright/test';
import { login } from './helpers';

/** عناوين الشاشات كما في خريطة TITLES داخل app.js */
const TITLES: Record<string, string> = {
  dashboard: 'لوحة التحكم',
  patients: 'المرضى',
  appointments: 'المواعيد',
  pharmacy: 'الصيدلية',
  inventory: 'المخزون',
  lab: 'المختبر والأشعة',
  accounting: 'المحاسبة',
  /* الفواتير والرواتب تبويبات داخل شاشة المحاسبة — تُفتح الشاشة بعنوانها */
  invoices: 'المحاسبة',
  payroll: 'المحاسبة',
  clinical: 'الرعاية والتشغيل',
};

/** فتح شاشة من الشريط الجانبي والانتظار حتى يظهر محتواها */
export async function openView(page: Page, view: keyof typeof TITLES): Promise<void> {
  await page.click(`.sidebar a[data-view="${view}"]`);
  await expect(page.locator('#page-title')).toHaveText(TITLES[view]);
  await expect(page.locator('#main .card, #main .stats').first()).toBeVisible();
}

export { TITLES };

/**
 * لا يجب أن تعرض شاشة رسالة فشل عرض (الخطأ يُرسم في `#main` كعنصر `.empty` أحمر).
 * ملاحظة: الرموز التحذيرية ⚠️ الأخرى داخل الجداول (منتهي صلاحية…) مشروعة.
 */
export async function expectNoUiError(page: Page): Promise<void> {
  await expect(page.locator('#main .empty', { hasText: '⚠️' })).toHaveCount(0);
}
