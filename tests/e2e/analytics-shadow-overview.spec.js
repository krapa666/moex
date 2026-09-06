const { test, expect } = require('@playwright/test');

const overview = {
  generated_at: '2026-09-06T08:00:00Z',
  history_days: 30,
  universe_tickers: 4,
  tickers_with_history: 3,
  classified_tickers: 3,
  alert_tickers: 1,
  watch_tickers: 1,
  stable_tickers: 1,
  insufficient_tickers: 1,
  actionable_tickers: 2,
  history_coverage_percent: 75,
  classified_coverage_percent: 75,
  items: [
    {
      ticker: 'DDD', target_year: 2027, latest_training_snapshot: 'pre_year', status: 'alert',
      reasons: ['large_baseline_divergence'], snapshots: 6, history_days: 30,
      history_span_hours: 72, first_captured_at: '2026-09-03T08:00:00Z', last_captured_at: '2026-09-06T08:00:00Z',
      latest_delta_percent: 25, previous_delta_percent: 24, delta_step_percentage_points: 1,
      median_abs_delta_percent: 24, max_abs_delta_percent: 25,
      latest_weight_concentration_ratio: 1.2, max_weight_concentration_ratio: 1.2,
      median_target_change_percent: 2, weighted_target_change_percent: 3,
      relative_movement_gap_percentage_points: 1, training_snapshot_changed: false,
    },
    {
      ticker: 'BBB', target_year: 2027, latest_training_snapshot: 'pre_year', status: 'watch',
      reasons: ['weight_concentration'], snapshots: 5, history_days: 30,
      history_span_hours: 60, first_captured_at: '2026-09-03T20:00:00Z', last_captured_at: '2026-09-06T08:00:00Z',
      latest_delta_percent: 6, previous_delta_percent: 5.5, delta_step_percentage_points: 0.5,
      median_abs_delta_percent: 5.7, max_abs_delta_percent: 6,
      latest_weight_concentration_ratio: 1.55, max_weight_concentration_ratio: 1.55,
      median_target_change_percent: 1, weighted_target_change_percent: 2,
      relative_movement_gap_percentage_points: 1, training_snapshot_changed: false,
    },
    {
      ticker: 'AAA', target_year: 2027, latest_training_snapshot: 'pre_year', status: 'stable',
      reasons: [], snapshots: 5, history_days: 30,
      history_span_hours: 60, first_captured_at: '2026-09-03T20:00:00Z', last_captured_at: '2026-09-06T08:00:00Z',
      latest_delta_percent: 2, previous_delta_percent: 2, delta_step_percentage_points: 0,
      median_abs_delta_percent: 2, max_abs_delta_percent: 2,
      latest_weight_concentration_ratio: 1.1, max_weight_concentration_ratio: 1.1,
      median_target_change_percent: 1, weighted_target_change_percent: 1,
      relative_movement_gap_percentage_points: 0, training_snapshot_changed: false,
    },
    {
      ticker: 'CCC', target_year: null, latest_training_snapshot: null, status: 'insufficient',
      reasons: ['no_history'], snapshots: 0, history_days: 30,
      history_span_hours: 0, first_captured_at: null, last_captured_at: null,
      latest_delta_percent: null, previous_delta_percent: null, delta_step_percentage_points: null,
      median_abs_delta_percent: null, max_abs_delta_percent: null,
      latest_weight_concentration_ratio: null, max_weight_concentration_ratio: null,
      median_target_change_percent: null, weighted_target_change_percent: null,
      relative_movement_gap_percentage_points: null, training_snapshot_changed: false,
    },
  ],
};

const notificationStatus = {
  enabled: true,
  configured: true,
  smtp_configured: true,
  recipient_configured: true,
  cooldown_hours: 24,
  history_days: 30,
  pending_events: 0,
  failed_events: 0,
  last_event_at: '2026-09-06T08:00:00Z',
  last_sent_at: '2026-09-06T08:00:00Z',
};

const notificationEvents = [
  {
    id: 5,
    ticker: 'BBB',
    target_year: 2027,
    from_status: 'stable',
    to_status: 'watch',
    transition_kind: 'transition',
    observed_at: '2026-09-06T08:00:00Z',
    latest_delta_percent: 6,
    reasons: ['weight_concentration'],
    delivery_status: 'sent',
    delivery_reason: null,
    delivery_attempts: 1,
    last_attempt_at: '2026-09-06T08:00:00Z',
    notified_at: '2026-09-06T08:00:00Z',
  },
];

async function mockApi(page, { isAdmin = false, testCounter = null } = {}) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: isAdmin ? 'local-network' : 'guest', is_admin: isAdmin } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [
        { id: 1, table_number: 1, analyst_name: 'Арсагера', forecast_start_year: 2027 },
      ] });
    }
    if (url.pathname === '/api/analytics/shadow-consensus/overview') {
      return route.fulfill({ json: overview });
    }
    if (url.pathname === '/api/analytics/shadow-consensus/notifications/status') {
      return route.fulfill({ json: notificationStatus });
    }
    if (url.pathname === '/api/analytics/shadow-consensus/notifications/events') {
      return route.fulfill({ json: notificationEvents });
    }
    if (url.pathname === '/api/analytics/shadow-consensus/notifications/test') {
      if (testCounter) testCounter.count += 1;
      return route.fulfill({ json: { sent: true } });
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
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('analytics shows global shadow drift ordered by operational severity and public notification history', async ({ page }) => {
  await mockApi(page);
  await page.goto('/analytics/');

  const panel = page.locator('[data-shadow-overview]');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Shadow drift — весь universe');
  await expect(panel).toContainText('75,0%');
  await expect(page.locator('[data-shadow-overview-status]')).toContainText('Требуют внимания: 2');

  const rows = page.locator('[data-shadow-overview-row]');
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText('DDD');
  await expect(rows.nth(0)).toContainText('ALERT');
  await expect(rows.nth(1)).toContainText('BBB');
  await expect(rows.nth(1)).toContainText('WATCH');
  await expect(rows.nth(2)).toContainText('AAA');
  await expect(rows.nth(2)).toContainText('STABLE');
  await expect(rows.nth(3)).toContainText('CCC');
  await expect(rows.nth(3)).toContainText('НАКОПЛЕНИЕ');

  await expect(panel).toContainText('Уведомления о переходах drift');
  await expect(page.locator('[data-shadow-notification-status]')).toContainText('Включены');
  await expect(page.locator('[data-shadow-notification-event="5"]')).toContainText('BBB');
  await expect(page.locator('[data-shadow-notification-event="5"]')).toContainText('STABLE → WATCH');
  await expect(page.locator('[data-shadow-notification-event="5"]')).toContainText('отправлено');
  await expect(page.locator('[data-shadow-notification-test]')).toBeHidden();
  await expect(panel).not.toContainText('Арсагера');

  await panel.locator('[data-shadow-overview-filter]').selectOption('actionable');
  await expect(page.locator('[data-shadow-overview-row]')).toHaveCount(2);
  await expect(page.locator('[data-shadow-overview-row]').nth(0)).toContainText('DDD');
  await expect(page.locator('[data-shadow-overview-row]').nth(1)).toContainText('BBB');
});

test('local analytics can send a shadow notification test email', async ({ page }) => {
  const testCounter = { count: 0 };
  await mockApi(page, { isAdmin: true, testCounter });
  await page.goto('/analytics/');

  const button = page.locator('[data-shadow-notification-test]');
  await expect(button).toBeVisible();
  await button.click();

  await expect(page.locator('[data-shadow-notification-test-status]')).toContainText('Тестовое письмо отправлено');
  expect(testCounter.count).toBe(1);
});
