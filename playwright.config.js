// إعداد Playwright — اختبارات E2E لنظام إدارة المستشفيات
// التشغيل: npx playwright test            (كل المتصفحات)
//          npx playwright test --project=chromium
// يجب أن يكون الخادم شغّالًا على http://127.0.0.1:8001 (أو اضبط BASE_URL)
const { defineConfig, devices } = require('@playwright/test');

// اللقطات تُلتقط على Chromium فقط حتى لا تتكرر/تتداخل الصور بين المتصفحات
const NO_SHOTS = ['**/screenshots.spec.ts', '**/gallery.spec.ts'];

// تعدد المتصفحات: يعمل في CI (Ubuntu + --with-deps) أو عند التفعيل اليدوي
// MULTI_BROWSER=1 — على Windows المحلية يبقى Chromium (Firefox/WebKit ينقصها توابع نظامية)
const MULTI = process.env.CI === 'true' || process.env.CI === '1'
  || process.env.MULTI_BROWSER === '1';

const projects = [
  { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
];

if (MULTI) {
  projects.push(
    { name: 'firefox', use: { ...devices['Desktop Firefox'] }, testIgnore: NO_SHOTS },
    { name: 'webkit', use: { ...devices['Desktop Safari'] }, testIgnore: NO_SHOTS },
  );
}

module.exports = defineConfig({
  testDir: './tests/e2e',
  outputDir: 'test-results',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:8001',
    locale: 'ar-EG',
    timezoneId: 'Africa/Cairo',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects,
});
