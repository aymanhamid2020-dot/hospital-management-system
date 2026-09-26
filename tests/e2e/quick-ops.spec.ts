import { test, expect, type Page } from '@playwright/test';
import { login, authHeader } from './helpers';
import { expectNoUiError, openView } from './views';

/** بادئة فريدة لكل تشغيل حتى تتكرر الاختبارات على نفس القاعدة */
const TAG = Date.now().toString(36).slice(-5).toUpperCase();

/** بيانات التهيئة: مورد + مستودع + صنف + دواء (عبر API) — تُنشأ مرة واحدة فقط */
async function seed(request: import('@playwright/test').APIRequestContext) {
  const h = await authHeader(request);
  const wh = await (await request.get('/stock/warehouses', { headers: h })).json();
  const main = wh.find((w: any) => w.is_default) || wh[0];
  const second = wh.find((w: any) => w.id !== main.id) || main;

  // المورد: يُنشأ مرة واحدة ويُعاد استخدامه
  const vCode = `QV${TAG}`;
  let vendors = (await (await request.get('/accounts/ledger/vendors', { headers: h })).json());
  let vendor = vendors.find((v: any) => v.code === vCode)?.id;
  if (!vendor) {
    const vRes = await request.post('/accounts/ledger/vendors', {
      headers: h, data: { code: vCode, name: `مورد سريع ${TAG}` } });
    expect(vRes.ok(), 'تعذّر إنشاء المورد').toBeTruthy();
    vendor = (await vRes.json()).id;
  }

  // الصنف
  const iCode = `QI${TAG}`;
  let items = (await (await request.get('/general-stock/', { headers: h })).json());
  let item = items.find((x: any) => x.code === iCode)?.id;
  if (!item) {
    const iRes = await request.post('/general-stock/', {
      headers: h, data: {
        code: iCode, name: `مستلزم سريع ${TAG}`, category: 'medical_supplies',
        unit: 'قطعة', unit_cost: 10, reorder_point: 1, max_quantity: 500, is_active: true } });
    expect(iRes.ok(), 'تعذّر إنشاء الصنف').toBeTruthy();
    item = (await iRes.json()).id;
  }

  // الدواء
  const mCode = `QM${TAG}`;
  let meds = (await (await request.get('/medications/', { headers: h })).json());
  let med = meds.find((m: any) => m.code === mCode)?.id;
  if (!med) {
    const mRes = await request.post('/medications/', {
      headers: h, data: {
        code: mCode, name: `دواء سريع ${TAG}`, quantity: 40,
        price: 5, min_quantity: 1, unit: 'علبة' } });
    expect(mRes.ok(), 'تعذّر إنشاء الدواء').toBeTruthy();
    med = (await mRes.json()).id;
  }

  return { main, second, vendor, item, med, headers: h };
}

/** إكمال حقل بحث وانتظار نتائج البطاقات */
async function pick(page: Page, selector: string, text: string, card = '#qo-results .qo-hit') {
  await page.fill(selector, text);
  await page.waitForTimeout(900);
  await page.locator(card).first().click();
}

test.describe('مركز العمليات السريعة ⚡', () => {
  test('الشاشة في القائمة مع ثلاث عمليات ومؤشرات اليوم', async ({ page }) => {
    await login(page);
    await expect(page.locator('.sidebar a[data-view="quickops"]')).toHaveCount(1);
    await openView(page, 'quickops');

    await expect(page.locator('#qo-tiles .qo-tile')).toHaveCount(3);
    await expect(page.locator('#qo-tabs .tab')).toHaveCount(4);
    await expect(page.locator('#qo-tabs .tab.active')).toHaveAttribute('data-tab', 'sale');
    await expect(page.locator('#main .stats .stat')).toHaveCount(4);
    await expect(page.locator('#qo-patient-input')).toBeVisible();
    await expectNoUiError(page);
  });

  test('اختصارات لوحة المفاتيح تفتح العملية مباشرة', async ({ page }) => {
    await login(page);
    await page.keyboard.press('Control+Alt+KeyB');
    await expect(page.locator('#page-title')).toHaveText('العمليات السريعة');
    await expect(page.locator('#qo-tabs .tab.active')).toHaveAttribute('data-tab', 'purchase');
    await page.keyboard.press('Control+Alt+KeyT');
    await expect(page.locator('#qo-tabs .tab.active')).toHaveAttribute('data-tab', 'transfer');
    await page.keyboard.press('Control+Alt+KeyS');
    await expect(page.locator('#qo-tabs .tab.active')).toHaveAttribute('data-tab', 'sale');
    await expectNoUiError(page);
  });

  test('بيع سريع: دواء + مستلزم ⇒ صرف وفيوترة وقيد', async ({ page, request }) => {
    const s = await seed(request);
    await login(page);
    await openView(page, 'quickops');

    // توريد الصنف أولًا حتى يوجد رصيد للبيع
    const grn = await request.post('/quick-ops/purchases', {
      headers: s.headers, data: {
        vendor_id: s.vendor, warehouse_id: s.main.id, bill_no: `SEED-${TAG}`,
        lines: [{ item_id: s.item, quantity: 20, unit_cost: 10 }] } });
    expect(grn.ok(), 'فشل توريد الصنف').toBeTruthy();

    // اختيار المريض بالبحث (أول مريض موجود في النظام)
    const patients = await (await request.get('/patients/?limit=1', { headers: s.headers })).json();
    expect(patients.length, 'لا يوجد مريض للاختبار').toBeGreaterThan(0);
    const nameHead = (patients[0].full_name || '').slice(0, 4);
    await page.fill('#qo-patient-input', nameHead);
    await page.waitForTimeout(900);
    await page.locator('#qo-patients .qo-hit').first().click();
    await expect(page.locator('.pill.paid').first()).toBeVisible();

    // إضافة الصنف ثم الدواء
    await pick(page, '#qo-q', `مستلزم سريع ${TAG}`);
    await expect(page.locator('#qo-basket tbody tr')).toHaveCount(1);
    await page.fill('#qo-q', `دواء سريع ${TAG}`);
    await page.waitForTimeout(900);
    await page.locator('#qo-results .qo-hit').first().click();
    await expect(page.locator('#qo-basket tbody tr')).toHaveCount(2);

    // خصم وضريبة ومدفوع كامل ثم الإتمام
    await page.fill('#qo-discount', '2');
    await page.fill('#qo-tax', '15');
    await page.fill('#qo-paid', '9999');
    await page.click('#qo-submit');

    await expect(page.locator('#qo-body .qo-ok')).toBeVisible();
    await expect(page.locator('#qo-body h3', { hasText: 'تم البيع' })).toBeVisible();
    await expect(page.locator('#qo-body .kv', { hasText: 'الأدوية' })).toBeVisible();
    await expect(page.locator('#qo-body .kv', { hasText: 'المتبقي' })).toContainText('0.00');
    await expectNoUiError(page);

    // الأثر على الخادم: سجل صرف + فاتورة + رصيدDrug ناقص
    const disp = await (await request.get('/dispenses/', { headers: s.headers })).json();
    const mine = disp.filter((d: any) => d.medication_id === s.med);
    expect(mine.length, 'لم يُسجَّل صرف الدواء').toBeGreaterThan(0);
    const inv = await (await request.get('/invoices/', { headers: s.headers })).json();
    expect(inv.some((x: any) => (x.description || '').includes('بيع سريع')),
      'لم تُنشأ فاتورة للبيع السريع').toBeTruthy();
  });

  test('شراء سريع: إذن استلام + فاتورة مورد + خصم المستودع', async ({ page, request }) => {
    const s = await seed(request);
    await login(page);
    await openView(page, 'quickops');
    await page.keyboard.press('Control+Alt+KeyB');
    await expect(page.locator('#qo-tabs .tab.active')).toHaveAttribute('data-tab', 'purchase');

    await page.selectOption('#qo-vendor', String(s.vendor));
    await page.fill('#qo-bill', `QB-${TAG}`);
    await pick(page, '#qo-q', `مستلزم سريع ${TAG}`);
    await page.fill('#qo-basket tbody tr:first-child input[type="text"]', 'LOT-1');
    await page.click('#qo-submit');
    await expect(page.locator('#qo-body h3', { hasText: 'تم الاستلام' })).toBeVisible();
    await expect(page.locator('#qo-body .kv', { hasText: 'المستحق للمورد' })).toBeVisible();
    await expectNoUiError(page);

    const bills = await (await request.get('/accounts/ledger/vendor-bills', { headers: s.headers })).json();
    expect(bills.some((b: any) => b.bill_no === `QB-${TAG}`),
      'لم تُسجَّل فاتورة المورد').toBeTruthy();
    const wh = await (await request.get(`/stock/warehouses/${s.main.id}/items`, { headers: s.headers })).json();
    expect(wh.some((x: any) => x.item_id === s.item && x.quantity >= 1),
      'لم يُضاف الرصيد للمستودع').toBeTruthy();
  });

  test('ترحيل سريع: خصم من المصدر وإضافة للوجهة', async ({ page, request }) => {
    const s = await seed(request);
    // توريد الصنف في المستودع المصدر أولًا
    const grn = await request.post('/quick-ops/purchases', {
      headers: s.headers, data: {
        vendor_id: s.vendor, warehouse_id: s.main.id,
        lines: [{ item_id: s.item, quantity: 15, unit_cost: 10 }] } });
    expect(grn.ok(), 'فشل التوريد').toBeTruthy();
    const before = await (await request.get(`/stock/warehouses/${s.main.id}/items`, { headers: s.headers })).json();
    const qtyBefore = before.find((x: any) => x.item_id === s.item)?.quantity || 0;

    await login(page);
    await openView(page, 'quickops');
    await page.click('#qo-tabs .tab[data-tab="transfer"]');
    await page.selectOption('#qo-from', String(s.main.id));
    await page.selectOption('#qo-to', String(s.second.id));
    await pick(page, '#qo-q', `مستلزم سريع ${TAG}`);
    await page.click('#qo-submit');

    await expect(page.locator('#qo-body .qo-ok')).toBeVisible();
    await expect(page.locator('#qo-body h3', { hasText: 'تم الترحيل' })).toBeVisible();
    await expectNoUiError(page);

    const after = await (await request.get(`/stock/warehouses/${s.main.id}/items`, { headers: s.headers })).json();
    const qtyAfter = after.find((x: any) => x.item_id === s.item)?.quantity || 0;
    expect(qtyAfter, 'لم ينقص رصيد المستودع المصدر').toBe(qtyBefore - 1);
    if (s.second.id !== s.main.id) {
      const dst = await (await request.get(`/stock/warehouses/${s.second.id}/items`, { headers: s.headers })).json();
      expect(dst.some((x: any) => x.item_id === s.item && x.quantity >= 1),
        'لم يصل الصنف للمستودع الوجهة').toBeTruthy();
    }
  });

  test('آخر العمليات تعرض سجل اليوم', async ({ page }) => {
    await login(page);
    await openView(page, 'quickops');
    await page.click('#qo-tabs .tab[data-tab="recent"]');
    await expect(page.locator('#qo-body h3', { hasText: 'آخر عمليات اليوم' })).toBeVisible();
    await expectNoUiError(page);
  });
});