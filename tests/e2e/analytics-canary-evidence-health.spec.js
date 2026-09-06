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
    items: [],
  },
  promotion: {
    generated_at: '2026-09-06T12:00:00Z', status: 'READY_FOR_MANUAL_PROMOTION',
    gates_passed: 10, gates_total: 10, historical_snapshot: 'mid_year',
    historical_readiness: true, forward_history_days: 30, gates: [],
  },
};

const evidenceOverview = {
  generated_at: '2026-09-06T12:00:00Z', history_days: 30,
  configured_tickers: 1, tickers_with_evidence: 1, snapshots: 3,
  configured_weighted_hours: 18, weighted_hours: 18, fallback_hours: 0,
  weighted_uptime_percent: 100, fallback_incidents: 0, recoveries: 0,
  current_weighted_tickers: 1, current_fallback_tickers: 0,
  current_median_tickers: 0, current_unknown_tickers: 0,
  median_history_span_hours: 18, items: [],
};

const healthPayload = {
  generated_at: '2026-09-06T12:00:00Z', history_days: 30,
  canary_enabled: true, configured_tickers: 1, expected_interval_hours: 6,
  status: 'degraded', tickers_with_evidence: 1,
  healthy_tickers: 0, warming_up_tickers: 0, degraded_tickers: 1, stale_tickers: 0,
  fresh_tickers: 1, delayed_tickers: 0,
  missed_cycles_estimate: 1, gap_violations: 1,
  latest_capture_at: '2026-09-06T12:00:00Z', latest_capture_age_hours: 0,
  longest_gap_hours: 12, median_continuity_percent: 66.6667,
  items: [{
    ticker: 'AAA', status: 'degraded', reasons: ['capture_gaps_detected'],
    expected_interval_hours: 6, snapshots: 3,
    first_captured_at: '2026-09-05T18:00:00Z', last_captured_at: '2026-09-06T12:00:00Z',
    latest_age_hours: 0, history_span_hours: 18, observed_intervals: 2,
    gap_violations: 1, missed_cycles_estimate: 1, longest_gap_hours: 12,
    continuity_percent: 66.6667,
  }],
};

async function routeApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'guest', is_admin: false } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Source A', forecast_start_year: 2027 },
      ] });
    }
    if (url.pathname === '/api/analytics/production-impact') {
      return route.fulfill({ json: impactPayload });
    }
    if (url.pathname === '/api/analytics/consensus-canary') {
      return route.fulfill({ json: {
        enabled: true, tickers: ['AAA'], max_tickers: 5,
        safety_policy: 'weighted requires history and STABLE drift; otherwise median fallback',
        updated_at: '2026-09-05T18:00:00Z',
      } });
    }
    if (url.pathname === '/api/analytics/consensus-canary/evidence') {
      return route.fulfill({
        json: { ...evidenceOverview, history_days: Number(url.searchParams.get('days') || 30) },
      });
    }
    if (url.pathname === '/api/analytics/consensus-canary/evidence/health') {
      return route.fulfill({
        json: { ...healthPayload, history_days: Number(url.searchParams.get('days') || 30) },
      });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('public analytics exposes degraded capture health without source identity', async ({ page }) => {
  await routeApi(page);
  await page.goto('/analytics/');

  const panel = page.locator('[data-canary-evidence-health]');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Capture health');
  await expect(panel.locator('.canary-health-overall')).toHaveText('DEGRADED');
  await expect(panel).toContainText('Expected cadence');
  await expect(panel).toContainText('6,0 ч');
  await expect(panel).toContainText('Median continuity');
  await expect(panel).toContainText('66,7 %');
  await expect(panel).toContainText('Missed cycles est.');
  await expect(panel.locator('[data-canary-health-ticker="AAA"]')).toContainText('обнаружены пропуски capture');
  await expect(panel).not.toContainText('Source A');
});

test('capture health window reloads independently', async ({ page }) => {
  const requestedDays = [];
  await routeApi(page);
  await page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/analytics/consensus-canary/evidence/health') {
      requestedDays.push(url.searchParams.get('days'));
    }
  });
  await page.goto('/analytics/');

  const selector = page.locator('[data-canary-health-days]');
  await expect(selector).toBeVisible();
  await selector.selectOption('7');
  await expect.poll(() => requestedDays.includes('7')).toBe(true);
});
