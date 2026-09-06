const { test, expect } = require('@playwright/test');

const impactPayload = {
  impact: {
    generated_at: '2026-09-06T12:00:00Z', top_n: 10,
    universe_tickers: 1, comparable_tickers: 1, comparable_coverage_percent: 100,
    median_abs_target_delta_percent: 1.8, max_abs_target_delta_percent: 1.8,
    median_abs_expected_return_delta_pp: 2, return_sign_flip_tickers: 0,
    return_sign_flip_percent: 0, rank_correlation_spearman: 1,
    mean_abs_rank_change: 0, max_abs_rank_change: 0,
    top_n_overlap_tickers: 1, top_n_overlap_percent: 100,
    top_n_entered: [], top_n_exited: [], mean_abs_watchlist_score_delta: 2,
    items: [{
      ticker: 'AAA', target_year: 2027, current_price: 100,
      median_target_price: 110, weighted_target_price: 112,
      target_delta_rub: 2, target_delta_percent: 1.818,
      median_expected_return_percent: 10, weighted_expected_return_percent: 12,
      expected_return_delta_pp: 2, expected_return_sign_changed: false,
      volume_signal_status: 'normal', median_watchlist_score: 10,
      weighted_watchlist_score: 12, watchlist_score_delta: 2,
      median_rank: 1, weighted_rank: 1, rank_delta: 0,
      in_median_top_n: true, in_weighted_top_n: true,
    }],
  },
  promotion: {
    generated_at: '2026-09-06T12:00:00Z', status: 'READY_FOR_MANUAL_PROMOTION',
    gates_passed: 10, gates_total: 10, historical_snapshot: 'mid_year',
    historical_readiness: true, forward_history_days: 30, gates: [],
  },
};

const overview = {
  generated_at: '2026-09-06T12:00:00Z', history_days: 30,
  configured_tickers: 1, tickers_with_evidence: 1, snapshots: 4,
  configured_weighted_hours: 18, weighted_hours: 12, fallback_hours: 6,
  weighted_uptime_percent: 66.6667, fallback_incidents: 1, recoveries: 1,
  current_weighted_tickers: 1, current_fallback_tickers: 0, current_median_tickers: 0,
  median_history_span_hours: 18,
  items: [{
    ticker: 'AAA', history_days: 30, snapshots: 4, target_years: [2027], latest_target_year: 2027,
    first_captured_at: '2026-09-05T18:00:00Z', last_captured_at: '2026-09-06T12:00:00Z',
    history_span_hours: 18, configured_weighted_hours: 18, weighted_hours: 12,
    fallback_hours: 6, weighted_uptime_percent: 66.6667, fallback_incidents: 1,
    recoveries: 1, longest_weighted_run_hours: 6, longest_fallback_run_hours: 6,
    fallback_reason_counts: { drift_watch: 1 }, current_canary_enabled: true,
    current_in_allowlist: true, current_configured_mode: 'weighted_canary',
    current_effective_mode: 'weighted', current_safety_status: 'stable',
    current_fallback_reason: null, current_median_target_price: 110,
    current_weighted_target_price: 112, current_active_target_price: 112,
    current_median_expected_return_percent: 10, current_weighted_expected_return_percent: 12,
    current_active_expected_return_percent: 12,
  }],
};

const history = [
  {
    id: 1, ticker: 'AAA', target_year: 2027, captured_at: '2026-09-05T18:00:00Z',
    canary_enabled: true, in_allowlist: true, configured_mode: 'weighted_canary',
    effective_mode: 'weighted', active_available: true, safety_status: 'stable', fallback_reason: null,
    sources: 3, current_price: 100, median_target_price: 110, weighted_target_price: 112,
    active_target_price: 112, median_expected_return_percent: 10,
    weighted_expected_return_percent: 12, active_expected_return_percent: 12,
  },
  {
    id: 2, ticker: 'AAA', target_year: 2027, captured_at: '2026-09-06T00:00:00Z',
    canary_enabled: true, in_allowlist: true, configured_mode: 'weighted_canary',
    effective_mode: 'median', active_available: true, safety_status: 'watch', fallback_reason: 'drift_watch',
    sources: 3, current_price: 100, median_target_price: 110, weighted_target_price: 115,
    active_target_price: 110, median_expected_return_percent: 10,
    weighted_expected_return_percent: 15, active_expected_return_percent: 10,
  },
  {
    id: 3, ticker: 'AAA', target_year: 2027, captured_at: '2026-09-06T06:00:00Z',
    canary_enabled: true, in_allowlist: true, configured_mode: 'weighted_canary',
    effective_mode: 'weighted', active_available: true, safety_status: 'stable', fallback_reason: null,
    sources: 3, current_price: 100, median_target_price: 110, weighted_target_price: 112,
    active_target_price: 112, median_expected_return_percent: 10,
    weighted_expected_return_percent: 12, active_expected_return_percent: 12,
  },
];

async function routeApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: { username: 'guest', is_admin: false } });
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Source A', forecast_start_year: 2027 },
        { id: 2, table_number: 2, analyst_name: 'Source B', forecast_start_year: 2027 },
      ] });
    }
    if (url.pathname === '/api/ticker-comparison') {
      return route.fulfill({ json: [
        { table_id: 1, table_number: 1, analyst_name: 'Source A', forecast_start_year: 2027, current_price: 100, years: [{ year: 2027, forecast_price: 110, upside_percent: 10 }] },
        { table_id: 2, table_number: 2, analyst_name: 'Source B', forecast_start_year: 2027, current_price: 100, years: [{ year: 2027, forecast_price: 112, upside_percent: 12 }] },
      ] });
    }
    if (url.pathname === '/api/analytics/production-impact') return route.fulfill({ json: impactPayload });
    if (url.pathname === '/api/analytics/consensus-canary') {
      return route.fulfill({ json: {
        enabled: true, tickers: ['AAA'], max_tickers: 5,
        safety_policy: 'weighted requires history and STABLE drift; otherwise median fallback',
        updated_at: '2026-09-05T18:00:00Z',
      } });
    }
    if (url.pathname === '/api/analytics/active-consensus') {
      return route.fulfill({ json: {
        ticker: 'AAA', target_year: 2027, active_available: true, reason: null,
        canary_enabled: true, in_allowlist: true, configured_mode: 'weighted_canary',
        effective_mode: 'weighted', safety_status: 'stable', fallback_reason: null,
        sources: 3, current_price: 100, median_target_price: 110, weighted_target_price: 112,
        active_target_price: 112, median_expected_return_percent: 10,
        weighted_expected_return_percent: 12, active_expected_return_percent: 12,
      } });
    }
    if (url.pathname === '/api/analytics/consensus-canary/evidence') {
      return route.fulfill({ json: { ...overview, history_days: Number(url.searchParams.get('days') || 30) } });
    }
    if (url.pathname === '/api/analytics/consensus-canary/evidence/ticker') {
      return route.fulfill({ json: { ...overview.items[0], history_days: Number(url.searchParams.get('days') || 30) } });
    }
    if (url.pathname === '/api/analytics/consensus-canary/evidence/history') return route.fulfill({ json: history });
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('public analytics shows time-weighted canary evidence and per-ticker timeline', async ({ page }) => {
  await routeApi(page);
  await page.goto('/analytics/?ticker=AAA');

  const overviewPanel = page.locator('[data-canary-evidence-overview]');
  await expect(overviewPanel).toBeVisible();
  await expect(overviewPanel).toContainText('Weighted uptime');
  await expect(overviewPanel).toContainText('66,7 %');
  await expect(overviewPanel).toContainText('Fallback incidents');
  await expect(overviewPanel.locator('[data-canary-evidence-ticker="AAA"]')).toContainText('WEIGHTED CANARY');
  await expect(overviewPanel).not.toContainText('Source A');
  await expect(overviewPanel).not.toContainText('Source B');

  const tickerPanel = page.locator('[data-canary-evidence-ticker-panel]');
  await expect(tickerPanel).toBeVisible();
  await expect(tickerPanel).toContainText('Canary evidence · AAA');
  await expect(tickerPanel).toContainText('FALLBACK');
  await expect(tickerPanel).toContainText('drift WATCH');
  await expect(tickerPanel).toContainText('112 ₽');
});

test('changing evidence window reloads overview with selected days', async ({ page }) => {
  const requestedDays = [];
  await routeApi(page);
  await page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/analytics/consensus-canary/evidence') {
      requestedDays.push(url.searchParams.get('days'));
    }
  });
  await page.goto('/analytics/');

  const selector = page.locator('[data-canary-evidence-days]');
  await expect(selector).toBeVisible();
  await selector.selectOption('7');
  await expect.poll(() => requestedDays.includes('7')).toBe(true);
});
