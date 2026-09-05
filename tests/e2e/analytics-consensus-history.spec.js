const { test, expect } = require('@playwright/test');

const tables = [
  { id: 1, table_number: 1, analyst_name: 'Основной', forecast_start_year: 2026 },
  { id: 2, table_number: 2, analyst_name: 'Консервативный', forecast_start_year: 2026 },
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
    current_price: 300,
    forecast_price_year1: 350,
    forecast_price_year2: null,
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
    current_price: 300,
    forecast_price_year1: 247.5,
    forecast_price_year2: null,
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
    current_price: 300,
    forecast_price_year1: 330,
    forecast_price_year2: null,
    created_at: '2026-09-03T09:00:00Z',
  },
];

async function mockAnalyticsApi(page, { isAdmin = true } = {}) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: isAdmin ? 'local-network' : 'guest', is_admin: isAdmin } });
    }
    if (url.pathname === '/api/tables') return route.fulfill({ json: tables });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') {
      if (url.searchParams.get('ticker') !== 'SBER') return route.fulfill({ json: [] });
      const tableId = url.searchParams.get('table_id');
      const rows = tableId
        ? revisions.filter((revision) => String(revision.table_id) === tableId)
        : revisions;
      return route.fulfill({ json: rows });
    }
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('reconstructs median target and spread from saved revisions', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-consensus-history-panel]');
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-consensus-history-kpi="points"]')).toHaveText('3');
  await expect(panel.locator('[data-consensus-history-kpi="median"]')).toHaveText('298,75 ₽');
  await expect(panel.locator('[data-consensus-history-kpi="spread"]')).toHaveText('34,3 %');
  await expect(panel.locator('[data-consensus-history-kpi="targets"]')).toHaveText('2');
  await expect(panel.locator('[data-consensus-history-median-point]')).toHaveCount(3);
  await expect(panel.locator('[data-consensus-history-spread-point]')).toHaveCount(2);
  await expect(panel.locator('[data-consensus-history-row]')).toHaveCount(3);
  await expect(panel.locator('[data-consensus-history-row="3"]')).toContainText('298,75 ₽');
  await expect(panel.locator('[data-consensus-history-row="3"]')).toContainText('разброс 34,3 %');
  await expect(panel.locator('[data-consensus-history-median-chart] svg')).toHaveAttribute(
    'aria-label',
    'Динамика медианной цели SBER по сохранённым ревизиям',
  );
  await expect(panel.locator('[data-consensus-history-spread-chart] svg')).toHaveAttribute(
    'aria-label',
    'Динамика разброса целей SBER по сохранённым ревизиям',
  );
});

test('analyst filter does not narrow historical consensus reconstruction', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-consensus-history-panel]');
  await expect(panel.locator('[data-consensus-history-kpi="points"]')).toHaveText('3');
  await page.locator('#analytics-table').selectOption('2');

  await expect(page.locator('[data-analytics-revision]')).toHaveCount(1);
  await expect(panel.locator('[data-consensus-history-kpi="points"]')).toHaveText('3');
  await expect(panel.locator('[data-consensus-history-kpi="median"]')).toHaveText('298,75 ₽');
  await expect(panel.locator('[data-consensus-history-median-point]')).toHaveCount(3);
});

test('historical consensus does not expose analyst names to guests', async ({ page }) => {
  await mockAnalyticsApi(page, { isAdmin: false });
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-consensus-history-panel]');
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-consensus-history-kpi="points"]')).toHaveText('3');
  await expect(panel).not.toContainText('Основной');
  await expect(panel).not.toContainText('Консервативный');
});

test('historical consensus stays inside the mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');

  await expect(page.locator('[data-consensus-history-panel]')).toBeVisible();
  await expect(page.locator('[data-consensus-history-median-point]')).toHaveCount(3);

  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
});
