import { test, expect } from '@playwright/test';
import {
  APP, authHeader, firstDoctorId, login, openDoctors,
} from './helpers';

test.describe('وحدة الأطباء 🩺', () => {
  test('شاشة الدخول ثم عرض قائمة الأطباء', async ({ page }) => {
    await login(page);
    await openDoctors(page);

    // بطاقات الإحصاء + زر التقرير المقارن + صفوف الأطباء
    await expect(page.locator('#main .stat').first()).toBeVisible();
    await expect(page.locator('#main button:has-text("أداء الشهر")')).toBeVisible();
    expect(await page.locator('#tbl tbody tr').count()).toBeGreaterThan(0);
  });

  test('التقرير المقارن PDF يُحمّل بمستند صالح', async ({ request }) => {
    const res = await request.get('/doctors/performance/report.pdf', {
      headers: await authHeader(request),
    });

    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('application/pdf');
    expect(res.headers()['content-disposition']).toContain('doctors_performance');
    const body = await res.body();
    expect(body.subarray(0, 4).toString('latin1')).toBe('%PDF');
    expect(body.byteLength).toBeGreaterThan(500);
  });

  test('تصدير CSV المقارن يفتح بترميز UTF-8 وعناوين عربية', async ({ request }) => {
    const res = await request.get('/doctors/performance/export.csv', {
      headers: await authHeader(request),
    });

    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('text/csv');
    expect(res.headers()['content-disposition']).toContain('doctors_performance');
    const text = await res.text();
    expect(text.startsWith('﻿')).toBeTruthy(); // BOM لفتح Excel بالعربية
    expect(text).toContain('الطبيب');
    expect(text).toContain('نسبة الإتمام %');
  });

  test('بطاقة الترخيص PDF للطبيب الأول', async ({ request }) => {
    const headers = await authHeader(request);
    const id = await firstDoctorId(request, headers);
    const res = await request.get(`/doctors/${id}/license.pdf`, { headers });

    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('application/pdf');
    expect(res.headers()['content-disposition']).toContain(`license_doctor_${id}`);
    const body = await res.body();
    expect(body.subarray(0, 4).toString('latin1')).toBe('%PDF');
  });

  test('جدول النوبات الأسبوعي يُفتح ويُحفظ دون تغيير البيانات', async ({ page, request }) => {
    const headers = await authHeader(request);
    const id = await firstDoctorId(request, headers);
    const before = await (await request.get(`/doctors/${id}/schedule`, { headers })).json();

    await login(page);
    await openDoctors(page);
    // ترتيب الصفوف في الواجهة = ترتيب قائمة الأطباء (أول صف = rows[0])
    await page.locator('#tbl tbody tr').first()
      .locator('button[title="نوبات العمل"]').click();

    await expect(page.locator('#modal-back')).toHaveClass(/show/);
    await expect(page.locator('#modal-title')).toContainText('نوبات العمل');
    await expect(page.locator('#modal-body tbody tr')).toHaveCount(7); // أيام الأسبوع
    await expect(page.locator('#sc-s-0')).toBeVisible();
    await expect(page.locator('#sc-e-6')).toBeVisible();

    // حفظ الأسبوع كما هو (لا يغيّر البيانات) ثم التحقق من المطابقة
    await page.click('#modal-body button:has-text("حفظ الأسبوع")');
    await expect(page.locator('#toast')).toContainText('حُفظت نوبات الأسبوع');
    await expect(page.locator('#modal-back')).not.toHaveClass(/show/);

    const after = await (await request.get(`/doctors/${id}/schedule`, { headers })).json();
    const active = before.filter((e: { is_active?: boolean }) => e.is_active !== false);
    expect(after).toEqual(active);
  });

  test('الوضع الداكن يتبع تفضيل النظام ويبقى بعد إعادة التحميل', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await login(page);

    // تفضيل النظام داكن ⇒ الثيم الداكن تلقائيًا دون إعداد مسبق
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('dark');
    await expect(page.locator('#theme-btn')).toHaveText('☀️');

    // التبديل اليدوي يحفظ الاختيار ويبقى بعد إعادة التحميل
    await page.click('#theme-btn');
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('light');
    await page.reload();
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('light');
    expect(await page.evaluate(() => localStorage.getItem('hms_theme'))).toBe('light');
    await expect(page.locator('#app-view')).toBeVisible();
    expect(APP).toBe('/ui/');
  });
});
