const { test, expect } = require('@playwright/test');

const tables = [
  { id: 1, table_number: 1, analyst_name: 'Основной' },
  { id: 2, table_number: 2, analyst_name: 'Консервативный' },
];

const revisions = [
  {
    id: 3,
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
    id: 2,
    stock_row_id: 20,
    table_id: 2,
    ticker: 'SBER',
    analyst_name: 'Консервативный',
    forecast_start_year: 2026,
    event_type: 'created',
    changed_by: 'local-network',
    shares_billion: 20,
    pe_avg_5y: 4.5,
    current_price: 300,
    net_profit_year_map: { 2026: 1100 },
    dividend_year_map: { 2026: 18 },
    net_profit_source_comment: null,
    forecast_price_year1: 247.5,
    forecast_price_year2: null,
    upside_percent_year1: -11.5,
    upside_percent_year2: null,
    created_at: '2026-09-04T11:00:00Z',
  },
  {
    id: 1,
    stock_row_id: 10,
    table_id: 1,
    ticker: 'SBER',
    analyst_name: 'Основной',
    forecast_start_year: 2026,
    event_type: 'created',
    changed_by: 'local-network',
    shares_billion: 20,
    pe_avg_5y: 5,
    current_price: 300,
    net_profit_year_map: { 2026: 1320 },
    dividend_year_map: { 2026: 20 },
    net_profit_source_comment: 'Первоначальная оценка',
    forecast_price_year1: 330,
    forecast_price_year2: null,
    upside_percent_year1: 16.7,
    upside_percent_year2: null,
    created_at: '2026-09-03T09:00:00Z',
  },
];

async function mockAnalyticsApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: tables });
    }
    if (url.pathname === '/api/analytics/forecast-revisions') {
      const ticker = url.searchParams.get('ticker');
      const tableId = url.searchParams.get('table_id');
      if (ticker !== 'SBER') return route.fulfill({ json: [] });
      const rows = tableId
        ? revisions.filter((revision) => String(revision.table_id) === tableId)
        : revisions;
      return route.fulfill({ json: rows });
    }
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('renders direct-linked forecast history with summary and revision deltas', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');

  await expect(page.getByRole('heading', { name: 'История прогнозов' })).toBeVisible();
  await expect(page.locator('.app-nav-link.active')).toHaveText('Аналитика');
  await expect(page.locator('#analytics-ticker')).toHaveValue('SBER');
  await expect(page.locator('[data-analytics-kpi="revisions"]')).toHaveText('3');
  await expect(page.locator('[data-analytics-kpi="analysts"]')).toHaveText('2');
  await expect(page.locator('[data-analytics-kpi="latest-fair"]')).toHaveText('350 ₽');

  const timeline = page.locator('[data-analytics-timeline]');
  await expect(timeline.locator('[data-analytics-revision]')).toHaveCount(3);
  await expect.poll(() => timeline.locator('[data-analytics-revision]').evaluateAll(
    (items) => items.map((item) => item.dataset.analyticsRevision),
  )).toEqual(['3', '2', '1']);
  await expect(timeline.locator('[data-analytics-revision="3"]')).toContainText('Fair value +20');
  await expect(timeline.locator('[data-analytics-revision="3"]')).toContainText('ЧП +80');
  await expect(timeline.locator('[data-analytics-revision="3"]')).toContainText('Повышение прогноза после отчёта');
});

test('filters forecast history by analyst and keeps the selection in the URL', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');
  await expect(page.locator('[data-analytics-revision]')).toHaveCount(3);

  await page.locator('#analytics-table').selectOption('2');

  await expect(page.locator('[data-analytics-revision]')).toHaveCount(1);
  await expect(page.locator('[data-analytics-revision="2"]')).toContainText('Консервативный');
  expect(new URL(page.url()).searchParams.get('table_id')).toBe('2');
  await expect(page.locator('[data-analytics-kpi="analysts"]')).toHaveText('1');
});

test('shows a clear empty state for a ticker without revisions', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/');

  await page.locator('#analytics-ticker').fill('GAZP');
  await page.getByRole('button', { name: 'Показать историю' }).click();

  await expect(page.locator('#analytics-status')).toHaveText('Ревизий: 0');
  await expect(page.locator('[data-analytics-empty]')).toContainText('История не найдена');
  await expect(page.locator('[data-analytics-timeline]')).toBeHidden();
  expect(new URL(page.url()).searchParams.get('ticker')).toBe('GAZP');
});

test('analytics history has no horizontal overflow on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');
  await expect(page.locator('[data-analytics-revision]')).toHaveCount(3);

  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
});
