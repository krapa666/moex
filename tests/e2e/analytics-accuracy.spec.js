const { test, expect } = require('@playwright/test');

const tables = [
  { id: 1, table_number: 1, analyst_name: 'Арсагера' },
  { id: 2, table_number: 2, analyst_name: 'fin-vista (модель)' },
];

const accuracy = [
  {
    table_id: 1,
    analyst_name: 'Арсагера',
    samples: 12,
    tickers: 8,
    years: 2,
    median_smape_percent: 11.2,
    mean_smape_percent: 13.4,
    median_absolute_error_billion_rub: 42.0,
    mean_absolute_error_billion_rub: 51.5,
    mean_bias_billion_rub: -7.5,
    sign_accuracy_percent: 100,
    eligible: true,
    rank: 1,
  },
  {
    table_id: 2,
    analyst_name: 'fin-vista (модель)',
    samples: 3,
    tickers: 3,
    years: 1,
    median_smape_percent: 9.0,
    mean_smape_percent: 10.0,
    median_absolute_error_billion_rub: 30.0,
    mean_absolute_error_billion_rub: 33.0,
    mean_bias_billion_rub: 5.0,
    sign_accuracy_percent: 66.7,
    eligible: false,
    rank: null,
  },
];

const facts = [
  {
    id: 1,
    ticker: 'SBER',
    fiscal_year: 2025,
    net_profit_billion_rub: 1580.3,
    source_name: 'МСФО, отчёт эмитента',
    source_url: null,
    source_comment: null,
    reported_at: null,
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:00:00Z',
  },
];

async function mockAnalyticsApi(page, { isAdmin }) {
  let savedFact = null;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === '/api/auth/me') {
      return route.fulfill({
        json: isAdmin
          ? { username: 'local-network', is_admin: true }
          : { username: 'guest', is_admin: false },
      });
    }
    if (url.pathname === '/api/tables') return route.fulfill({ json: tables });
    if (url.pathname === '/api/analytics/source-accuracy') {
      return route.fulfill({ json: accuracy });
    }
    if (url.pathname === '/api/analytics/actual-net-profits') {
      return route.fulfill({ json: facts });
    }
    if (
      url.pathname === '/api/analytics/actual-net-profits/GAZP/2025'
      && request.method() === 'PUT'
    ) {
      savedFact = request.postDataJSON();
      return route.fulfill({
        json: {
          id: 2,
          ticker: 'GAZP',
          fiscal_year: 2025,
          ...savedFact,
          source_url: savedFact.source_url || null,
          source_comment: null,
          reported_at: null,
          created_at: '2026-09-06T03:00:00Z',
          updated_at: '2026-09-06T03:00:00Z',
        },
      });
    }
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
  return () => savedFact;
}

test('local analytics shows source ranking, facts and editable actual result form', async ({ page }) => {
  const getSavedFact = await mockAnalyticsApi(page, { isAdmin: true });
  await page.goto('/analytics/');

  const rows = page.locator('[data-accuracy-table-body] tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('Арсагера');
  await expect(rows.first()).toContainText('11,2%');
  await expect(rows.nth(1)).toContainText('fin-vista (модель)');
  await expect(rows.nth(1)).toContainText('< 5 наблюдений');

  await expect(page.locator('[data-actual-facts-body]')).toContainText('SBER');
  await expect(page.locator('[data-actual-facts-body]')).toContainText('1 580,3');
  await expect(page.locator('[data-actual-admin]')).toBeVisible();

  await page.locator('[data-actual-form] [name="ticker"]').fill('gazp');
  await page.locator('[data-actual-form] [name="fiscal_year"]').fill('2025');
  await page.locator('[data-actual-form] [name="net_profit_billion_rub"]').fill('125.5');
  await page.locator('[data-actual-form] [name="source_name"]').fill('Отчёт эмитента');
  await page.locator('[data-actual-form] button[type="submit"]').click();

  await expect(page.locator('[data-actual-form-status]')).toContainText('GAZP 2025');
  expect(getSavedFact()).toMatchObject({
    net_profit_billion_rub: 125.5,
    source_name: 'Отчёт эмитента',
  });
});

test('internet analytics masks source names and keeps actual results read-only', async ({ page }) => {
  await mockAnalyticsApi(page, { isAdmin: false });
  await page.goto('/analytics/');

  const rows = page.locator('[data-accuracy-table-body] tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('Аналитик 1');
  await expect(rows.first()).not.toContainText('Арсагера');
  await expect(rows.nth(1)).toContainText('Аналитик 2');
  await expect(rows.nth(1)).not.toContainText('fin-vista');
  await expect(page.locator('[data-actual-admin]')).toBeHidden();
  await expect(page.locator('[data-actual-facts-body]')).toContainText('SBER');
});
