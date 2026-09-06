const { test, expect } = require('@playwright/test');

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'guest', is_admin: false } });
    }
    if (url.pathname === '/api/tables') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits/coverage') {
      return route.fulfill({
        json: {
          snapshot: 'pre_year',
          start_year: 2021,
          end_year: 2025,
          forecast_pairs: 0,
          covered_pairs: 0,
          missing_forecast_pairs: 0,
          missing_actual_records: 0,
          coverage_percent: 0,
          forecast_tickers: 0,
          covered_tickers: 0,
          actual_records: 12,
          actual_tickers: 4,
          by_year: [
            {
              fiscal_year: 2025,
              forecast_pairs: 0,
              covered_pairs: 0,
              missing_forecast_pairs: 0,
              coverage_percent: 0,
              actual_records: 4,
            },
          ],
          by_source: [],
          missing_actuals: [],
        },
      });
    }
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

test('actual corpus remains visible when forecast-pair denominator is still zero', async ({ page }) => {
  await mockApi(page);
  await page.goto('/analytics/');

  const panel = page.locator('[data-actual-coverage]');
  await expect(panel).toBeVisible();
  await expect(page.locator('[data-actual-coverage-kpi="coverage"]')).toHaveText('н/д');
  await expect(page.locator('[data-actual-coverage-kpi="actuals"]')).toHaveText('12');
  await expect(page.locator('[data-actual-coverage-status]')).toContainText('12 фактов');
  await expect(page.locator('[data-actual-coverage-empty]')).toContainText('Coverage ещё не применим');
  await expect(page.locator('[data-actual-coverage-year-body]')).toContainText('2025');
  await expect(page.locator('[data-actual-coverage-year-body]')).toContainText('н/д');
});
