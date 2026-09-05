const { test, expect } = require('@playwright/test');

test('shows the dashboard shell with unified navigation', async ({ page }) => {
  await page.goto('/dashboard/');

  await expect(page.getByRole('heading', { name: 'Обзор рынка' })).toBeVisible();
  await expect(page.locator('.app-nav-link.active')).toHaveText('Обзор');
  await expect(page.locator('.dashboard-kpi-card')).toHaveCount(4);
  await expect(page.locator('.dashboard-panel')).toHaveCount(2);
  await expect(page.getByRole('link', { name: 'Оценки', exact: true })).toHaveAttribute('href', '/');
  await expect(page.getByRole('link', { name: 'Объёмы', exact: true })).toHaveAttribute('href', '/volumes/');
});

test('adds the dashboard entry to forecast and volume navigation', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Обзор', exact: true })).toHaveAttribute('href', '/dashboard/');

  await page.goto('/volumes/');
  await expect(page.getByRole('link', { name: 'Обзор', exact: true })).toHaveAttribute('href', '/dashboard/');
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 1024, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`dashboard has no horizontal page overflow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/dashboard/');

    const layout = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));

    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  });
}
