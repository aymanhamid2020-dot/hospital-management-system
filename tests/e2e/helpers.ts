import { expect, type APIRequestContext, type Page } from '@playwright/test';

/** مسار لوحة التحكم (الواجهة معلّقة على /ui) */
export const APP = '/ui/';

/** بيانات الدخول الافتراضية للبيئة التجريبية (تُتجاوز عبر HMS_USER / HMS_PASS) */
export const USER = process.env.HMS_USER || 'admin';
export const PASS = process.env.HMS_PASS || 'admin123';

/** تسجيل الدخول عبر شاشة الدخول والانتظار حتى يظهر التطبيق */
export async function login(page: Page): Promise<void> {
  await page.goto(APP);
  await expect(page.locator('#login-view')).toBeVisible();
  await page.fill('#li-user', USER);
  await page.fill('#li-pass', PASS);
  await page.click('#login-view button:has-text("تسجيل الدخول")');
  await expect(page.locator('#app-view')).toBeVisible();
}

/** فتح شاشة الأطباء من الشريط الجانبي والانتظار حتى يكتمل الجدول */
export async function openDoctors(page: Page): Promise<void> {
  await page.click('.sidebar a[data-view="doctors"]');
  await expect(page.locator('#page-title')).toHaveText('الأطباء');
  await expect(page.locator('#main h3').filter({ hasText: 'الأطباء' })).toBeVisible();
  await expect(page.locator('#tbl tbody tr').first()).toBeVisible();
}

/** رمز وصول عبر API مباشرة — لاختبار المستندات (PDF/CSV) خارج المتصفح */
export async function apiToken(request: APIRequestContext): Promise<string> {
  const res = await request.post('/auth/login', {
    data: { username: USER, password: PASS },
  });
  expect(res.ok(), 'فشل تسجيل الدخول عبر API').toBeTruthy();
  const body = await res.json();
  expect(body.access_token, 'لا يوجد access_token في استجابة الدخول').toBeTruthy();
  return body.access_token as string;
}

/** ترويسة Authorization الجاهزة لطلبات API المحمية */
export async function authHeader(request: APIRequestContext): Promise<Record<string, string>> {
  return { Authorization: `Bearer ${await apiToken(request)}` };
}

/** معرّف أول طبيب في النظام (يعتمد عليه اختبار الترخيص/الجدول) */
export async function firstDoctorId(
  request: APIRequestContext,
  headers: Record<string, string>,
): Promise<number> {
  const res = await request.get('/doctors/', { headers });
  expect(res.ok(), 'تعذّر قراءة قائمة الأطباء').toBeTruthy();
  const rows = await res.json();
  expect(rows.length, 'لا يوجد أطباء في قاعدة البيانات').toBeGreaterThan(0);
  return rows[0].id as number;
}
