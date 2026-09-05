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
          {
            ticker: 'SBER',
            current_price: 320.45,
            forecast_price_year1: 384.54,
            upside_percent_year1: 20,
          },
          {
            ticker: 'LKOH',
            current_price: 6000,
            forecast_price_year1: 8400,
            upside_percent_year1: 40,
          },
          {
            ticker: 'GAZP',
            current_price: 124.8,
            forecast_price_year1: null,
            upside_percent_year1: null,
          },
        ],
      });
      return;
    }
    if (url.pathname === '/api/volume/overview') {
      await route.fulfill({
        json: [
          {
            ticker: 'SBER',
            short_name: 'Сбербанк',
            latest: { trade_date: '2026-09-04', ratio: 4.4, signal_status: 'signal' },
          },
          {
            ticker: 'LKOH',
            short_name: 'ЛУКОЙЛ',
            latest: { trade_date: '2026-09-04', ratio: 7.1, signal_status: 'above_range' },
          },
          {
            ticker: 'GAZP',
            short_name: 'Газпром',
            latest: { trade_date: '2026-09-04', ratio: 5.8, signal_status: 'signal' },
          },
          {
            ticker: 'ROSN',
            short_name: 'Роснефть',
            latest: { trade_date: '2026-09-04', ratio: 1.2, signal_status: 'normal' },
          },
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
  await expect(page.getByRole('button', { name: 'Обновить данные' })).toBeVisible();
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
  await expect(page.locator('#dashboard-refresh-status')).toContainText('Обновлено');
});

test('refreshes dashboard data in place and blocks overlapping refreshes', async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto('/dashboard/');
  await expect(page.locator('[data-dashboard-kpi="securities"]')).toHaveText('3');
  await expect(page.locator('#dashboard-refresh-status')).toContainText('Обновлено');

  await page.evaluate(() => {
    window.__dashboardRefreshSentinel = 'alive';
  });

  let refreshTableRequests = 0;
  await page.route('**/api/tables', async (route) => {
    refreshTableRequests += 1;
    await new Promise((resolve) => setTimeout(resolve, 120));
    await route.fulfill({
      json: [
        { id: 9, table_number: 2, analyst_name: 'Другой' },
        { id: 7, table_number: 1, analyst_name: 'Основной' },
      ],
    });
  });
  await page.route(/\/api\/rows\?table_id=7$/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 120));
    await route.fulfill({
      json: [
        { ticker: 'SBER', current_price: 320.45, forecast_price_year1: 384.54, upside_percent_year1: 20 },
        { ticker: 'LKOH', current_price: 6000, forecast_price_year1: 8400, upside_percent_year1: 40 },
        { ticker: 'GAZP', current_price: 124.8, forecast_price_year1: null, upside_percent_year1: null },
        { ticker: 'ROSN', current_price: 510, forecast_price_year1: 816, upside_percent_year1: 60 },
      ],
    });
  });
  await page.route('**/api/volume/overview', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 120));
    await route.fulfill({
      json: [
        { ticker: 'SBER', short_name: 'Сбербанк', latest: { trade_date: '2026-09-05', ratio: 4.4, signal_status: 'signal' } },
        { ticker: 'LKOH', short_name: 'ЛУКОЙЛ', latest: { trade_date: '2026-09-05', ratio: 7.1, signal_status: 'above_range' } },
        { ticker: 'GAZP', short_name: 'Газпром', latest: { trade_date: '2026-09-05', ratio: 5.8, signal_status: 'signal' } },
        { ticker: 'ROSN', short_name: 'Роснефть', latest: { trade_date: '2026-09-05', ratio: 4.1, signal_status: 'signal' } },
      ],
    });
  });
  await page.route('**/api/volume/runs/latest', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 120));
    await route.fulfill({
      json: {
        status: 'success',
        started_at: '2026-09-05T11:40:00Z',
        finished_at: '2026-09-05T11:41:00Z',
      },
    });
  });

  const refreshButton = page.locator('#dashboard-refresh-btn');
  await page.evaluate(() => {
    const button = document.getElementById('dashboard-refresh-btn');
    button.click();
    button.click();
  });

  await expect(refreshButton).toBeDisabled();
  await expect(refreshButton).toHaveText('Обновление…');
  await expect(page.locator('#dashboard-refresh-status')).toHaveText('Обновление…');

  await expect(page.locator('[data-dashboard-kpi="securities"]')).toHaveText('4');
  await expect(page.locator('[data-dashboard-kpi="median-upside"]')).toHaveText('40,0 %');
  await expect(page.locator('[data-dashboard-kpi="volume-signals"]')).toHaveText('3');
  await expect(page.locator('[data-dashboard-opportunity="ROSN"]')).toBeVisible();
  await expect(page.locator('#dashboard-refresh-status')).toHaveAttribute('data-state', 'success');
  await expect(page.locator('#dashboard-refresh-status')).toContainText('Обновлено');
  await expect(refreshButton).toBeEnabled();
  await expect(refreshButton).toHaveText('Обновить данные');

  expect(refreshTableRequests).toBe(1);
  expect(await page.evaluate(() => window.__dashboardRefreshSentinel)).toBe('alive');
  await expect(page).toHaveURL('/dashboard/');
});

test('ranks valuation opportunities and anomalous volumes from the same API data', async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto('/dashboard/');

  const opportunities = page.locator('[data-dashboard-list="opportunities"]');
  await expect(opportunities).toBeVisible();
  await expect(page.locator('[data-dashboard-empty="opportunities"]')).toBeHidden();
  await expect(opportunities.locator('.dashboard-list-row')).toHaveCount(2);
  await expect.poll(() => opportunities.locator('.dashboard-list-row').evaluateAll(
    (rows) => rows.map((row) => row.dataset.dashboardOpportunity),
  )).toEqual(['LKOH', 'SBER']);
  await expect(opportunities.locator('.dashboard-list-row').first()).toContainText('40,0 %');
  await expect(opportunities.locator('.dashboard-list-row').first()).toContainText('8 400 ₽');
  await expect(opportunities.locator('.dashboard-list-row').first()).toHaveAttribute('href', '/?ticker=LKOH');

  const volumes = page.locator('[data-dashboard-list="volumes"]');
  await expect(volumes).toBeVisible();
  await expect(page.locator('[data-dashboard-empty="volumes"]')).toBeHidden();
  await expect(volumes.locator('.dashboard-list-row')).toHaveCount(3);
  await expect.poll(() => volumes.locator('.dashboard-list-row').evaluateAll(
    (rows) => rows.map((row) => row.dataset.dashboardVolume),
  )).toEqual(['LKOH', 'GAZP', 'SBER']);
  await expect(volumes.locator('.dashboard-list-row').first()).toContainText('7,1×');
  await expect(volumes.locator('.dashboard-list-row').first()).toContainText('Выше диапазона');
  await expect(volumes.locator('.dashboard-list-row').first()).toHaveAttribute('href', '/volumes/?ticker=LKOH');
  await expect(volumes).not.toContainText('ROSN');
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
