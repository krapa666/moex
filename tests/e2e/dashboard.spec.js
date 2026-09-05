const { test, expect } = require('@playwright/test');

async function mockDashboardApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/tables') {
      await route.fulfill({
        json: [
          { id: 9, table_number: 2, analyst_name: 'Другой' },
          { id: 7, table_number: 1, analyst_name: 'Основной' },
        ],
      });
      return;
    }
    if (url.pathname === '/api/rows' && url.searchParams.get('table_id') === '7') {
      await route.fulfill({
        json: [
          { ticker: 'SBER', upside_percent_year1: 20 },
          { ticker: 'LKOH', upside_percent_year1: 40 },
          { ticker: 'GAZP', upside_percent_year1: null },
        ],
      });
      return;
    }
    if (url.pathname === '/api/volume/overview') {
      await route.fulfill({
        json: [
          { ticker: 'SBER', latest: { signal_status: 'signal' } },
          { ticker: 'LKOH', latest: { signal_status: 'normal' } },
          { ticker: 'GAZP', latest: { signal_status: 'signal' } },
        ],
      });
      return;
    }
    if (url.pathname === '/api/volume/runs/latest') {
      await route.fulfill({
        json: {
          status: 'success',
          started_at: '2026-09-05T09:25:00Z',
          finished_at: '2026-09-05T09:30:00Z',
        },
      });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: 'Unexpected dashboard request' } });
  });
}

test('shows the dashboard shell with unified navigation', async ({ page }) => {
  await page.goto('/dashboard/');

  await expect(page.getByRole('heading', { name: 'Обзор рынка' })).toBeVisible();
  await expect(page.locator('.app-nav-link.active')).toHaveText('Обзор');
  await expect(page.locator('.dashboard-kpi-card')).toHaveCount(4);
  await expect(page.locator('.dashboard-panel')).toHaveCount(2);
  await expect(page.getByRole('link', { name: 'Оценки', exact: true })).toHaveAttribute('href', '/');
  await expect(page.getByRole('link', { name: 'Объёмы', exact: true })).toHaveAttribute('href', '/volumes/');
});

test('loads valuation and volume KPI aggregates from existing APIs', async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto('/dashboard/');

  await expect(page.locator('[data-dashboard-kpi="securities"]')).toHaveText('3');
  await expect(page.locator('[data-dashboard-kpi="median-upside"]')).toHaveText('30,0 %');
  await expect(page.locator('[data-dashboard-kpi="volume-signals"]')).toHaveText('2');
  await expect(page.locator('[data-dashboard-kpi="last-volume-run"]')).toContainText('05.09');
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
