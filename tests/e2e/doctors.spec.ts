// @ts-check
import { test, expect } from '@playwright/test';

test.describe("وحدة الأطباء", () => {
  test("صفحة الأطباء تُحمّل", async ({ page }) => {
    await page.goto("/doctors");
    await expect(page.locator("text=الأطباء")).toBeVisible();
  });

  test("التقرير المقارن يُحمّل", async ({ page }) => {
    await page.goto("/doctors/performance/report.pdf");
    const cd = page.response()?.headers()["content-disposition"] ?? "";
    expect(cd).toContain("doctors_performance");
  });

  test("بطاقة الترخيص تُحمّل", async ({ page }) => {
    await page.goto("/doctors/1/license.pdf");
    const cd = page.response()?.headers()["content-disposition"] ?? "";
    expect(cd).toContain("license_doctor");
  });

  test("النوبات الأسبوعية تُعرض", async ({ page }) => {
    await page.goto("/doctors/1/schedule");
    await expect(page.locator("table")).toBeVisible();
  });
});
