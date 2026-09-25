/* 📸 التقاط لقطات جولة الوحدات التشغيلية (docs/service-units-tour.html)
   التشغيل:  node scripts/capture-service-units-shots.js      (الخادم شغّالًا على 8001)
   تُحفظ في: docs/screenshots/service-units/*.png             (BASE_URL قابل للتجاوز) */
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8001';
const USER = process.env.HMS_USER || 'admin';
const PASS = process.env.HMS_PASS || 'admin123';
const OUT = path.join(__dirname, '..', 'docs', 'screenshots', 'service-units');

/** [الاسم، شاشة القائمة، مسار المحور داخلها (اختياري)] */
const SHOTS = [
  ['01-service-requests', 'clinical', null],
  ['02-care-plans', 'clinical', 'care-plans'],
  ['03-physiotherapy', 'clinical', 'physiotherapy'],
  ['04-housekeeping', 'clinical', 'housekeeping'],
  ['05-emergency', 'clinical', 'emergency'],
  ['06-accounting-tabs', 'accounting', null],
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'ar-EG' });

  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#login-view');
  await page.fill('#li-user', USER);
  await page.fill('#li-pass', PASS);
  await page.click('#login-view button:has-text("تسجيل الدخول")');
  await page.waitForSelector('#app-view');

  for (const [name, view, unit] of SHOTS) {
    await page.click(`.sidebar a[data-view="${view}"]`);
    await page.waitForSelector('#main .card');
    if (unit) {
      await page.click(`#main button.stat[onclick*="${unit}"]`);
      await page.waitForSelector('#main .card');
    }
    await page.waitForTimeout(900);           // استقرار الجداول والعدّادات
    const file = path.join(OUT, `${name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(`✓ ${path.relative(process.cwd(), file)}`);
  }

  await browser.close();
})().catch(err => { console.error('✗', err.message); process.exit(1); });
