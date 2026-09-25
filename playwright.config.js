// إعداد Playwright — اختبارات E2E لنظام إدارة المستشفيات
// التشغيل: npx playwright test            (كل المتصفحات)
//          npx playwright test --project=chromium
// يجب أن يكون الخادم شغّالًا على http://127.0.0.1:8001 (أو اضبط BASE_URL)
const { defineConfig, devices } = require('@playwright/test');
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

// اللقطات تُلتقط على Chromium فقط حتى لا تتكرر/تتداخل الصور بين المتصفحات
const NO_SHOTS = ['**/screenshots.spec.ts', '**/gallery.spec.ts'];

// تعدد المتصفحات: يعمل في CI (Ubuntu + --with-deps) أو عند التفعيل اليدوي
// MULTI_BROWSER=1 — Chromium وFirefox يعملان على Windows، أما WebKit فقد يحجبه
// «Smart App Control» (سياسة تحكّم تطبيقات ويندوز) ⇒ نفحص ذلك قبل الإدراج.
const MULTI = process.env.CI === 'true' || process.env.CI === '1'
  || process.env.MULTI_BROWSER === '1';

/** هل يمنع سياسة تحكّم التطبيقات تحميل WebKit2.dll على ويندوز؟ */
function webkitBlockedByPolicy() {
  if (process.platform !== 'win32') return false;
  try {
    const root = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
    const ldd = fs.readdirSync(root).find(d => d.startsWith('winldd-'));
    const kit = fs.readdirSync(root).find(d => d.startsWith('webkit-'));
    if (!ldd || !kit) return false;
    const run = spawnSync(path.join(root, ldd, 'PrintDeps.exe'),
      [path.join(root, kit, 'WebKit2.dll')],
      { encoding: 'utf8', windowsHide: true, timeout: 15_000 });
    const text = `${run.stdout || ''}\n${run.stderr || ''}`;
    return /Application Control policy has blocked/i.test(text);
  } catch (e) {
    return false;  /* أي فشل في الفحص ⇒ نُبقي المشروع كما هو ونظهر الخطأ الأصلي */
  }
}

const projects = [
  { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
];

if (MULTI) {
  projects.push(
    { name: 'firefox', use: { ...devices['Desktop Firefox'] }, testIgnore: NO_SHOTS },
  );
  if (webkitBlockedByPolicy()) {
    console.warn('ℹ️ WebKit محجوب على هذا الجهاز بسياسة Smart App Control'
      + ' — يُستبعد محليًا ويُفحص على CI (Linux).');
  } else {
    projects.push(
      { name: 'webkit', use: { ...devices['Desktop Safari'] }, testIgnore: NO_SHOTS },
    );
  }
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
