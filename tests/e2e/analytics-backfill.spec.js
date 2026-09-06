const { test, expect } = require('@playwright/test');

const previewResult = {
  applied: false,
  rows_total: 2,
  valid_rows: 2,
  create_rows: 1,
  unchanged_rows: 0,
  protected_rows: 1,
  invalid_rows: 0,
  created_rows: 0,
  items: [
    {
      row_number: 2,
      ticker: 'GAZP',
      fiscal_year: 2025,
      action: 'create',
      message: 'new canonical actual result',
    },
    {
      row_number: 3,
      ticker: 'SBER',
      fiscal_year: 2025,
      action: 'protected',
      message: 'existing manual result is protected; bulk import never overwrites canonical facts',
    },
  ],
};

async function mockApi(page) {
  let previewCalls = 0;
  let applyCalls = 0;

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'local-network', is_admin: true } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: [{ id: 1, table_number: 1, analyst_name: 'Арсагера' }] });
    }
    if (url.pathname === '/api/analytics/source-accuracy') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits') return route.fulfill({ json: [] });
    if (url.pathname === '/api/analytics/actual-net-profits/sync-status') {
      return route.fulfill({
        json: {
          source_key: 'moex-cci',
          source_name: 'MOEX CCI · МСФО',
          enabled: false,
          configured: false,
          interval_hours: 24,
          run_on_startup: false,
          years_back: 5,
        },
      });
    }
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
          actual_records: 0,
          actual_tickers: 0,
          by_year: [],
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
    if (url.pathname === '/api/analytics/actual-net-profits/backfill/preview') {
      previewCalls += 1;
      return route.fulfill({ json: previewResult });
    }
    if (url.pathname === '/api/analytics/actual-net-profits/backfill') {
      applyCalls += 1;
      return route.fulfill({
        json: { ...previewResult, applied: true, created_rows: 1 },
      });
    }
    if (url.pathname === '/api/analytics/forecast-revisions') return route.fulfill({ json: [] });
    if (url.pathname === '/api/ticker-comparison') return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });

  return {
    previewCalls: () => previewCalls,
    applyCalls: () => applyCalls,
  };
}

test('local admin previews protected rows before applying actual-result CSV backfill', async ({ page }) => {
  const state = await mockApi(page);
  await page.goto('/analytics/');

  const panel = page.locator('[data-actual-backfill]');
  await expect(panel).toBeVisible();
  await page.locator('[data-actual-backfill-form] input[type="file"]').setInputFiles({
    name: 'actuals.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'ticker;fiscal_year;net_profit_billion_rub;source_name;source_url;reported_at\n' +
      'GAZP;2025;1000;Issuer;https://example.test/gazp;2026-03-01\n' +
      'SBER;2025;1580;Issuer;https://example.test/sber;2026-02-27\n',
    ),
  });

  await page.locator('[data-actual-backfill-preview]').click();
  await expect.poll(state.previewCalls).toBe(1);
  await expect(page.locator('[data-actual-backfill-status]')).toContainText('к импорту 1');
  await expect(page.locator('[data-actual-backfill-summary]')).toContainText('защищено 1');

  const rows = page.locator('[data-actual-backfill-body] tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('GAZP');
  await expect(rows.first()).toContainText('CREATE');
  await expect(rows.nth(1)).toContainText('SBER');
  await expect(rows.nth(1)).toContainText('PROTECTED');
  await expect(page.locator('[data-actual-backfill-apply]')).toBeEnabled();

  await page.locator('[data-actual-backfill-apply]').click();
  await expect.poll(state.applyCalls).toBe(1);
});
