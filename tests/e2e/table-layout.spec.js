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
    if (request.method() === 'PUT' && /^\/api\/rows\/\d+$/.test(url.pathname)) {
      const id = Number(url.pathname.split('/').at(-1));
      const original = rows.find((row) => row.id === id);
      const body = request.postDataJSON();
      await route.fulfill({
        json: {
          ...original,
          ...body,
          net_profit_year_map: body.net_profit_year_map || original.net_profit_year_map,
          dividend_year_map: body.dividend_year_map || original.dividend_year_map,
        },
      });
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

test('renders a compact forecast while preserving the full 17-cell data model', async ({ page }) => {
  await openTable(page);

  await expect(page.locator('#header-year1-group')).toHaveText('2026');
  await expect(page.locator('#header-year2-group')).toHaveText('2027');
  await expect(page.locator('#header-dividends-year1')).toBeHidden();
  await expect(page.locator('#header-dividends-year2')).toBeHidden();

  const firstRow = page.locator('#rows-table-body > tr').first();
  await expect(firstRow.locator('td')).toHaveCount(17);
  await expect(firstRow.locator('td:visible')).toHaveCount(13);
  await expect(page.locator('[data-cell="dividend_yield_year1"]').first()).toHaveText('10,9 %');
  await expect(page.locator('[data-cell="dividend_yield_year2"]').first()).toHaveText('13,1 %');
  await expect(page.locator('[data-cell="upside_year1"]').first()).toHaveText('72 %');
  await expect(page.locator('[data-cell="upside_year2"]').first()).toHaveText('112 %');
});

test('opens stock details and edits secondary fields from the drawer', async ({ page }) => {
  await openTable(page);

  const firstRow = page.locator('#rows-table-body > tr').first();
  const detailsButton = firstRow.getByRole('button', { name: 'Подробнее' });
  await expect(detailsButton).toBeVisible();
  await detailsButton.click();
  expect(new URL(page.url()).searchParams.get('ticker')).toBe('SBER');

  const drawer = page.locator('#security-detail-overlay');
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-detail="ticker"]')).toHaveText('SBER');
  await expect(drawer.locator('[data-detail="current_price"]')).toHaveText('320,45 ₽');
  await expect(drawer.locator('[data-detail="shares"]')).toHaveValue('21.586');
  await expect(drawer.locator('[data-detail="year1"]')).toHaveText('2026');
  await expect(drawer.locator('[data-detail="price1"]')).toHaveText('516,99 ₽');
  await expect(drawer.locator('[data-detail="dividends1"]')).toHaveValue('35');
  await expect(drawer.locator('[data-detail="source"]')).toContainText('Тестовая строка');

  await drawer.locator('[data-detail="dividends1"]').fill('64.09');
  await expect(drawer.locator('[data-detail="dividends1"]')).toHaveValue('64.09');
  await expect(drawer.locator('[data-detail="dividend_yield1"]')).toHaveText('20,0 %');
  await expect(firstRow.locator('[data-cell="dividend_yield_year1"]')).toHaveText('20,0 %');

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  expect(new URL(page.url()).searchParams.get('ticker')).toBeNull();
});

test('opens the requested stock drawer from a ticker deep link after rows load', async ({ page }) => {
  await mockApi(page);
  await page.goto('/?ticker=LKOH');
  await expect(page.locator('#rows-table-body > tr')).toHaveCount(2);

  const drawer = page.locator('#security-detail-overlay');
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-detail="ticker"]')).toHaveText('LKOH');
  await expect(drawer.locator('[data-detail="current_price"]')).toHaveText('6 000 ₽');

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL('/');
});

test('cleans a missing forecast ticker deep link after rows finish loading', async ({ page }) => {
  await mockApi(page);
  await page.goto('/?ticker=UNKNOWN');
  await expect(page.locator('#rows-table-body > tr')).toHaveCount(2);

  await expect(page.locator('#security-detail-overlay')).toBeHidden();
  await expect(page).toHaveURL('/');
  await expect(page.locator('#global-status')).toHaveText('Тикер UNKNOWN не найден в текущей таблице');
});

test('uses browser back and forward for forecast details opened inside the app', async ({ page }) => {
  await openTable(page);
  const drawer = page.locator('#security-detail-overlay');

  await page.locator('#rows-table-body > tr').first().getByRole('button', { name: 'Подробнее' }).click();
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-detail="ticker"]')).toHaveText('SBER');
  await expect(page).toHaveURL('/?ticker=SBER');

  await page.goBack();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL('/');

  await page.goForward();
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-detail="ticker"]')).toHaveText('SBER');
  await expect(page).toHaveURL('/?ticker=SBER');
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

test('centers visible column labels while keeping numeric inputs right-aligned', async ({ page }) => {
  await openTable(page);

  const headerAlignments = await page.locator('thead th:visible').evaluateAll((headers) =>
    [...new Set(headers.map((header) => getComputedStyle(header).textAlign))],
  );
  expect(headerAlignments).toEqual(['center']);

  await expect(page.locator('input[data-field="forecast_profit_year1_billion_rub"]').first()).toHaveCSS('text-align', 'right');
  await page.locator('#rows-table-body > tr').first().getByRole('button', { name: 'Подробнее' }).click();
  await expect(page.locator('[data-detail="shares"]')).toHaveCSS('text-align', 'right');
});

test('toggles dark theme and keeps the choice after reload', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await mockApi(page);
  await page.goto('/');
  await page.evaluate(() => localStorage.removeItem('moex-theme'));
  await page.reload();
  await expect(page.locator('#rows-table-body > tr')).toHaveCount(2);

  const root = page.locator('html');
  const toggle = page.locator('[data-theme-toggle]');
  await expect(root).toHaveAttribute('data-theme', 'light');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  const lightBackground = await page.locator('body').evaluate((element) => getComputedStyle(element).backgroundColor);

  await toggle.click();
  await expect(root).toHaveAttribute('data-theme', 'dark');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  const darkBackground = await page.locator('body').evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(darkBackground).not.toBe(lightBackground);

  await page.reload();
  await expect(page.locator('#rows-table-body > tr')).toHaveCount(2);
  await expect(root).toHaveAttribute('data-theme', 'dark');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
});
