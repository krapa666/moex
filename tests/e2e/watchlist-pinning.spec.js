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

test('pins securities locally, restores them after reload, and keeps pins when the view is reset', async ({ page }) => {
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');

  const visibleTickers = () => page.locator('#watchlist-body > tr:visible').evaluateAll(
    (rows) => rows.map((row) => row.dataset.watchlistTicker),
  );

  const sberPin = page.getByRole('button', { name: 'Закрепить SBER' });
  const gazpPin = page.getByRole('button', { name: 'Закрепить GAZP' });
  await sberPin.click();
  await gazpPin.click();

  await expect(page.locator('[data-watchlist-ticker="SBER"]')).toHaveAttribute('data-watchlist-pinned', 'true');
  await expect(page.locator('[data-watchlist-ticker="GAZP"]')).toHaveAttribute('data-watchlist-pinned', 'true');
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('moex.watchlist.pins.v1')))).toEqual(['GAZP', 'SBER']);

  await page.locator('#watchlist-filter').selectOption('pinned');
  await expect.poll(visibleTickers).toEqual(['SBER', 'GAZP']);
  await expect(page.locator('#watchlist-status')).toHaveText('Показано: 2 из 3 · объёмы: 2');

  await page.reload();

  await expect(page.locator('#watchlist-filter')).toHaveValue('pinned');
  await expect.poll(visibleTickers).toEqual(['SBER', 'GAZP']);
  await expect(page.getByRole('button', { name: 'Открепить SBER' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Открепить GAZP' })).toHaveAttribute('aria-pressed', 'true');

  await page.locator('#watchlist-reset-view').click();

  await expect(page.locator('#watchlist-filter')).toHaveValue('all');
  await expect.poll(visibleTickers).toEqual(['SBER', 'LKOH', 'GAZP']);
  await expect(page.getByRole('button', { name: 'Открепить SBER' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Открепить GAZP' })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('moex.watchlist.pins.v1')))).toEqual(['GAZP', 'SBER']);
});
