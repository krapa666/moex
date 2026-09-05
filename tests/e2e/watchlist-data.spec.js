const { test, expect } = require('@playwright/test');

async function mockWatchlistApi(page, { volumeAvailable = true } = {}) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/tables') {
      return route.fulfill({
        json: [
          { id: 9, table_number: 2, analyst_name: 'Другой', forecast_start_year: 2026 },
          { id: 7, table_number: 1, analyst_name: 'Основной', forecast_start_year: 2026 },
        ],
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
      if (!volumeAvailable) {
        return route.fulfill({ status: 503, json: { detail: 'volume unavailable' } });
      }
      return route.fulfill({
        json: [
          {
            ticker: 'SBER',
            latest: { ratio: 4.4, signal_status: 'signal' },
          },
          {
            ticker: 'GAZP',
            latest: { ratio: 7.1, signal_status: 'above_range' },
          },
          {
            ticker: 'ROSN',
            latest: { ratio: 1.2, signal_status: 'normal' },
          },
        ],
      });
    }

    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('merges the primary valuation table with volume monitoring by ticker', async ({ page }) => {
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');

  const rows = page.locator('#watchlist-body > tr');
  await expect(rows).toHaveCount(3);
  await expect(page.locator('[data-watchlist-empty]')).toBeHidden();
  await expect(page.locator('[data-watchlist-table]')).toBeVisible();
  await expect(page.locator('#watchlist-status')).toHaveText('Бумаги: 3 · объёмы: 2');
  await expect(page.locator('#watchlist-status')).toHaveAttribute('data-state', 'partial');
  await expect(page.locator('#watchlist-search')).toBeEnabled();
  await expect(page.locator('#watchlist-filter')).toBeEnabled();

  const sber = page.locator('[data-watchlist-ticker="SBER"]');
  await expect(sber).toContainText('320,45');
  await expect(sber).toContainText('384,54');
  await expect(sber).toContainText('20,0 %');
  await expect(sber).toContainText('10,9 %');
  await expect(sber).toContainText('4,4×');
  await expect(sber).toContainText('Сигнал');
  await expect(sber.getByRole('link', { name: 'SBER' })).toHaveAttribute('href', '/?ticker=SBER');
  await expect(sber.locator('.watchlist-volume-link')).toHaveAttribute('href', '/volumes/?ticker=SBER');

  const lkoh = page.locator('[data-watchlist-ticker="LKOH"]');
  await expect(lkoh).toContainText('40,0 %');
  await expect(lkoh).toContainText('15,0 %');
  await expect(lkoh).toContainText('Нет данных');

  const gazp = page.locator('[data-watchlist-ticker="GAZP"]');
  await expect(gazp).toContainText('-5,0 %');
  await expect(gazp).toContainText('7,1×');
  await expect(gazp).toContainText('Выше диапазона');
});

test('filters Watchlist locally by ticker, signal, and upside sign', async ({ page }) => {
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');
  await expect(page.locator('#watchlist-body > tr')).toHaveCount(3);

  const visibleTickers = () => page.locator('#watchlist-body > tr:visible').evaluateAll(
    (rows) => rows.map((row) => row.dataset.watchlistTicker),
  );

  await page.locator('#watchlist-search').fill('sbe');
  await expect.poll(visibleTickers).toEqual(['SBER']);
  await expect(page.locator('#watchlist-status')).toHaveText('Показано: 1 из 3 · объёмы: 2');

  await page.locator('#watchlist-search').fill('');
  await page.locator('#watchlist-filter').selectOption('signals');
  await expect.poll(visibleTickers).toEqual(['SBER', 'GAZP']);
  await expect(page.locator('#watchlist-status')).toHaveText('Показано: 2 из 3 · объёмы: 2');

  await page.locator('#watchlist-filter').selectOption('positive');
  await expect.poll(visibleTickers).toEqual(['SBER', 'LKOH']);

  await page.locator('#watchlist-filter').selectOption('negative');
  await expect.poll(visibleTickers).toEqual(['GAZP']);

  await page.locator('#watchlist-search').fill('SBER');
  await expect.poll(visibleTickers).toEqual([]);
  await expect(page.locator('[data-watchlist-filter-empty]')).toBeVisible();
  await expect(page.locator('#watchlist-status')).toHaveText('Показано: 0 из 3 · объёмы: 2');

  await page.locator('#watchlist-search').fill('');
  await page.locator('#watchlist-filter').selectOption('all');
  await expect.poll(visibleTickers).toEqual(['SBER', 'LKOH', 'GAZP']);
  await expect(page.locator('[data-watchlist-filter-empty]')).toBeHidden();
  await expect(page.locator('#watchlist-status')).toHaveText('Бумаги: 3 · объёмы: 2');
});

test('keeps valuation rows usable when the volume API is unavailable', async ({ page }) => {
  await mockWatchlistApi(page, { volumeAvailable: false });
  await page.goto('/watchlist/');

  await expect(page.locator('#watchlist-body > tr')).toHaveCount(3);
  await expect(page.locator('[data-watchlist-table]')).toBeVisible();
  await expect(page.locator('#watchlist-status')).toHaveText('Бумаги: 3 · объёмы недоступны');
  await expect(page.locator('#watchlist-status')).toHaveAttribute('data-state', 'partial');
  await expect(page.locator('[data-watchlist-ticker="SBER"]')).toContainText('384,54');
});
