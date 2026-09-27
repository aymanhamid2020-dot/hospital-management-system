import { test, expect, type APIRequestContext } from '@playwright/test';
import { login, authHeader } from './helpers';
import { expectNoUiError, openView } from './views';

const TAG = Date.now().toString(36).slice(-5).toUpperCase();
const TABS = ['pos', 'collect', 'insure', 'quotes', 'pricing', 'reports'] as const;

async function firstPatientId(request: APIRequestContext, headers: Record<string, string>) {
  const rows = await (await request.get('/patients/?limit=1', { headers })).json();
  return rows[0]?.id as number;
}

test.describe('دورة الإيراد في شاشة المبيعات 🧾', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openView(page, 'sales');
    await expect(page.locator('#rc-body .card').first()).toBeVisible();
  });

  test('التبويبات الستة تفتح وتعرض محتواها الحقيقي', async ({ page }) => {
    await expect(page.locator('#rc-tabs .tab')).toHaveCount(TABS.length);
    const markers: Record<string, string> = {
      pos: 'نقطة البيع والفواتير',
      collect: 'إغلاق الصندوق اليومي',
      insure: 'الموافقات المسبقة',
      quotes: 'عروض الأسعار',
      pricing: 'قوائم الأسعار',
      reports: 'ملخص المبيعات',
    };
    for (const t of TABS) {
      await page.click(`#rc-tabs .tab[data-tab="${t}"]`);
      await expect(page.locator('#rc-tabs .tab.active')).toHaveAttribute('data-tab', t);
      await expect(page.locator('#rc-body h3').filter({ hasText: markers[t] }).first())
        .toBeVisible();
      await expectNoUiError(page);
    }
  });

  test('إشعار الدائن لا يتجاوز المدفوع ويُنقص رصيد الفاتورة', async ({ page, request }) => {
    const h = await authHeader(request);
    const pid = await firstPatientId(request, h);
    const invRes = await request.post('/invoices/', {
      headers: h, data: { patient_id: pid, amount: 400, payment_method: 'cash',
                          status: 'paid', description: 'خدمة اختبارية' } });
    expect(invRes.status(), 'تعذّر إنشاء الفاتورة').toBeTruthy();
    const inv = await invRes.json();
    expect(inv.paid_amount, 'الفاتورة لم تُسجَّل مدفوعة').toBe(400);

    await page.click('#rc-tabs .tab[data-tab="pos"]');
    await page.fill('#cn-target', String(inv.id));
    await page.fill('#cn-amount', '150');
    await page.fill('#cn-reason', 'خدمة لم تُقدَّم');
    await page.click('#rc-body button:has-text("إصدار إشعار دائن")');

    await expect(page.locator('#toast')).toContainText('✅');
    await expect(page.locator('#rc-body h3', { hasText: 'إشعارات الدائن' })).toBeVisible();
    await expect(page.locator('#rc-body table').last()).toContainText('خدمة لم تُقدَّم');
    const after = await (await request.get(`/invoices/${inv.id}`, { headers: h })).json();
    expect(after.paid_amount, 'الاسترداد لم يُخصم من المدفوع').toBe(250);

    await expect(page.locator('#toast')).not.toHaveClass(/show/);
    await page.fill('#cn-target', String(inv.id));
    await page.fill('#cn-amount', '9999');
    await page.fill('#cn-reason', 'محاولة استرداد أكبر');
    await page.click('#rc-body button:has-text("إصدار إشعار دائن")');
    await expect(page.locator('#toast')).toContainText('يتجاوز المدفوع');
    await expectNoUiError(page);
  });

  test('الوديعة تُسجَّل وتُخصم من فاتورة', async ({ page, request }) => {
    const h = await authHeader(request);
    const pid = await firstPatientId(request, h);
    await page.click('#rc-tabs .tab[data-tab="collect"]');
    await page.fill('#dep-patient', String(pid));
    await page.fill('#dep-amount', '250');
    await page.fill('#dep-notes', 'دفعة تنويم');
    await page.click('#rc-body button:has-text("تسجيل دفعة مقدمة")');
    await expect(page.locator('#toast')).toContainText('✅');
    await expect(page.locator('#rc-body h3', { hasText: 'الدفعات المقدمة' })).toBeVisible();

    const dep = await (await request.get(`/revenue/deposits?patient_id=${pid}`, { headers: h })).json();
    const mine = dep.find((d: any) => d.amount === 250);
    expect(mine, 'لم تُسجَّل الوديعة في الخادم').toBeTruthy();
    const inv = await (await request.post('/invoices/', {
      headers: h, data: { patient_id: pid, amount: 250, payment_method: 'cash',
                          description: 'فاتورة من الوديعة' } })).json();
    const r = await (await request.post(`/revenue/deposits/${mine.id}/apply`, {
      headers: h, data: { invoice_id: inv.id } })).json();
    expect(r.balance, 'الرصيد لم يُخصم').toBe(0);
    expect(r.status).toBe('applied');
    await expectNoUiError(page);
  });

  test('وردية الكاشير تُفتح وتُغلق بمطابقة الصندوق', async ({ page }) => {
    await page.click('#rc-tabs .tab[data-tab="collect"]');
    const openBtn = page.locator('#rc-body button:has-text("فتح وردية")');
    if (await openBtn.count()) {
      await page.fill('#shift-opening', '100');
      await openBtn.click();
      await expect(page.locator('#toast')).toContainText('✅');
    }
    await expect(page.locator('#rc-body h3', { hasText: 'إغلاق الصندوق' })).toBeVisible();
    await page.fill('#shift-counted', '100');
    await page.click('#rc-body button:has-text("إغلاق ومطابقة")');
    await expect(page.locator('#rc-body table').last()).toContainText('متوازنة');
    await expectNoUiError(page);
  });

  test('الموافقة المسبقة تُسجَّل ويُسجَّل قرار التأمين', async ({ page, request }) => {
    const h = await authHeader(request);
    const pid = await firstPatientId(request, h);
    await page.click('#rc-tabs .tab[data-tab="insure"]');
    await page.fill('#pa-patient', String(pid));
    await page.fill('#pa-service', 'عملية قلب مفتوح');
    await page.fill('#pa-icd', 'I21.4');
    await page.fill('#pa-cpt', '33510');
    await page.fill('#pa-amount', '40000');
    await page.click('#rc-body button:has-text("تسجيل طلب موافقة")');
    await expect(page.locator('#toast')).toContainText('✅');

    const auths = await (await request.get('/revenue/prior-authorizations', { headers: h })).json();
    const mine = auths.find((a: any) => a.service_description === 'عملية قلب مفتوح');
    expect(mine, 'لم تُسجَّل الموافقة المسبقة').toBeTruthy();
    expect(mine.status).toBe('pending');
    expect(mine.icd10_code).toBe('I21.4');

    const row = page.locator('#rc-body tr', { hasText: mine.auth_number });
    await row.locator('button:has-text("موافقة")').click();
    await expect(page.locator('#toast')).toContainText('✅');
    const after = await (await request.get('/revenue/prior-authorizations', { headers: h })).json();
    const done = after.find((a: any) => a.id === mine.id);
    expect(done.status).toBe('approved');
    expect(done.approved_amount).toBe(40000);
    await expectNoUiError(page);
  });

  test('عرض السعر يُنشأ ويُحوَّل إلى فاتورة', async ({ page, request }) => {
    const h = await authHeader(request);
    const pid = await firstPatientId(request, h);
    await page.click('#rc-tabs .tab[data-tab="quotes"]');
    await page.fill('#qt-patient', String(pid));
    await page.fill('#qt-title', `عرض تجميل ${TAG}`);
    await page.fill('#qt-line', 'جلسة ليزر');
    await page.fill('#qt-price', '1500');
    await page.fill('#qty', '2');
    await page.fill('#qt-tax', '15');
    await page.click('#rc-body button:has-text("إنشاء عرض سعر")');
    await expect(page.locator('#toast')).toContainText('عرض السعر');

    const quotes = await (await request.get('/revenue/quotations', { headers: h })).json();
    const q = quotes.find((x: any) => x.title === `عرض تجميل ${TAG}`);
    expect(q, 'لم يُسجَّل عرض السعر').toBeTruthy();
    expect(q.total).toBe(3450);   // 3000 + 15% ضريبة

    await page.locator('#rc-body tr', { hasText: q.quote_no })
      .locator('button:has-text("قبول")').click();
    await expect(page.locator('#toast')).toContainText('✅');
    await page.locator('#rc-body tr', { hasText: q.quote_no })
      .locator('button:has-text("تحويل لفاتورة")').click();
    await expect(page.locator('#toast')).toContainText('فاتورة');

    const after = await (await request.get('/revenue/quotations', { headers: h })).json();
    const conv = after.find((x: any) => x.id === q.id);
    expect(conv.status).toBe('converted');
    expect(conv.invoice_id, 'لم تُنشأ فاتورة من العرض').toBeTruthy();
    await expectNoUiError(page);
  });

  test('سياسة الخصم تُفحص وتُحجب النسبة الزائدة', async ({ page }) => {
    await page.click('#rc-tabs .tab[data-tab="pricing"]');
    await page.fill('#dr-name', `سقف ${TAG}`);
    await page.fill('#dr-max', '10');
    await page.click('#rc-body button:has-text("إضافة سياسة")');
    await expect(page.locator('#toast')).toContainText('✅');

    await page.fill('#dr-check', '5');
    await page.click('#rc-body button:has-text("فحص")');
    await expect(page.locator('#toast')).toContainText('ضمن السقف');

    /* ننتظر اختفاء الإشعار حتى لا يحجب زر الفحص الثاني النقر */
    await expect(page.locator('#toast')).not.toHaveClass(/show/);
    await page.fill('#dr-check', '30');
    await page.click('#rc-body button:has-text("فحص")');
    await expect(page.locator('#toast')).toContainText('يتجاوز سقف');
    await expectNoUiError(page);
  });

  test('تقرير المبيعات يعرض مفاتيحه الأربعة', async ({ page }) => {
    await page.click('#rc-tabs .tab[data-tab="reports"]');
    await expect(page.locator('#rc-body h3', { hasText: 'ملخص المبيعات' })).toBeVisible();
    await expect(page.locator('#rc-body h3', { hasText: 'حسب طريقة الدفع' })).toBeVisible();
    await expect(page.locator('#rc-body h3', { hasText: 'إيرادات الأطباء' })).toBeVisible();
    await expect(page.locator('#rc-body h3', { hasText: 'شركة التأمين' })).toBeVisible();
    await expect(page.locator('#rc-body h3', { hasText: 'حالة التحصيل' })).toBeVisible();
    await expectNoUiError(page);
  });
});


