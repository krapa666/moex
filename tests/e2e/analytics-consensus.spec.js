const { test, expect } = require('@playwright/test');

const tables = [
  { id: 1, table_number: 1, analyst_name: 'Основной', forecast_start_year: 2026 },
  { id: 2, table_number: 2, analyst_name: 'Консервативный', forecast_start_year: 2026 },
  { id: 3, table_number: 3, analyst_name: 'Дальний горизонт', forecast_start_year: 2027 },
];

const comparison = [
  {
    table_id: 1,
    table_number: 1,
    analyst_name: 'Основной',
    forecast_start_year: 2026,
    ticker: 'SBER',
    current_price: 300,
    years: [
      { year: 2026, forecast_price: 350, forecast_profit_billion_rub: 1400, dividends_per_share: 20, upside_percent: 23.3 },
      { year: 2027, forecast_price: 390, forecast_profit_billion_rub: 1500, dividends_per_share: 22, upside_percent: 38 },
    ],
  },
  {
    table_id: 2,
    table_number: 2,
    analyst_name: 'Консервативный',
    forecast_start_year: 2026,
    ticker: 'SBER',
    current_price: 300,
    years: [
      { year: 2026, forecast_price: 250, forecast_profit_billion_rub: 1100, dividends_per_share: 18, upside_percent: -10.7 },
      { year: 2027, forecast_price: 280, forecast_profit_billion_rub: 1200, dividends_per_share: 20, upside_percent: 0 },
    ],
  },
  {
    table_id: 3,
    table_number: 3,
    analyst_name: 'Дальний горизонт',
    forecast_start_year: 2027,
    ticker: 'SBER',
    current_price: 300,
    years: [
      { year: 2027, forecast_price: 500, forecast_profit_billion_rub: 1700, dividends_per_share: 25, upside_percent: 75 },
      { year: 2028, forecast_price: 540, forecast_profit_billion_rub: 1800, dividends_per_share: 27, upside_percent: 91 },
    ],
  },
];

const singleTargetComparison = [
  {
    table_id: 1,
    table_number: 1,
    analyst_name: 'Основной',
    forecast_start_year: 2026,
    ticker: 'LKOH',
    current_price: 6100,
    years: [
      { year: 2026, forecast_price: 7000, forecast_profit_billion_rub: 900, dividends_per_share: 550, upside_percent: 23.8 },
    ],
  },
];

async function mockAnalyticsApi(page, { isAdmin = true } = {}) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: isAdmin ? 'local-network' : 'guest', is_admin: isAdmin } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({ json: tables });
    }
    if (url.pathname === '/api/ticker-comparison') {
      const ticker = url.searchParams.get('ticker');
      if (ticker === 'SBER') return route.fulfill({ json: comparison });
      if (ticker === 'LKOH') return route.fulfill({ json: singleTargetComparison });
      return route.fulfill({ json: [] });
    }
    if (url.pathname === '/api/analytics/forecast-revisions') {
      return route.fulfill({ json: [] });
    }
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('shows same-year analyst targets with range and agreement metrics', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');

  const panel = page.locator('[data-analytics-consensus]');
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-analytics-consensus-status]')).toHaveText('2026 · целей: 2/3');
  await expect(panel.locator('[data-consensus-kpi="min"]')).toHaveText('250 ₽');
  await expect(panel.locator('[data-consensus-kpi="median"]')).toHaveText('300 ₽');
  await expect(panel.locator('[data-consensus-kpi="max"]')).toHaveText('350 ₽');
  await expect(panel.locator('[data-consensus-kpi="market"]')).toHaveText('300 ₽');
  await expect(panel.locator('[data-consensus-kpi="spread"]')).toHaveText('33,3 %');
  await expect(panel.locator('[data-consensus-kpi="agreement"]')).toHaveText('Низкая');
  await expect(panel.locator('[data-consensus-kpi="agreement"]')).toHaveClass(/low/);
  await expect(panel.locator('.analytics-consensus-formula')).toContainText('(максимум − минимум) / медиана');

  await expect(panel.locator('[data-consensus-target]')).toHaveCount(2);
  await expect(panel.locator('[data-consensus-target="1"]')).toContainText('Основной');
  await expect(panel.locator('[data-consensus-target="1"]')).toContainText('350 ₽');
  await expect(panel.locator('[data-consensus-target="2"]')).toContainText('Консервативный');
  await expect(panel.locator('[data-consensus-target="3"]')).toHaveCount(0);
  await expect(panel.locator('.analytics-consensus-marker')).toHaveCount(2);
  await expect(panel.locator('.analytics-consensus-range')).toHaveAttribute(
    'aria-label',
    'Диапазон целей SBER на 2026: минимум 250 ₽, медиана 300 ₽, максимум 350 ₽',
  );
});

test('masks real analyst names for a guest in selector and consensus', async ({ page }) => {
  await mockAnalyticsApi(page, { isAdmin: false });
  await page.goto('/analytics/?ticker=SBER');

  const select = page.locator('#analytics-table');
  await expect(select.locator('option[value="1"]')).toHaveText('Аналитик 1 · таблица 1');
  await expect(select.locator('option[value="2"]')).toHaveText('Аналитик 2 · таблица 2');
  await expect(select.locator('option[value="3"]')).toHaveText('Аналитик 3 · таблица 3');

  const panel = page.locator('[data-analytics-consensus]');
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-consensus-target="1"]')).toContainText('Аналитик 1');
  await expect(panel.locator('[data-consensus-target="2"]')).toContainText('Аналитик 2');
  await expect(panel).not.toContainText('Основной');
  await expect(panel).not.toContainText('Консервативный');
  await expect(page.locator('body')).not.toContainText('Дальний горизонт');
});

test('does not infer analyst agreement from a single comparable target', async ({ page }) => {
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=LKOH');

  const panel = page.locator('[data-analytics-consensus]');
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-analytics-consensus-status]')).toHaveText('2026 · целей: 1/1');
  await expect(panel.locator('[data-consensus-kpi="spread"]')).toHaveText('—');
  await expect(panel.locator('[data-consensus-kpi="agreement"]')).toHaveText('Недостаточно данных');
  await expect(panel.locator('[data-consensus-kpi="agreement"]')).toHaveClass(/insufficient/);
  await expect(panel.locator('.analytics-consensus-formula')).toContainText('минимум две сопоставимые цели');
});

test('consensus panel stays inside the mobile page viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockAnalyticsApi(page);
  await page.goto('/analytics/?ticker=SBER');

  await expect(page.locator('[data-analytics-consensus]')).toBeVisible();
  await expect(page.locator('[data-consensus-target]')).toHaveCount(2);
  await expect(page.locator('[data-consensus-kpi="spread"]')).toHaveText('33,3 %');

  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
});
