const { test, expect } = require('@playwright/test');

async function mockDashboardApi(page, observedWindows) {
  const now = new Date('2026-09-06T12:00:00Z');

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/dashboard/source-health') {
      const days = Number(url.searchParams.get('days') || 30);
      observedWindows.push(days);
      return route.fulfill({
        json: {
          generated_at: now.toISOString(),
          history_days: days,
          configured_sources: 3,
          sources_with_runs: 3,
          status: 'failed',
          healthy_sources: 1,
          degraded_sources: 1,
          stale_sources: 0,
          failed_sources: 1,
          latest_run_at: '2026-09-06T11:00:00Z',
          items: [
            {
              source_id: 'published-sheets:abc123',
              source_key: 'published-sheets',
              display_name: 'Published Sheets #1',
              analyst_name: 'Private Analyst Must Not Render',
              expected_interval_hours: 6,
              status: 'failed',
              reasons: ['latest_run_failed'],
              run_in_progress: false,
              latest_run_status: 'failed',
              last_run_at: '2026-09-06T11:00:00Z',
              last_completed_at: '2026-09-06T11:05:00Z',
              last_success_at: '2026-09-06T05:05:00Z',
              latest_age_hours: 0.9,
              coverage_percent: null,
              baseline_coverage_percent: 92,
              coverage_change_pp: null,
              coverage_baseline_runs: 5,
              tickers_total: 0,
              tickers_mapped: 0,
              tickers_updated: 0,
              tickers_unchanged: 0,
              tickers_skipped: 0,
              runs_in_window: 10,
              success_runs: 8,
              partial_runs: 1,
              failed_runs: 1,
              consecutive_successes: 0,
              consecutive_failures: 1,
              latest_error_kind: 'sync_exception',
              latest_error_count: 1,
            },
            {
              source_id: 'dohod',
              source_key: 'dohod',
              display_name: 'ДОХОДЪ',
              expected_interval_hours: 6,
              status: 'degraded',
              reasons: ['latest_run_partial', 'coverage_drop'],
              run_in_progress: false,
              latest_run_status: 'partial',
              last_run_at: '2026-09-06T10:00:00Z',
              last_completed_at: '2026-09-06T10:05:00Z',
              last_success_at: '2026-09-06T04:05:00Z',
              latest_age_hours: 1.9,
              coverage_percent: 68,
              baseline_coverage_percent: 91,
              coverage_change_pp: -23,
              coverage_baseline_runs: 6,
              tickers_total: 100,
              tickers_mapped: 68,
              tickers_updated: 5,
              tickers_unchanged: 63,
              tickers_skipped: 32,
              runs_in_window: 9,
              success_runs: 7,
              partial_runs: 2,
              failed_runs: 0,
              consecutive_successes: 0,
              consecutive_failures: 0,
              latest_error_kind: 'ticker_errors',
              latest_error_count: 32,
            },
            {
              source_id: 'arsagera',
              source_key: 'arsagera',
              display_name: 'Арсагера',
              expected_interval_hours: 6,
              status: 'healthy',
              reasons: [],
              run_in_progress: false,
              latest_run_status: 'success',
              last_run_at: '2026-09-06T09:00:00Z',
              last_completed_at: '2026-09-06T09:05:00Z',
              last_success_at: '2026-09-06T09:05:00Z',
              latest_age_hours: 2.9,
              coverage_percent: 96,
              baseline_coverage_percent: 95,
              coverage_change_pp: 1,
              coverage_baseline_runs: 8,
              tickers_total: 100,
              tickers_mapped: 96,
              tickers_updated: 4,
              tickers_unchanged: 92,
              tickers_skipped: 4,
              runs_in_window: 10,
              success_runs: 10,
              partial_runs: 0,
              failed_runs: 0,
              consecutive_successes: 10,
              consecutive_failures: 0,
              latest_error_kind: null,
              latest_error_count: 0,
            },
          ],
        },
      });
    }

    if (url.pathname === '/api/tables') return route.fulfill({ json: [] });
    if (url.pathname === '/api/volume/overview') return route.fulfill({ json: [] });
    if (url.pathname === '/api/volume/runs/latest') return route.fulfill({ json: null });

    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('renders source health worst-first without exposing private analyst names', async ({ page }) => {
  const observedWindows = [];
  await mockDashboardApi(page, observedWindows);
  await page.goto('/dashboard/');

  const panel = page.locator('#source-health-panel');
  await expect(panel.locator('[data-source-health-overall]')).toHaveText('FAILED');
  await expect(panel.locator('[data-source-health-count="configured"]')).toHaveText('3');
  await expect(panel.locator('[data-source-health-count="healthy"]')).toHaveText('1');
  await expect(panel.locator('[data-source-health-count="degraded"]')).toHaveText('1');
  await expect(panel.locator('[data-source-health-count="failed"]')).toHaveText('1');

  const rows = panel.locator('[data-source-health-source]');
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText('Published Sheets #1');
  await expect(rows.nth(0)).toContainText('FAILED');
  await expect(rows.nth(1)).toContainText('ДОХОДЪ');
  await expect(rows.nth(1)).toContainText('-23,0 п.п.');
  await expect(rows.nth(2)).toContainText('Арсагера');
  await expect(panel).not.toContainText('Private Analyst Must Not Render');
});

test('reloads source health for the selected history window', async ({ page }) => {
  const observedWindows = [];
  await mockDashboardApi(page, observedWindows);
  await page.goto('/dashboard/');

  await expect.poll(() => observedWindows.includes(30)).toBe(true);
  await page.locator('[data-source-health-window]').selectOption('90');
  await expect.poll(() => observedWindows.includes(90)).toBe(true);
});
