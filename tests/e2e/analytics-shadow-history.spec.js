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

const history = [
  {
    id: 1,
    ticker: 'SBER',
    target_year: 2026,
    training_snapshot: 'mid_year',
    captured_at: '2026-09-03T07:00:00Z',
    sources: 3,
    sources_with_training_history: 2,
    training_samples: 14,
    weighting_uses_history: true,
    max_source_weight_percent: 44,
    min_source_weight_percent: 23,
    median_net_profit_billion_rub: 1680,
    weighted_net_profit_billion_rub: 1730,
    median_target_price: 345,
    weighted_target_price: 358,
    weighted_vs_median_target_delta_rub: 13,
    weighted_vs_median_target_delta_percent: 3.77,
    current_price: 318,
    median_market_gap_percent: 8.49,
    weighted_market_gap_percent: 12.58,
  },
  {
    id: 2,
    ticker: 'SBER',
    target_year: 2026,
    training_snapshot: 'mid_year',
    captured_at: '2026-09-04T07:00:00Z',
    sources: 3,
    sources_with_training_history: 2,
    training_samples: 14,
    weighting_uses_history: true,
    max_source_weight_percent: 44.2,
    min_source_weight_percent: 23.1,
    median_net_profit_billion_rub: 1690,
    weighted_net_profit_billion_rub: 1740,
    median_target_price: 348,
    weighted_target_price: 362,
    weighted_vs_median_target_delta_rub: 14,
    weighted_vs_median_target_delta_percent: 4.02,
    current_price: 319,
    median_market_gap_percent: 9.09,
    weighted_market_gap_percent: 13.48,
  },
  {
    id: 3,
    ticker: 'SBER',
    target_year: 2026,
    training_snapshot: 'mid_year',
    captured_at: '2026-09-05T07:00:00Z',
    sources: 3,
    sources_with_training_history: 2,
    training_samples: 14,
    weighting_uses_history: true,
    max_source_weight_percent: 44.2,
    min_source_weight_percent: 23.1,
    median_net_profit_billion_rub: 1700,
    weighted_net_profit_billion_rub: 1750,
    median_target_price: 350,
    weighted_target_price: 365,
    weighted_vs_median_target_delta_rub: 15,
    weighted_vs_median_target_delta_percent: 4.29,
    current_price: 320,
    median_market_gap_percent: 9.38,
    weighted_market_gap_percent: 14.06,
  },
];

const drift = {
  ticker: 'SBER',
  target_year: 2026,
  latest_training_snapshot: 'mid_year',
  status: 'watch',
  reasons: ['weight_concentration'],
  snapshots: 3,
  history_days: 30,
  history_span_hours: 48,
  first_captured_at: '2026-09-03T07:00:00Z',
  last_captured_at: '2026-09-05T07:00:00Z',
  latest_delta_percent: 4.29,
  previous_delta_percent: 4.02,
  delta_step_percentage_points: 0.27,
  median_abs_delta_percent: 4.02,
  max_abs_delta_percent: 4.29,
  latest_weight_concentration_ratio: 1.52,
  max_weight_concentration_ratio: 1.52,
  median_target_change_percent: 1.45,
  weighted_target_change_percent: 1.96,
  relative_movement_gap_percentage_points: 0.51,
  training_snapshot_changed: false,
};

async function mockApi(page, { emptyHistory = false } = {}) {
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
      return route.fulfill({ json: {
        snapshot: 'pre_year', observations: 0, tickers: 0, years: 0,
        by_year: [], by_ticker: [], jackknife_year: [], jackknife_ticker: [],
        parameter_sweep: [], readiness: null,
      } });
    }
    if (url.pathname === '/api/analytics/shadow-consensus/history') {
      return route.fulfill({ json: emptyHistory ? [] : history });
    }
    if (url.pathname === '/api/analytics/shadow-consensus/drift') {
      return route.fulfill({ json: emptyHistory ? { ...drift, status: 'insufficient', reasons: ['no_history'], snapshots: 0 } : drift });
    }
    if (url.pathname === '/api/analytics/shadow-consensus') return route.fulfill({ json: shadow });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('analytics renders forward shadow history and drift without source identities', async ({ page }) => {
  await mockApi(page);
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-shadow-history]');
  await expect(panel).toBeVisible();
  await expect(page.locator('[data-shadow-history-status]')).toContainText('WATCH · 3 точек');
  await expect(panel).toContainText('весовая концентрация повышена');
  await expect(panel).toContainText('1,52×');
  await expect(panel).toContainText('+4,3 %');

  await expect(page.locator('[data-shadow-history-chart] path')).toHaveCount(2);
  await expect(page.locator('[data-shadow-history-rows] tr')).toHaveCount(3);
  await expect(panel).toContainText('350 ₽');
  await expect(panel).toContainText('365 ₽');

  await expect(panel).not.toContainText('Арсагера');
  await expect(panel).not.toContainText('fin-vista');
});

test('analytics explains when forward history has not accumulated yet', async ({ page }) => {
  await mockApi(page, { emptyHistory: true });
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-shadow-history]');
  await expect(panel).toBeVisible();
  await expect(page.locator('[data-shadow-history-status]')).toContainText('Истории пока нет');
  await expect(page.locator('[data-shadow-history-empty]')).toContainText('forward shadow history ещё не накоплена');
});
