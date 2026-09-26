import { test, expect } from '@playwright/test';
import { authHeader, login } from './helpers';
import { expectNoUiError, openView } from './views';

/** الأقسام الستة لشاشة المخزون (نفس ترتيب INV_TABS في app.js) */
const TABS: [string, string][] = [
  ['item-master', 'دليل المواد والمنتجات'],
  ['stock-movements', 'حركة وإدارة المخازن'],
  ['stocktake', 'الجرد والجرودات'],
  ['expiry', 'انتهاء الصلاحية والتالف'],
  ['procurement', 'المشتريات والموردين'],
  ['reports', 'التقارير والإحصائيات'],
];

const tag = () => 'e2e' + Date.now().toString(36);

test.describe('إدارة المخازن (الأقسام الستة)', () => {
  test('شريط الأقسام الستة موجود وكل تبويب يُحمَّل محتواه', async ({ page }) => {
    await login(page);
    await openView(page, 'inventory');

    // ستّة أقسام مرقّمة + شريط تبويبات فرعية
    for (const [key, label] of TABS) {
      await expect(page.locator(`[data-invtab="${key}"]`)).toContainText(label);
    }
    await expect(page.locator('[data-invtab]')).toHaveCount(6);
    await expect(page.locator('#inv-ops')).toBeVisible();

    // التبويب الافتراضي: قائمة المنتجات
    await expect(page.locator('#inv-ops h3').first()).toContainText('قائمة المنتجات');

    // المرور على الأقسام كلها: كل واحد يعرض محتواه بلا رسالة فشل
    for (const [key] of TABS) {
      await page.click(`[data-invtab="${key}"]`);
      await expect(page.locator(`[data-invtab="${key}"]`)).toHaveClass(/active/);
      await expect(page.locator('#inv-ops .card, #inv-ops table').first()).toBeVisible();
      await expectNoUiError(page);
    }

    // عيّنة من التبويبات الفرعية المطلوبة في كل قسم
    await page.click('[data-invtab="stock-movements"]');
    await page.click('[data-invsub="warehouses"]');
    await expect(page.locator('#inv-ops h3').first()).toContainText('المستودعات والفروع');
    await expect(page.locator('#inv-ops')).toContainText('المستودع الرئيسي');

    await page.click('[data-invsub="grn"]');
    await expect(page.locator('#inv-ops h3').first()).toContainText('إذن استلام');

    await page.click('[data-invtab="reports"]');
    await page.click('[data-invsub="valuation"]');
    await expect(page.locator('#inv-ops h3').first()).toContainText('قيمة المخزون');

    await page.click('[data-invsub="slow-moving"]');
    await expect(page.locator('#inv-ops h3').first()).toContainText('الركود');

    await page.click('[data-invtab="item-master"]');
    await page.click('[data-invsub="reorder"]');
    await expect(page.locator('#inv-ops h3').first()).toContainText('مستويات إعادة الطلب');
  });

  test('إنشاء مستودع وصنف وإذن استلام من الواجهة', async ({ page, request }) => {
    test.setTimeout(120_000);   // تدفّق إداري كامل: نماذج + حفظ + قراءة خلفية
    const uid = tag();
    const whName = 'مستودع E2E ' + uid;
    const code = 'E2E' + uid.slice(-6).toUpperCase();   // من ذيل المعرّف: ثابت لو قطعت من أوله
    const headers = await authHeader(request);
    let itemId = 0;

    /* النقر داخل النافذة تحديدًا: النقر العام قد يصيب زر الصف بعد إعادة الرسم */
    const saveInModal = async (label: string) => {
      await expect(page.locator('#modal-back')).toHaveClass(/show/);
      await page.locator(`#modal-body button:has-text("${label}")`).click();
      await expect(page.locator('#modal-back')).not.toHaveClass(/show/, { timeout: 20_000 });
    };

    try {
      await login(page);
      await openView(page, 'inventory');

      // 1) مستودع جديد من شاشة المستودعات
      await test.step('مستودع جديد', async () => {
        await page.click('[data-invtab="stock-movements"]');
        await page.click('[data-invsub="warehouses"]');
        await page.click('#inv-ops button:has-text("إضافة مستودع")');
        await page.fill('#wh-name', whName);
        await page.selectOption('#wh-kind', 'emergency');
        await saveInModal('حفظ المستودع');
        await expect(page.locator('#inv-ops')).toContainText(whName, { timeout: 20_000 });
      });

      // 2) صنف جديد بدليل المواد مع بياناته التفصيلية
      await test.step('صنف جديد', async () => {
        await page.click('[data-invtab="item-master"]');
        await page.click('[data-invsub="catalog"]');
        await page.click('#inv-ops button:has-text("إضافة صنف")');
        await page.fill('#si-code', code);
        await page.fill('#si-name', 'مستلزم E2E ' + uid);
        await page.fill('#si-store', 'ثلاجة 2–8°');
        await page.fill('#si-min', '5');
        await page.fill('#si-reorder', '20');
        await page.fill('#si-max', '60');
        await page.fill('#si-cost', '7.5');
        await saveInModal('حفظ الصنف');
        await expect(page.locator('#inv-ops')).toContainText(code, { timeout: 20_000 });
        await expect(page.locator('#inv-ops')).toContainText('ثلاجة 2–8°');
      });

      const items = await (await request.get('/general-stock/', { headers })).json();
      itemId = items.find((i: any) => i.code === code)?.id ?? 0;
      expect(itemId, 'لم يُحفظ الصنف').toBeGreaterThan(0);
      const row = items.find((i: any) => i.id === itemId);
      expect(row.reorder_point).toBe(20);
      expect(row.max_quantity).toBe(60);
      expect(row.storage_condition).toBe('ثلاجة 2–8°');

      // 3) إذن استلام بدفعة رقم تشغيلة وتاريخ انتهاء
      await test.step('إذن استلام', async () => {
        await page.click('[data-invtab="stock-movements"]');
        await page.click('[data-invsub="grn"]');
        await page.click('#inv-ops button:has-text("جديد")');
        await page.click('#modal-body button:has-text("إضافة سطر")');
        await expect(page.locator('[data-stk-line="0"]')).toBeVisible({ timeout: 20_000 });
        await page.selectOption('[data-stk-line="0"] select', String(itemId));
        await page.fill('[data-stk-line="0"] [data-stk="qty"]', '40');
        await page.fill('[data-stk-line="0"] [data-stk="batch"]', 'B' + uid.slice(-4).toUpperCase());
        await page.fill('[data-stk-line="0"] [data-stk="expiry"]', '2027-12-31');
        await page.fill('[data-stk-line="0"] [data-stk="cost"]', '7.5');
        await saveInModal('حفظ إذن استلام');
        await expect(page.locator('#inv-ops')).toContainText('GRN-', { timeout: 20_000 });
      });

      const docs = await (await request.get('/stock/docs?doc_type=grn',
        { headers })).json();
      const mine = docs.find((d: any) => d.lines.some((l: any) => l.item_id === itemId));
      expect(mine, 'لم يُسجَّل إذن الاستلام').toBeTruthy();
      expect(mine.status).toBe('completed');
      expect(mine.lines.find((l: any) => l.item_id === itemId).quantity).toBe(40);

      // 4) الصنف في بطاقة الصنف برصيده ودفعة الصلاحية
      await test.step('بطاقة الصنف', async () => {
        await page.click('[data-invtab="reports"]');
        await page.click('[data-invsub="item-card"]');
        await expect(page.locator('#stk-item-pick')).toBeVisible({ timeout: 20_000 });
        await page.selectOption('#stk-item-pick', String(itemId));
        await expect(page.locator('#inv-ops')).toContainText(code, { timeout: 20_000 });
        await expect(page.locator('#inv-ops')).toContainText('40');
        await expectNoUiError(page);
      });
    } finally {
      // تنظيف: الصنف له حركات ومستندات فلا يُحذف (409) فيُعطَّل، والمستودع يُحذف
      if (itemId) {
        const off = await request.put(`/general-stock/${itemId}`,
          { headers, data: { is_active: false } });
        expect([200, 204]).toContain(off.status());
      }
      const whs = await (await request.get('/stock/warehouses', { headers })).json();
      const wh = whs.find((w: any) => w.name === whName);
      if (wh) await request.delete(`/stock/warehouses/${wh.id}`, { headers });
    }
  });
});
