import { test, expect, type Page } from '@playwright/test';
import { login, authHeader } from './helpers';
import { expectNoUiError, openView } from './views';

/** بادئة فريدة لكل تشغيل حتى تتكرر الاختبارات على نفس القاعدة */
const TAG = Date.now().toString(36).slice(-5).toUpperCase();

/** بيانات التهيئة: مورد + مستودع + صنف + دواء (عبر API) — تُنشأ مرة واحدة فقط */
async function seed(request: import('@playwright/test').APIRequestContext) {
  const h = await authHeader(request);
  let wh = await (await request.get('/stock/warehouses', { headers: h })).json();
  // قاعدة CI نظيفة لا يكون فيها سوى «المستودع الرئيسي» الافتراضي (seed_demo لا
  // ينشئ مستودعات)، والترحيل إلى نفس المستودع يُرفض 400 ⇒ ننشئ فرعًا أولًا
  if (wh.length < 2) {
    const wRes = await request.post('/stock/warehouses', {
      headers: h, data: { name: `فرع التحويل ${TAG}`, kind: 'dept' } });
    expect(wRes.ok(), 'تعذّر إنشاء مستودع التحويل').toBeTruthy();
    wh = await (await request.get('/stock/warehouses', { headers: h })).json();
  }
  const main = wh.find((w: any) => w.is_default) || wh[0];
  const second = wh.find((w: any) => w.id !== main.id) || main;
  expect(second.id, 'يلزم مستودعان مختلفان لاختبار الترحيل').not.toBe(main.id);

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
        unit: 'قطعة', unit_cost: 10, reorder_point: 1, max_quantity: 500,
        is_active: true, barcode: `BAR${TAG}` } });
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

  test('مسار الباركود: Enter يضيف ويفرّغ الحقل + مسودة تعود بعد تحديث + تكرار آخر عملية', async ({ page, request }) => {
    const s = await seed(request);
    const grn = await request.post('/quick-ops/purchases', {
      headers: s.headers, data: {
        vendor_id: s.vendor, warehouse_id: s.main.id,
        lines: [{ item_id: s.item, quantity: 10, unit_cost: 10 }] } });
    expect(grn.ok(), 'فشل توريد الصنف').toBeTruthy();
    const items = (await (await request.get('/general-stock/', { headers: s.headers })).json());
    const mine = items.find((x: any) => x.code === `QI${TAG}`);
    expect(mine && mine.barcode, 'الصنف بلا باركود لاختبار المسح').toBeTruthy();

    await login(page);
    await openView(page, 'quickops');

    // 1) مسح الباركود + Enter ⇒ إضافة فورية وتفريغ الحقل لمسحٍ تالٍ
    await page.fill('#qo-q', mine.barcode);
    await page.press('#qo-q', 'Enter');
    await expect(page.locator('#qo-basket tbody tr')).toHaveCount(1);
    await expect(page.locator('#qo-q')).toHaveValue('');
    // Enter على حقل فارغ ⇒ تلميح بلا إضافة ولا خطأ
    await page.press('#qo-q', 'Enter');
    await expect(page.locator('#qo-basket tbody tr')).toHaveCount(1);
    await expectNoUiError(page);

    // 2) المسودة محفوظة، وتعود بعد تحديث الصفحة
    const draft = await page.evaluate(() => localStorage.getItem('hms_qo_draft'));
    expect(draft, 'السلة غير محفوظة كمسودة').toBeTruthy();
    expect(JSON.parse(draft as string).basket.length).toBe(1);
    await page.reload();
    if (await page.locator('#login-view').isVisible().catch(() => false)) await login(page);
    await openView(page, 'quickops');
    await expect(page.locator('#qo-basket tbody tr')).toHaveCount(1);
    await expect(page.locator('#toast')).toContainText('مسودة سابقة');
    await expectNoUiError(page);

    // 3) المريض ثم الإتمام بـ Ctrl+Enter (المسار المختصر)
    const patients = await (await request.get('/patients/?limit=1', { headers: s.headers })).json();
    expect(patients.length, 'لا يوجد مريض للاختبار').toBeGreaterThan(0);
    await page.fill('#qo-patient-input', (patients[0].full_name || '').slice(0, 4));
    await page.waitForTimeout(900);
    await page.locator('#qo-patients .qo-hit').first().click();
    await page.press('#qo-q', 'Control+Enter');
    await expect(page.locator('#qo-body .qo-ok')).toBeVisible();
    await expect(page.locator('#qo-body h3', { hasText: 'تم البيع' })).toBeVisible();

    // 4) بعد الإتمام: مسودة ممحوحة + لقطة عملية سابقة جاهزة للتكرار
    expect(await page.evaluate(() => localStorage.getItem('hms_qo_draft')),
      'المسودة بقيت بعد الإتمام').toBeNull();
    expect(await page.evaluate(() => localStorage.getItem('hms_qo_lastop')),
      'لا لقطة عملية سابقة للتكرار').toBeTruthy();

    await page.click('#qo-body button:has-text("عملية جديدة")');
    const repeat = page.locator('button:has-text("تكرار آخر عملية")');
    await expect(repeat).toHaveCount(1);
    await repeat.click();
    await expect(page.locator('#qo-basket tbody tr')).toHaveCount(1);
    await expect(page.locator('#qo-basket tbody tr').first()).toContainText(`مستلزم سريع ${TAG}`);
    await expectNoUiError(page);
  });

  test('وصل صرف الأدوية ثم إرجاع البيع السريع من البطاقة', async ({ page, request }) => {
    const s = await seed(request);
    await login(page);
    await openView(page, 'quickops');

    const qty = async () => (await (await request.get('/medications/', { headers: s.headers })).json())
      .find((m: any) => m.id === s.med).quantity;
    const nonReturned = async () =>
      (await (await request.get('/dispenses/', { headers: s.headers })).json())
        .filter((d: any) => d.medication_id === s.med && !d.returned_at).length;
    const q0 = await qty();
    const d0 = await nonReturned();

    // بيع أدوية فقط (بلا فاتورة أصناف) ⇒ زر الوصل يظهر
    const patients = await (await request.get('/patients/?limit=1', { headers: s.headers })).json();
    await page.fill('#qo-patient-input', (patients[0].full_name || '').slice(0, 4));
    await page.waitForTimeout(900);
    await page.locator('#qo-patients .qo-hit').first().click();
    await pick(page, '#qo-q', `دواء سريع ${TAG}`);
    await page.fill('#qo-paid', '9999');
    await page.click('#qo-submit');
    await expect(page.locator('#qo-body h3', { hasText: 'تم البيع' })).toBeVisible();
    await expect(page.locator('button:has-text("طباعة الفاتورة")')).toHaveCount(0);

    // الوصل: نافذة طباعة بنفس نظام التصميم الموحّد تحمل الدواء والمريض —
    // ويفتح نافذة الطباعة تلقائيًّا (autoprint=1). نعوّض window.print في
    // السياق قبل الفتح حتى لا يحجب محرّك الطباعة الاختبار، ثم نتحقّق
    // أنّ الطباعة التلقائية استُدعيت فعلًا بعد تحميل الوصل.
    await page.context().addInitScript(() => {
      (window as any).__printed = false;
      window.print = () => { (window as any).__printed = true; };
    });
    const receiptBtn = page.locator('button:has-text("وصل صرف الأدوية")');
    await expect(receiptBtn).toHaveCount(1);
    const popupPromise = page.waitForEvent('popup');
    await receiptBtn.click();
    const popup = await popupPromise;
    await expect(popup.locator('body')).toContainText('وصل صرف أدوية');
    await expect(popup.locator('body')).toContainText(`دواء سريع ${TAG}`);
    await expect.poll(() => popup.evaluate(() => (window as any).__printed),
      { timeout: 10_000, message: 'الطباعة التلقائية على الطابعة الافتراضية لم تُستدعَ' })
      .toBe(true);
    await popup.close();

    // الإرجاع: سبب إلزامي عبر prompt ثم تأكيد confirm
    page.on('dialog', async (d) => {
      if (d.type() === 'prompt') await d.accept('خطأ في الطلب');
      else await d.accept();
    });
    await page.click('#qo-body button:has-text("إرجاع البيع")');
    await expect(page.locator('#qo-body h3', { hasText: 'تم إرجاع البيع' })).toBeVisible();
    await expect(page.locator('#qo-body .pill.paid')).toContainText('رُدّ');
    await expect(page.locator('#qo-body button:has-text("إرجاع البيع")')).toHaveCount(0);
    await expectNoUiError(page);

    // الأثر على الخادم: الدواء عاد، والصرف عُلِّم مرتجعًا
    expect(await qty(), 'لم يعود رصيد الدواء بعد الإرجاع').toBe(q0);
    expect(await nonReturned(), 'لم يُعلَّم الصرف كمرتجع').toBe(d0);
  });
});