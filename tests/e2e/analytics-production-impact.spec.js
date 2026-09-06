const { test, expect } = require('@playwright/test');

const impactPayload = {
  impact: {
    generated_at: '2026-09-06T09:00:00Z',
    top_n: 10,
    universe_tickers: 20,
    comparable_tickers: 18,
    comparable_coverage_percent: 90,
    median_abs_target_delta_percent: 3.1,
    max_abs_target_delta_percent: 12.5,
    median_abs_expected_return_delta_pp: 2.4,
    return_sign_flip_tickers: 1,
    return_sign_flip_percent: 5,
    rank_correlation_spearman: 0.96,
    mean_abs_rank_change: 1.4,
    max_abs_rank_change: 5,
    top_n_overlap_tickers: 9,
    top_n_overlap_percent: 90,
    top_n_entered: ['LKOH'],
    top_n_exited: ['ROSN'],
    mean_abs_watchlist_score_delta: 3.2,
    items: [
      {
        ticker: 'LKOH', target_year: 2027, current_price: 7000,
        median_target_price: 8000, weighted_target_price: 8800,
        target_delta_rub: 800, target_delta_percent: 10,
        median_expected_return_percent: 20, weighted_expected_return_percent: 30,
        expected_return_delta_pp: 10, expected_return_sign_changed: false,
        volume_signal_status: 'signal', median_watchlist_score: 39,
        weighted_watchlist_score: 49, watchlist_score_delta: 10,
        median_rank: 12, weighted_rank: 8, rank_delta: -4,
        in_median_top_n: false, in_weighted_top_n: true,
      },
      {
        ticker: 'ROSN', target_year: 2027, current_price: 500,
        median_target_price: 650, weighted_target_price: 600,
        target_delta_rub: -50, target_delta_percent: -7.6923,
        median_expected_return_percent: 25, weighted_expected_return_percent: 15,
        expected_return_delta_pp: -10, expected_return_sign_changed: false,
        volume_signal_status: 'normal', median_watchlist_score: 30,
        weighted_watchlist_score: 20, watchlist_score_delta: -10,
        median_rank: 8, weighted_rank: 13, rank_delta: 5,
        in_median_top_n: true, in_weighted_top_n: false,
      },
    ],
  },
  promotion: {
    generated_at: '2026-09-06T09:00:00Z',
    status: 'OBSERVE',
    gates_passed: 8,
    gates_total: 10,
    historical_snapshot: 'mid_year',
    historical_readiness: true,
    forward_history_days: 30,
    gates: [
      { key: 'historical_readiness', label: 'Исторический readiness', passed: true, actual: '11/11', requirement: '11/11 PASS' },
      { key: 'forward_observation_span', label: 'Forward observation span', passed: false, actual: '3.0 d', requirement: '>= 7 d median' },
    ],
  },
};

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/analytics/production-impact') {
      return route.fulfill({ json: impactPayload });
    }
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'guest', is_admin: false } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Скрытый источник', forecast_start_year: 2027 },
      ] });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('analytics renders portfolio production impact and promotion dossier without source identities', async ({ page }) => {
  await mockApi(page);
  await page.goto('/analytics/');

  const panel = page.locator('[data-production-impact]');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Production impact simulator');
  await expect(page.locator('[data-production-impact-status]')).toContainText('OBSERVE · 8/10');
  await expect(panel).toContainText('0,96');
  await expect(panel).toContainText('90,0 %');
  await expect(panel).toContainText('Forward observation span');
  await expect(panel).toContainText('WAIT');
  await expect(panel).toContainText('гипотетическая sensitivity');

  const rows = page.locator('[data-production-impact-ticker]');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('LKOH');
  await expect(rows.nth(0)).toContainText('входит');
  await expect(rows.nth(1)).toContainText('ROSN');
  await expect(rows.nth(1)).toContainText('выходит');

  await expect(panel).not.toContainText('Скрытый источник');
});

test('production impact controls request another portfolio window without changing production data', async ({ page }) => {
  const requests = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/analytics/production-impact') {
      requests.push(url.search);
      return route.fulfill({ json: impactPayload });
    }
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: { username: 'guest', is_admin: false } });
    if (url.pathname === '/api/tables') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: 'not mocked' } });
  });

  await page.goto('/analytics/');
  const panel = page.locator('[data-production-impact]');
  await expect(panel).toBeVisible();
  await panel.locator('[data-production-impact-top-n]').selectOption('20');
  await panel.locator('[data-production-impact-days]').selectOption('90');

  await expect.poll(() => requests.some((query) => query.includes('top_n=20') && query.includes('history_days=90'))).toBe(true);
  await expect(panel).toContainText('текущие Оценки и Watchlist не изменяются');
});
