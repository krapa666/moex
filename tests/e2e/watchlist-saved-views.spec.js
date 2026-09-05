const { test, expect } = require('@playwright/test');

async function mockWatchlistApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/tables') {
      return route.fulfill({
        json: [{ id: 7, table_number: 1, analyst_name: 'Основной', forecast_start_year: 2026 }],
      });
    }

    if (url.pathname === '/api/rows' && url.searchParams.get('table_id') === '7') {
      return route.fulfill({
        json: [
          {
            ticker: 'SBER',
            current_price: 320.45,
            forecast_price_year1: 384.54,
            upside_percent_year1: 20,
            dividend_year_map: { 2026: 35 },
          },
          {
            ticker: 'LKOH',
            current_price: 6000,
            forecast_price_year1: 8400,
            upside_percent_year1: 40,
            dividend_year_map: { 2026: 900 },
          },
          {
            ticker: 'GAZP',
            current_price: 124.8,
            forecast_price_year1: null,
            upside_percent_year1: -5,
            dividend_year_map: { 2026: null },
          },
        ],
      });
    }

    if (url.pathname === '/api/volume/overview') {
      return route.fulfill({
        json: [
          { ticker: 'SBER', latest: { ratio: 4.4, signal_status: 'signal' } },
          { ticker: 'GAZP', latest: { ratio: 7.1, signal_status: 'above_range' } },
        ],
      });
    }

    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('creates, applies, restores, and deletes named Watchlist views', async ({ page }) => {
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');

  const visibleTickers = () => page.locator('#watchlist-body > tr:visible').evaluateAll(
    (rows) => rows.map((row) => row.dataset.watchlistTicker),
  );

  const viewName = page.locator('#watchlist-view-name');
  const savedView = page.locator('#watchlist-saved-view');
  const upsideSort = page.locator('[data-watchlist-sort="upside"]');

  await page.locator('#watchlist-filter').selectOption('positive');
  await upsideSort.click();
  await viewName.fill('Рост');
  await page.locator('#watchlist-save-view').click();

  await expect(savedView).toHaveValue('Рост');
  await expect.poll(visibleTickers).toEqual(['LKOH', 'SBER']);
  await expect(upsideSort.locator('xpath=..')).toHaveAttribute('aria-sort', 'descending');

  await page.locator('#watchlist-reset-view').click();
  await page.locator('#watchlist-filter').selectOption('negative');
  await viewName.fill('Риск');
  await page.locator('#watchlist-save-view').click();

  await expect(savedView).toHaveValue('Риск');
  await expect.poll(visibleTickers).toEqual(['GAZP']);
  await expect(savedView.locator('option')).toHaveCount(3);

  await savedView.selectOption('Рост');
  await expect(page.locator('#watchlist-filter')).toHaveValue('positive');
  await expect.poll(visibleTickers).toEqual(['LKOH', 'SBER']);
  await expect(upsideSort.locator('xpath=..')).toHaveAttribute('aria-sort', 'descending');

  await page.reload();

  await expect(page.locator('#watchlist-filter')).toHaveValue('positive');
  await expect.poll(visibleTickers).toEqual(['LKOH', 'SBER']);
  await expect(page.locator('#watchlist-saved-view').locator('option')).toHaveCount(3);

  await page.locator('#watchlist-saved-view').selectOption('Риск');
  await expect(page.locator('#watchlist-filter')).toHaveValue('negative');
  await expect.poll(visibleTickers).toEqual(['GAZP']);
  await expect(page.locator('[aria-sort]')).toHaveCount(0);

  await page.locator('#watchlist-delete-view').click();

  await expect(page.locator('#watchlist-saved-view').locator('option')).toHaveCount(2);
  await expect(page.locator('#watchlist-saved-view').locator('option[value="Риск"]')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('moex.watchlist.saved_views.v1')))).toEqual([
    {
      name: 'Рост',
      search: '',
      filter: 'positive',
      sortField: 'upside',
      sortDirection: 'desc',
    },
  ]);
});
