const { test, expect } = require('@playwright/test');

const tables = [
  {
    id: 1,
    table_number: 1,
    analyst_name: 'Тестовый аналитик',
    forecast_start_year: 2026,
  },
];

const rows = [
  {
    id: 101,
    table_id: 1,
    ticker: 'SBER',
    current_price: 320.45,
    shares_billion: 21.586,
    market_cap_billion_rub: 6916.46,
    pe_avg_5y: 6.2,
    net_profit_year_map: { 2026: 1800, 2027: 2100 },
    dividend_year_map: { 2026: 35, 2027: 42 },
    forecast_price_year1: 516.99,
    forecast_price_year2: 603.15,
    upside_percent_year1: 72.26,
    upside_percent_year2: 112.25,
    price_updated_at: '2026-08-09T02:30:00Z',
    net_profit_source_comment: 'Тестовый прогноз',
    status_message: null,
    shared_fields_editable: true,
  },
];

async function mockForecastApi(page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === 'GET' && url.pathname === '/api/auth/me') {
      await route.fulfill({ json: { username: 'test-admin', is_admin: true } });
      return;
    }
    if (request.method() === 'GET' && url.pathname === '/api/tables') {
      await route.fulfill({ json: tables });
      return;
    }
    if (request.method() === 'GET' && url.pathname === '/api/rows') {
      await route.fulfill({ json: rows });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: 'Unexpected test request' } });
  });
}

test('shows analytics in every application navbar without mobile overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });

  for (const path of ['/', '/dashboard/', '/watchlist/', '/analytics/', '/volumes/']) {
    await page.goto(path);

    const nav = page.locator('.app-nav');
    const analyticsLink = nav.getByRole('link', { name: 'Аналитика' });
    await expect(analyticsLink).toHaveAttribute('href', '/analytics/');

    const dimensions = await nav.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
  }
});

test('links the stock drawer to ticker forecast history', async ({ page }) => {
  await mockForecastApi(page);
  await page.goto('/');
  await expect(page.locator('#rows-table-body > tr')).toHaveCount(1);

  await page.locator('#rows-table-body > tr').first().getByRole('button', { name: 'Подробнее' }).click();

  const drawer = page.locator('#security-detail-overlay');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('link', { name: 'История прогноза' }))
    .toHaveAttribute('href', '/analytics/?ticker=SBER');
});
