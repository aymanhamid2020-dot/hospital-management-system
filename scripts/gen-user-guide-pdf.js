/* 📘 توليد docs/user-guide.pdf من docs/user-guide.html
   التشغيل:  node scripts/gen-user-guide-pdf.js
   يُستخدم يدويًا وفي CI (وظيفة docs-pdf) حتى يبقى الملفان متزامنين. */
const path = require('path');
const fs = require('fs');

const root = path.resolve(__dirname, '..');
const html = path.join(root, 'docs', 'user-guide.html');
const pdf = path.join(root, 'docs', 'user-guide.pdf');

if (!fs.existsSync(html)) {
  console.error('✗ غير موجود:', html);
  process.exit(1);
}

// playwright مثبّت كاعتمادية تطوير في جذر المشروع
const { chromium } = require(path.join(root, 'node_modules', 'playwright'));

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file:///' + html.replace(/\\/g, '/'), { waitUntil: 'networkidle' });
  await page.pdf({
    path: pdf,
    format: 'A4',
    printBackground: true,
    margin: { top: '14mm', bottom: '14mm', left: '12mm', right: '12mm' },
  });
  await browser.close();

  const size = fs.statSync(pdf).size;
  if (size < 100_000) {
    console.error('✗ حجم الملف غير معقول:', size);
    process.exit(1);
  }
  console.log(`✓ ${path.relative(root, pdf)} — ${(size / 1024 / 1024).toFixed(2)} MB`);
})().catch(err => { console.error(err); process.exit(1); });
