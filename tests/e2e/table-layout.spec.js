const { test, expect } = require('@playwright/test');

const tables = [
  {
    id: 1,
    table_number: 1,
    analyst_name: 'Тестовый аналитик',
    forecast_start_year: 2026,
  },
];

const rows = [
  {
    id: 101,
    table_id: 1,
    ticker: 'SBER',
    current_price: 320.45,
    shares_billion: 21.586,
    market_cap_billion_rub: 6916.46,
    pe_avg_5y: 6.2,
    net_profit_year_map: { 2026: 1800, 2027: 2100 },
    dividend_year_map: { 2026: 35, 2027: 42 },
    forecast_price_year1: 516.99,
    forecast_price_year2: 603.15,
    upside_percent_year1: 72.26,
    upside_percent_year2: 112.25,
    price_updated_at: '2026-08-09T02:30:00Z',
    net_profit_source_comment: 'Тестовая строка с достаточно длинным комментарием',
    status_message: null,
    shared_fields_editable: true,
  },
  {
    id: 102,
    table_id: 1,
    ticker: 'LKOH',
    current_price: 6000,
    shares_billion: 0.6929,
    market_cap_billion_rub: 4157.4,
    pe_avg_5y: 5.8,
    net_profit_year_map: { 2026: 850, 2027: 900 },
    dividend_year_map: { 2026: 900, 2027: 300 },
    forecast_price_year1: 7115.02,
    forecast_price_year2: 7533.55,
    upside_percent_year1: 33.58,
    upside_percent_year2: 45.56,
    price_updated_at: '2026-08-09T02:30:00Z',
    net_profit_source_comment: null,
    status_message: null,
    shared_fields_editable: true,
  },
];

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === 'GET' && url.pathname === '/api/auth/me') {
      await route.fulfill({ json: { username: 'test-admin', is_admin: true } });
      return;
    }
    if (request.method() === 'GET' && url.pathname === '/api/tables') {
      await route.fulfill({ json: tables });
      return;
    }
    if (request.method() === 'GET' && url.pathname === '/api/rows') {
      await route.fulfill({ json: rows });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: 'Unexpected test request' } });
  });
}

async function openTable(page) {
  await mockApi(page);
  await page.goto('/');
  await expect(page.locator('#rows-table-body > tr')).toHaveCount(2);
}

test('renders the two-year forecast as a 17-column row with dividend yields', async ({ page }) => {
  await openTable(page);

  await expect(page.locator('#header-year1-group')).toHaveText('2026');
  await expect(page.locator('#header-year2-group')).toHaveText('2027');
  await expect(page.locator('#header-dividends-year1')).toHaveText('Дивиденды, ₽/акц.');
  await expect(page.locator('#header-dividends-year2')).toHaveText('Дивиденды, ₽/акц.');
  await expect(page.locator('#rows-table-body > tr').first().locator('td')).toHaveCount(17);
  await expect(page.locator('[data-cell="dividend_yield_year1"]').first()).toHaveText('10,9 %');
  await expect(page.locator('[data-cell="dividend_yield_year2"]').first()).toHaveText('13,1 %');
  await expect(page.locator('[data-cell="upside_year1"]').first()).toHaveText('72 %');
  await expect(page.locator('[data-cell="upside_year2"]').first()).toHaveText('112 %');

  await page.locator('input[data-field="dividends_year1"]').first().fill('64.09');
  await expect(page.locator('[data-cell="dividend_yield_year1"]').first()).toHaveText('20,0 %');
});

test('sorts rows by dividend yield for each forecast year', async ({ page }) => {
  await openTable(page);

  const tickers = () => page.locator('#rows-table-body input[data-field="ticker"]').evaluateAll(
    (inputs) => inputs.map((input) => input.value),
  );

  await page.locator('#sort-dividend-yield-year1').click();
  await page.locator('#sort-dividend-yield-year1').click();
  await expect.poll(tickers).toEqual(['LKOH', 'SBER']);

  await page.locator('#sort-dividend-yield-year2').click();
  await page.locator('#sort-dividend-yield-year2').click();
  await expect.poll(tickers).toEqual(['SBER', 'LKOH']);
});

for (const viewport of [
  { width: 1024, height: 768 },
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
]) {
  test(`fits without horizontal table scrolling at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openTable(page);

    const layout = await page.locator('.table-wrap').evaluate((wrapper) => {
      const table = wrapper.querySelector('table');
      const card = wrapper.closest('.card');
      return {
        wrapperClientWidth: wrapper.clientWidth,
        wrapperScrollWidth: wrapper.scrollWidth,
        tableWidth: table.getBoundingClientRect().width,
        cardWidth: card.getBoundingClientRect().width,
        cardLeft: card.getBoundingClientRect().left,
        cardRight: card.getBoundingClientRect().right,
      };
    });

    expect(layout.wrapperScrollWidth).toBeLessThanOrEqual(layout.wrapperClientWidth + 1);
    expect(layout.tableWidth).toBeLessThanOrEqual(layout.wrapperClientWidth + 1);
    expect(layout.cardWidth).toBeLessThanOrEqual(1255);

    if (viewport.width >= 1366) {
      expect(Math.abs(layout.cardLeft - (viewport.width - layout.cardRight))).toBeLessThanOrEqual(2);
    }
  });
}

test('centers column labels while keeping numeric inputs right-aligned', async ({ page }) => {
  await openTable(page);

  const headerAlignments = await page.locator('thead th').evaluateAll((headers) =>
    [...new Set(headers.map((header) => getComputedStyle(header).textAlign))],
  );
  expect(headerAlignments).toEqual(['center']);

  await expect(page.locator('input[data-field="shares_billion"]').first()).toHaveCSS('text-align', 'right');
  await expect(page.locator('input[data-field="forecast_profit_year1_billion_rub"]').first()).toHaveCSS('text-align', 'right');
});
