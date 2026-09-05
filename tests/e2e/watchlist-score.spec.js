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

const allTickers = (page) => page.locator('#watchlist-body > tr').evaluateAll(
  (rows) => rows.map((row) => row.dataset.watchlistTicker),
);

test('calculates a transparent 0-100 priority score from existing Watchlist factors', async ({ page }) => {
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');

  const sber = page.locator('[data-watchlist-ticker="SBER"]');
  const lkoh = page.locator('[data-watchlist-ticker="LKOH"]');
  const gazp = page.locator('[data-watchlist-ticker="GAZP"]');

  await expect(sber).toHaveAttribute('data-watchlist-score', '53');
  await expect(lkoh).toHaveAttribute('data-watchlist-score', '65');
  await expect(gazp).toHaveAttribute('data-watchlist-score', '');

  const sberScore = sber.locator('.watchlist-score');
  await expect(sberScore.locator('summary')).toHaveAccessibleName(/Приоритет SBER: 53 из 100/);
  await sberScore.locator('summary').click();
  await expect(sberScore).toHaveAttribute('open', '');
  await expect(sberScore.locator('.watchlist-score-breakdown')).toContainText('Цена · 20,0 %');
  await expect(sberScore.locator('.watchlist-score-breakdown')).toContainText('+20,0 / 60');
  await expect(sberScore.locator('.watchlist-score-breakdown')).toContainText('Дивиденды · 10,9 %');
  await expect(sberScore.locator('.watchlist-score-breakdown')).toContainText('+18,2 / 25');
  await expect(sberScore.locator('.watchlist-score-breakdown')).toContainText('Объём · Сигнал');
  await expect(sberScore.locator('.watchlist-score-breakdown')).toContainText('+15,0 / 15');

  await expect(gazp.locator('.watchlist-score')).toHaveCount(0);
  await expect(gazp.locator('.watchlist-score-cell')).toHaveText('—');
});

test('sorts by priority with missing scores last and restores the score sort after reload', async ({ page }) => {
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');

  const scoreSort = page.locator('[data-watchlist-sort="score"]');
  await scoreSort.click();

  await expect.poll(() => allTickers(page)).toEqual(['LKOH', 'SBER', 'GAZP']);
  await expect(scoreSort.locator('xpath=..')).toHaveAttribute('aria-sort', 'descending');
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('moex.watchlist.view.v1'))?.sortField)).toBe('score');

  await page.reload();

  await expect.poll(() => allTickers(page)).toEqual(['LKOH', 'SBER', 'GAZP']);
  await expect(page.locator('[data-watchlist-sort="score"]').locator('xpath=..')).toHaveAttribute('aria-sort', 'descending');

  await page.locator('[data-watchlist-sort="score"]').click();
  await expect.poll(() => allTickers(page)).toEqual(['SBER', 'LKOH', 'GAZP']);
  await expect(page.locator('[data-watchlist-sort="score"]').locator('xpath=..')).toHaveAttribute('aria-sort', 'ascending');
});

test('keeps the score explanation inside the mobile page viewport contract', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockWatchlistApi(page);
  await page.goto('/watchlist/');

  await page.locator('[data-watchlist-ticker="SBER"] .watchlist-score > summary').click();
  await expect(page.locator('[data-watchlist-ticker="SBER"] .watchlist-score-breakdown')).toBeVisible();

  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
});
