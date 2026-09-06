const { test, expect } = require('@playwright/test');

const coverage = {
  snapshot: 'pre_year',
  start_year: 2021,
  end_year: 2025,
  forecast_pairs: 6,
  covered_pairs: 4,
  missing_forecast_pairs: 2,
  missing_actual_records: 1,
  coverage_percent: 66.6666667,
  forecast_tickers: 4,
  covered_tickers: 3,
  actual_records: 5,
  actual_tickers: 4,
  by_year: [
    {
      fiscal_year: 2025,
      forecast_pairs: 6,
      covered_pairs: 4,
      missing_forecast_pairs: 2,
      coverage_percent: 66.6666667,
      actual_records: 5,
    },
  ],
  by_source: [
    {
      table_id: 1,
      analyst_name: 'Арсагера',
      forecast_pairs: 4,
      covered_pairs: 3,
      missing_forecast_pairs: 1,
      coverage_percent: 75,
      tickers: 4,
      years: 1,
    },
    {
      table_id: 2,
      analyst_name: 'Private model',
      forecast_pairs: 2,
      covered_pairs: 1,
      missing_forecast_pairs: 1,
      coverage_percent: 50,
      tickers: 2,
      years: 1,
    },
  ],
  missing_actuals: [{ ticker: 'GAZP', fiscal_year: 2025, sources: 2 }],
};

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'guest', is_admin: false } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({
        json: [
          { id: 1, table_number: 1, analyst_name: 'Арсагера' },
          { id: 2, table_number: 2, analyst_name: 'Private model' },
        ],
      });
    }
    if (url.pathname === '/api/analytics/actual-net-profits/coverage') {
      return route.fulfill({ json: coverage });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/consensus-backtest') {
      return route.fulfill({
        json: {
          snapshot: 'pre_year',
          min_sources: 2,
          shrinkage_samples: 5,
          error_floor_percent: 5,
          relative_score_cap: 2,
          observations: 0,
          tickers: 0,
          years: 0,
          methods: [],
        },
      });
    }
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('actual result coverage shows completed-year evidence and masks source names on internet access', async ({ page }) => {
  await mockApi(page);
  await page.goto('/analytics/');

  const panel = page.locator('[data-actual-coverage]');
  await expect(panel).toBeVisible();
  await expect(page.locator('[data-actual-coverage-status]')).toContainText('4 из 6');
  await expect(page.locator('[data-actual-coverage-kpi="coverage"]')).toHaveText('66,7%');
  await expect(page.locator('[data-actual-coverage-kpi="missing"]')).toHaveText('1');

  const yearRows = page.locator('[data-actual-coverage-year-body] tr');
  await expect(yearRows).toHaveCount(1);
  await expect(yearRows.first()).toContainText('2025');
  await expect(yearRows.first()).toContainText('66,7%');

  const sourceRows = page.locator('[data-actual-coverage-source-body] tr');
  await expect(sourceRows).toHaveCount(2);
  await expect(sourceRows.first()).toContainText('Аналитик 1');
  await expect(sourceRows.nth(1)).toContainText('Аналитик 2');
  await expect(panel).not.toContainText('Арсагера');
  await expect(panel).not.toContainText('Private model');

  await expect(page.locator('[data-actual-coverage-missing-list]')).toContainText('GAZP 2025');
  await expect(page.locator('[data-actual-coverage-missing-list]')).toContainText('2 ист.');
});
