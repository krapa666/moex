const { test, expect } = require('@playwright/test');

test('shows the Watchlist workspace shell with unified navigation', async ({ page }) => {
  await page.route('**/api/tables', (route) => route.fulfill({ json: [] }));
  await page.goto('/watchlist/');

  await expect(page.getByRole('heading', { name: 'Watchlist', exact: true })).toBeVisible();
  await expect(page.locator('.app-nav-link.active')).toHaveText('Watchlist');
  await expect(page.locator('.watchlist-summary-card')).toHaveCount(4);
  await expect(page.locator('.watchlist-score-guide')).toContainText('Приоритет');
  await expect(page.locator('[data-watchlist-empty]')).toContainText('Нет таблиц оценок');
  await expect(page.getByRole('link', { name: 'Открыть оценки' })).toHaveAttribute('href', '/');
  await expect(page.getByRole('link', { name: 'Открыть объёмы' })).toHaveAttribute('href', '/volumes/');
});

test('adds Watchlist to the existing application navigation', async ({ page }) => {
  for (const path of ['/', '/dashboard/', '/volumes/']) {
    await page.goto(path);
    await expect(page.getByRole('link', { name: 'Watchlist', exact: true })).toHaveAttribute('href', '/watchlist/');
  }
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 1024, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`Watchlist has no horizontal page overflow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/watchlist/');

    const layout = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));

    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  });
}
