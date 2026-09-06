const { test, expect } = require('@playwright/test');

const impactPayload = {
  impact: {
    generated_at: '2026-09-06T10:00:00Z', top_n: 10,
    universe_tickers: 10, comparable_tickers: 10, comparable_coverage_percent: 100,
    median_abs_target_delta_percent: 1.2, max_abs_target_delta_percent: 3.4,
    median_abs_expected_return_delta_pp: 1.1, return_sign_flip_tickers: 0,
    return_sign_flip_percent: 0, rank_correlation_spearman: 0.98,
    mean_abs_rank_change: 0.8, max_abs_rank_change: 2,
    top_n_overlap_tickers: 10, top_n_overlap_percent: 100,
    top_n_entered: [], top_n_exited: [], mean_abs_watchlist_score_delta: 1.5,
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
    generated_at: '2026-09-06T10:00:00Z', status: 'READY_FOR_MANUAL_PROMOTION',
    gates_passed: 10, gates_total: 10, historical_snapshot: 'mid_year',
    historical_readiness: true, forward_history_days: 30,
    gates: [{
      key: 'historical_readiness', label: 'Исторический readiness', passed: true,
      actual: '11/11', requirement: '11/11 PASS',
    }],
  },
};

const activeWeighted = {
  ticker: 'AAA', target_year: 2027, active_available: true, reason: null,
  canary_enabled: true, in_allowlist: true, configured_mode: 'weighted_canary',
  effective_mode: 'weighted', safety_status: 'stable', fallback_reason: null,
  sources: 3, current_price: 100, median_target_price: 110,
  weighted_target_price: 112, active_target_price: 112,
  median_expected_return_percent: 10, weighted_expected_return_percent: 12,
  active_expected_return_percent: 12,
};

function tickerComparison() {
  return [
    {
      table_id: 1, table_number: 1, analyst_name: 'Source A', forecast_start_year: 2027,
      current_price: 100, years: [{ year: 2027, forecast_price: 110, upside_percent: 10 }],
    },
    {
      table_id: 2, table_number: 2, analyst_name: 'Source B', forecast_start_year: 2027,
      current_price: 100, years: [{ year: 2027, forecast_price: 112, upside_percent: 12 }],
    },
  ];
}

async function routeCommon(page, { isAdmin = false, active = activeWeighted, canary = null, onPut = null, onRollback = null } = {}) {
  let currentCanary = canary || {
    enabled: true, tickers: ['AAA'], max_tickers: 5,
    safety_policy: 'weighted requires history and STABLE drift; otherwise median fallback',
    updated_at: '2026-09-06T10:00:00Z',
  };

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: isAdmin ? 'local-network' : 'guest', is_admin: isAdmin } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Source A', forecast_start_year: 2027 },
        { id: 2, table_number: 2, analyst_name: 'Source B', forecast_start_year: 2027 },
      ] });
    }
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: tickerComparison() });
    if (url.pathname === '/api/analytics/active-consensus') return route.fulfill({ json: active });
    if (url.pathname === '/api/analytics/production-impact') return route.fulfill({ json: impactPayload });
    if (url.pathname === '/api/analytics/consensus-canary' && route.request().method() === 'GET') {
      return route.fulfill({ json: currentCanary });
    }
    if (url.pathname === '/api/analytics/consensus-canary' && route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON();
      if (onPut) onPut(payload);
      currentCanary = { ...currentCanary, enabled: payload.enabled, tickers: payload.tickers };
      return route.fulfill({ json: currentCanary });
    }
    if (url.pathname === '/api/analytics/consensus-canary/rollback') {
      if (onRollback) onRollback();
      currentCanary = { ...currentCanary, enabled: false };
      return route.fulfill({ json: currentCanary });
    }
    if (url.pathname === '/api/analytics/consensus-canary/events') {
      return route.fulfill({ json: [{
        id: 1, occurred_at: '2026-09-06T10:00:00Z', action: 'enable',
        previous_enabled: false, new_enabled: true, previous_tickers: [], new_tickers: ['AAA'],
        actor: 'local-network', note: 'controlled start', promotion_status: 'READY_FOR_MANUAL_PROMOTION',
      }] });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('public analytics shows effective weighted canary without operator controls', async ({ page }) => {
  await routeCommon(page);
  await page.goto('/analytics/?ticker=AAA');

  const active = page.locator('[data-canary-active]');
  await expect(active).toBeVisible();
  await expect(page.locator('[data-canary-active-mode]')).toHaveText('WEIGHTED CANARY');
  await expect(active).toContainText('112 ₽');
  await expect(active).toContainText('Median baseline');
  await expect(active).toContainText('STABLE');

  const controls = page.locator('[data-canary-controls]');
  await expect(controls).toContainText('ENABLED · AAA');
  await expect(controls).toContainText('только из local scope');
  await expect(controls.locator('[data-canary-enable]')).toHaveCount(0);
});

test('active consensus clearly shows median fallback when forward drift is WATCH', async ({ page }) => {
  await routeCommon(page, {
    active: {
      ...activeWeighted,
      effective_mode: 'median',
      safety_status: 'watch',
      fallback_reason: 'drift_watch',
      active_target_price: 110,
      active_expected_return_percent: 10,
    },
  });
  await page.goto('/analytics/?ticker=AAA');

  await expect(page.locator('[data-canary-active-mode]')).toHaveText('MEDIAN FALLBACK');
  const active = page.locator('[data-canary-active]');
  await expect(active).toContainText('Fallback:');
  await expect(active).toContainText('forward drift = WATCH');
  await expect(active).toContainText('110 ₽');
});

test('local operator can enable canary and execute immediate rollback', async ({ page }) => {
  const puts = [];
  let rollbacks = 0;
  await routeCommon(page, {
    isAdmin: true,
    canary: {
      enabled: false, tickers: ['AAA'], max_tickers: 5,
      safety_policy: 'weighted requires history and STABLE drift; otherwise median fallback',
      updated_at: null,
    },
    onPut: (payload) => puts.push(payload),
    onRollback: () => { rollbacks += 1; },
  });
  await page.goto('/analytics/');

  const controls = page.locator('[data-canary-controls]');
  await expect(controls).toBeVisible();
  await expect(controls.locator('[data-canary-enable]')).toBeVisible();
  await controls.locator('[data-canary-note]').fill('manual gate passed');
  await controls.locator('[data-canary-enable]').click();

  await expect.poll(() => puts.length).toBe(1);
  expect(puts[0]).toEqual({ enabled: true, tickers: ['AAA'], note: 'manual gate passed' });
  await expect(controls).toContainText('ENABLED · AAA');
  await expect(page.locator('[data-production-impact-ticker="AAA"]')).toHaveAttribute('data-canary-ticker', 'true');

  await controls.locator('[data-canary-rollback]').click();
  await expect.poll(() => rollbacks).toBe(1);
  await expect(controls).toContainText('DISABLED · production median');
});
