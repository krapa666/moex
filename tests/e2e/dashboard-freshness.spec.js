const { test, expect } = require('@playwright/test');

async function mockFreshnessApi(page, { quoteAgesHours, volumeAgeHours }) {
  const now = Date.now();
  const timestamp = (hours) => new Date(now - hours * 60 * 60 * 1000).toISOString();

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/tables') {
      return route.fulfill({
        json: [{ id: 7, table_number: 1, analyst_name: 'Основной' }],
      });
    }

    if (url.pathname === '/api/rows' && url.searchParams.get('table_id') === '7') {
      return route.fulfill({
        json: quoteAgesHours.map((age, index) => ({
          ticker: index === 0 ? 'SBER' : 'LKOH',
          current_price: index === 0 ? 320.45 : 6000,
          forecast_price_year1: index === 0 ? 384.54 : 8400,
          upside_percent_year1: index === 0 ? 20 : 40,
          price_updated_at: age == null ? null : timestamp(age),
        })),
      });
    }

    if (url.pathname === '/api/volume/overview') {
      return route.fulfill({
        json: [
          {
            ticker: 'SBER',
            short_name: 'Сбербанк',
            latest: { trade_date: '2026-09-05', ratio: 4.4, signal_status: 'signal' },
          },
        ],
      });
    }

    if (url.pathname === '/api/volume/runs/latest') {
      return route.fulfill({
        json: volumeAgeHours == null
          ? null
          : {
              status: 'success',
              started_at: timestamp(volumeAgeHours + 0.1),
              finished_at: timestamp(volumeAgeHours),
            },
      });
    }

    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('marks fresh quotes and a stale volume run independently', async ({ page }) => {
  await mockFreshnessApi(page, {
    quoteAgesHours: [2, 20],
    volumeAgeHours: 120,
  });
  await page.goto('/dashboard/');

  const quotes = page.locator('[data-dashboard-freshness="quotes"]');
  const volumes = page.locator('[data-dashboard-freshness="volumes"]');

  await expect(quotes).toHaveAttribute('data-state', 'fresh');
  await expect(quotes.locator('[data-freshness-status]')).toHaveText('Актуально');
  await expect(quotes.locator('[data-freshness-detail]')).toContainText('Старейшая:');

  await expect(volumes).toHaveAttribute('data-state', 'stale');
  await expect(volumes.locator('[data-freshness-status]')).toHaveText('Устарело');
  await expect(volumes.locator('[data-freshness-detail]')).toContainText('Последний сбор:');
});

test('treats missing quote timestamps and medium-age volume data as delayed', async ({ page }) => {
  await mockFreshnessApi(page, {
    quoteAgesHours: [4, null],
    volumeAgeHours: 60,
  });
  await page.goto('/dashboard/');

  const quotes = page.locator('[data-dashboard-freshness="quotes"]');
  const volumes = page.locator('[data-dashboard-freshness="volumes"]');

  await expect(quotes).toHaveAttribute('data-state', 'delayed');
  await expect(quotes.locator('[data-freshness-status]')).toHaveText('Задержка');
  await expect(quotes.locator('[data-freshness-detail]')).toContainText('без времени: 1');

  await expect(volumes).toHaveAttribute('data-state', 'delayed');
  await expect(volumes.locator('[data-freshness-status]')).toHaveText('Задержка');
});
