const { test, expect } = require('@playwright/test');

const todayRevisions = [
  {
    id: 12,
    stock_row_id: 10,
    table_id: 1,
    ticker: 'SBER',
    analyst_name: 'Основной',
    forecast_start_year: 2026,
    event_type: 'updated',
    changed_by: 'local-network',
    shares_billion: 20,
    pe_avg_5y: 5,
    current_price: 300,
    net_profit_year_map: { 2026: 1400 },
    dividend_year_map: { 2026: 20 },
    net_profit_source_comment: 'Повышение прогноза после отчёта',
    forecast_price_year1: 350,
    forecast_price_year2: null,
    upside_percent_year1: 23.3,
    upside_percent_year2: null,
    created_at: '2026-09-05T10:00:00Z',
  },
  {
    id: 11,
    stock_row_id: 20,
    table_id: 2,
    ticker: 'GAZP',
    analyst_name: 'Консервативный',
    forecast_start_year: 2026,
    event_type: 'created',
    changed_by: 'local-network',
    shares_billion: 23.67,
    pe_avg_5y: 4.2,
    current_price: 130,
    net_profit_year_map: { 2026: 900 },
    dividend_year_map: { 2026: 12 },
    net_profit_source_comment: null,
    forecast_price_year1: 159.7,
    forecast_price_year2: null,
    upside_percent_year1: 32.1,
    upside_percent_year2: null,
    created_at: '2026-09-05T08:30:00Z',
  },
];

async function mockTodayApi(page, revisions = todayRevisions) {
  let sinceValue = null;
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/tables') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') {
      if (url.searchParams.has('since')) {
        sinceValue = url.searchParams.get('since');
        return route.fulfill({ json: revisions });
      }
      return route.fulfill({ json: [] });
    }
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
  return () => sinceValue;
}

test('shows forecast revisions saved today with links to ticker history', async ({ page }) => {
  const getSinceValue = await mockTodayApi(page);
  await page.goto('/analytics/');

  await expect(page.locator('[data-analytics-today-status]')).toHaveText('Ревизий сегодня: 2');
  const items = page.locator('[data-analytics-today-revision]');
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText('SBER');
  await expect(items.first()).toContainText('Основной');
  await expect(items.first()).toContainText('Fair value 350 ₽');
  await expect(items.first()).toContainText('ЧП 2026: 1 400 млрд ₽');
  await expect(items.first()).toContainText('Повышение прогноза после отчёта');
  await expect(items.first()).toHaveAttribute('href', '/analytics/?ticker=SBER&table_id=1');

  const sinceValue = getSinceValue();
  expect(sinceValue).toBeTruthy();
  expect(Number.isNaN(Date.parse(sinceValue))).toBe(false);
});

test('shows a clear state when there are no forecast revisions today', async ({ page }) => {
  await mockTodayApi(page, []);
  await page.goto('/analytics/');

  await expect(page.locator('[data-analytics-today-status]')).toHaveText('Ревизий сегодня: 0');
  await expect(page.locator('[data-analytics-today-empty]')).toBeVisible();
  await expect(page.locator('[data-analytics-today-list]')).toBeHidden();
});

test('today changes cards do not create horizontal overflow on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockTodayApi(page);
  await page.goto('/analytics/');
  await expect(page.locator('[data-analytics-today-revision]')).toHaveCount(2);

  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
});
