const { test, expect } = require('@playwright/test');

const shadow = {
  ticker: 'SBER',
  target_year: 2026,
  training_snapshot: 'mid_year',
  as_of: '2026-09-06T07:00:00Z',
  shadow_available: true,
  reason: null,
  sources: 3,
  sources_with_training_history: 2,
  training_samples: 14,
  weighting_uses_history: true,
  max_source_weight_percent: 44.2,
  min_source_weight_percent: 23.1,
  median_net_profit_billion_rub: 1700,
  mean_net_profit_billion_rub: 1710,
  weighted_net_profit_billion_rub: 1750,
  median_target_price: 350,
  mean_target_price: 352,
  weighted_target_price: 365,
  weighted_vs_median_target_delta_rub: 15,
  weighted_vs_median_target_delta_percent: 4.2857,
  current_price: 320,
  median_market_gap_percent: 9.375,
  weighted_market_gap_percent: 14.0625,
};

function readiness(snapshot = 'pre_year') {
  return {
    snapshot,
    ready: false,
    gates_passed: 7,
    gates_total: 11,
    observations: 24,
    tickers: 9,
    years: 3,
    weighted_median_delta_pp: 2.2,
    weighted_mean_delta_pp: 1.1,
    ticker_slice_positive_ratio: 0.66,
    year_slice_positive_ratio: 0.67,
    ticker_jackknife_preserved_ratio: 0.82,
    year_jackknife_preserved_ratio: 1,
    parameter_positive_ratio: 0.89,
    worst_parameter_median_delta_pp: -0.2,
    gates: [
      { key: 'observations', label: 'Исторические наблюдения', passed: false, actual: '24', requirement: '>= 30' },
      { key: 'tickers', label: 'Покрытие бумаг', passed: false, actual: '9', requirement: '>= 10' },
      { key: 'years', label: 'Покрытие лет', passed: true, actual: '3', requirement: '>= 3' },
      { key: 'median_improvement', label: 'Улучшение median sMAPE', passed: true, actual: '+2.20 pp', requirement: '>= +1.0 pp' },
      { key: 'mean_improvement', label: 'Улучшение mean sMAPE', passed: true, actual: '+1.10 pp', requirement: '> 0 pp' },
      { key: 'ticker_slices', label: 'Положительные ticker-срезы', passed: true, actual: '66.0%', requirement: '>= 60.0%' },
      { key: 'year_slices', label: 'Положительные year-срезы', passed: true, actual: '67.0%', requirement: '>= 66.7%' },
      { key: 'ticker_jackknife', label: 'Leave-one-ticker-out', passed: true, actual: '82.0%', requirement: '>= 80.0%' },
      { key: 'year_jackknife', label: 'Leave-one-year-out', passed: true, actual: '100.0%', requirement: '>= 80.0%' },
      { key: 'parameter_sweep', label: 'Положительные наборы параметров', passed: true, actual: '89.0%', requirement: '>= 80.0%' },
      { key: 'worst_parameter_case', label: 'Худший набор параметров', passed: false, actual: '-0.20 pp', requirement: '> 0 pp' },
    ],
  };
}

async function mockApi(page) {
  const readinessSnapshots = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'guest', is_admin: false } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Арсагера', forecast_start_year: 2026 },
        { id: 2, table_number: 2, analyst_name: 'fin-vista (модель)', forecast_start_year: 2026 },
      ] });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/consensus-backtest') {
      return route.fulfill({ json: { observations: 0, tickers: 0, years: 0, methods: [] } });
    }
    if (url.pathname === '/api/analytics/consensus-backtest/robustness') {
      return route.fulfill({
        json: {
          snapshot: url.searchParams.get('snapshot') || 'pre_year',
          observations: 0,
          tickers: 0,
          years: 0,
          by_year: [],
          by_ticker: [],
          jackknife_year: [],
          jackknife_ticker: [],
          parameter_sweep: [],
        },
      });
    }
    if (url.pathname === '/api/analytics/consensus-readiness') {
      const snapshot = url.searchParams.get('snapshot') || 'pre_year';
      readinessSnapshots.push(snapshot);
      return route.fulfill({ json: readiness(snapshot) });
    }
    if (url.pathname === '/api/analytics/shadow-consensus') return route.fulfill({ json: shadow });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
  return readinessSnapshots;
}

test('analytics shows shadow weighted consensus without changing production panel', async ({ page }) => {
  await mockApi(page);
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-shadow-consensus]');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Production median');
  await expect(panel).toContainText('350 ₽');
  await expect(panel).toContainText('Shadow weighted');
  await expect(panel).toContainText('365 ₽');
  await expect(panel).toContainText('+4,3 %');
  await expect(panel).toContainText('14 training');
  await expect(panel).toContainText('Shadow-only');
  await expect(panel).not.toContainText('Арсагера');
  await expect(panel).not.toContainText('fin-vista');
});

test('readiness shows explicit failed gates and follows snapshot selector', async ({ page }) => {
  const snapshots = await mockApi(page);
  await page.goto('/analytics/');

  const section = page.locator('[data-consensus-readiness]');
  await expect(section).toBeVisible();
  await expect(page.locator('[data-consensus-readiness-status]')).toContainText('SHADOW · 7/11');
  await expect(page.locator('[data-consensus-readiness-summary]')).toContainText('Weighted consensus остаётся shadow-only');

  const rows = page.locator('[data-consensus-readiness-body] tr');
  await expect(rows).toHaveCount(11);
  await expect(rows.first()).toContainText('Исторические наблюдения');
  await expect(rows.first()).toContainText('WAIT');
  await expect(rows.last()).toContainText('Худший набор параметров');
  await expect(rows.last()).toContainText('WAIT');

  await page.locator('[data-accuracy-snapshot]').selectOption('mid_year');
  await expect.poll(() => snapshots.includes('mid_year')).toBe(true);
});
