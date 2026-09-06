const { test, expect } = require('@playwright/test');

const robustness = {
  snapshot: 'pre_year',
  min_sources: 2,
  observations: 12,
  tickers: 2,
  years: 2,
  weighted_median_delta_pp: 2.6,
  weighted_mean_delta_pp: 1.8,
  positive_ticker_slices: 1,
  ticker_slices: 2,
  positive_year_slices: 2,
  year_slices: 2,
  ticker_jackknife_preserved: 1,
  ticker_jackknife_cases: 2,
  year_jackknife_preserved: 2,
  year_jackknife_cases: 2,
  positive_parameter_cases: 25,
  parameter_cases: 27,
  parameter_min_median_delta_pp: -0.4,
  parameter_max_median_delta_pp: 4.1,
  by_year: [
    {
      dimension: 'year', key: '2024', observations: 5, tickers: 2, years: 1,
      baseline_median_smape_percent: 14, weighted_median_smape_percent: 12,
      weighted_median_delta_pp: 2, baseline_mean_smape_percent: 15,
      weighted_mean_smape_percent: 13.5, weighted_mean_delta_pp: 1.5,
    },
    {
      dimension: 'year', key: '2025', observations: 7, tickers: 2, years: 1,
      baseline_median_smape_percent: 13, weighted_median_smape_percent: 9.5,
      weighted_median_delta_pp: 3.5, baseline_mean_smape_percent: 14,
      weighted_mean_smape_percent: 11.7, weighted_mean_delta_pp: 2.3,
    },
  ],
  by_ticker: [
    {
      dimension: 'ticker', key: 'SBER', observations: 6, tickers: 1, years: 2,
      baseline_median_smape_percent: 12, weighted_median_smape_percent: 8,
      weighted_median_delta_pp: 4, baseline_mean_smape_percent: 13,
      weighted_mean_smape_percent: 9, weighted_mean_delta_pp: 4,
    },
    {
      dimension: 'ticker', key: 'GAZP', observations: 6, tickers: 1, years: 2,
      baseline_median_smape_percent: 10, weighted_median_smape_percent: 11,
      weighted_median_delta_pp: -1, baseline_mean_smape_percent: 11,
      weighted_mean_smape_percent: 11.5, weighted_mean_delta_pp: -0.5,
    },
  ],
  jackknife_year: [],
  jackknife_ticker: [],
  parameter_sweep: [
    {
      shrinkage_samples: 2, error_floor_percent: 2.5, relative_score_cap: 1.5,
      observations: 12, weighted_median_smape_percent: 13.4,
      weighted_mean_smape_percent: 14, weighted_median_delta_pp: -0.4,
      weighted_mean_delta_pp: -0.1,
    },
    {
      shrinkage_samples: 5, error_floor_percent: 5, relative_score_cap: 2,
      observations: 12, weighted_median_smape_percent: 10.4,
      weighted_mean_smape_percent: 12.2, weighted_median_delta_pp: 2.6,
      weighted_mean_delta_pp: 1.8,
    },
  ],
};

async function mockApi(page) {
  const snapshots = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'guest', is_admin: false } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Арсагера' },
        { id: 2, table_number: 2, analyst_name: 'fin-vista (модель)' },
      ] });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/consensus-backtest') {
      return route.fulfill({ json: { observations: 0, tickers: 0, years: 0, methods: [] } });
    }
    if (url.pathname === '/api/analytics/consensus-backtest/robustness') {
      snapshots.push(url.searchParams.get('snapshot'));
      return route.fulfill({ json: robustness });
    }
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
  return snapshots;
}

test('analytics renders public robustness diagnostics and follows snapshot selector', async ({ page }) => {
  const snapshots = await mockApi(page);
  await page.goto('/analytics/');

  const section = page.locator('[data-consensus-robustness]');
  await expect(section).toBeVisible();
  await expect(page.locator('[data-consensus-robustness-status]')).toContainText('12 наблюдений');
  await expect(page.locator('[data-consensus-robustness-summary]')).toContainText('параметры: 25/27');
  await expect(page.locator('[data-consensus-robustness-summary]')).toContainText('-0,4 п.п. … +4,1 п.п.');

  const years = page.locator('[data-consensus-robustness-year-body] tr');
  await expect(years).toHaveCount(2);
  await expect(years.first()).toContainText('2024');

  const tickers = page.locator('[data-consensus-robustness-ticker-body] tr');
  await expect(tickers).toHaveCount(2);
  await expect(tickers.first()).toContainText('GAZP');
  await expect(tickers.first()).toContainText('-1 п.п.');
  await expect(tickers.nth(1)).toContainText('SBER');

  await expect(section).not.toContainText('Арсагера');
  await expect(section).not.toContainText('fin-vista');

  await page.locator('[data-accuracy-snapshot]').selectOption('mid_year');
  await expect.poll(() => snapshots.includes('mid_year')).toBe(true);
});
