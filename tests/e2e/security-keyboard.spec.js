const { test, expect } = require('@playwright/test');

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'test-admin', is_admin: true } });
    }
    if (url.pathname === '/api/tables') {
      return route.fulfill({
        json: [{ id: 1, table_number: 1, analyst_name: 'Тестовый аналитик', forecast_start_year: 2026 }],
      });
    }
    if (url.pathname === '/api/rows') {
      return route.fulfill({
        json: [
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
            price_updated_at: '2026-09-05T10:00:00Z',
            net_profit_source_comment: 'Тестовый комментарий',
            status_message: null,
            shared_fields_editable: true,
          },
        ],
      });
    }

    return route.fulfill({ status: 404, json: { detail: `Unexpected ${request.method()} ${url.pathname}` } });
  });
}

test('keeps Tab focus inside the stock drawer and restores the details trigger on close', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');

  const trigger = page.locator('#rows-table-body > tr').first().getByRole('button', { name: 'Подробнее' });
  await expect(trigger).toBeVisible();
  await trigger.click();

  const overlay = page.locator('#security-detail-overlay');
  const drawer = overlay.locator('.security-detail-drawer');
  const copyButton = drawer.locator('[data-copy-current-url]');
  const closeButton = drawer.getByRole('button', { name: 'Закрыть', exact: true });
  const lastInput = drawer.locator('[data-detail-input="dividends2"]');

  await expect(overlay).toBeVisible();
  await expect(page).toHaveURL('/?ticker=SBER');
  await expect(closeButton).toBeFocused();

  await copyButton.focus();
  await page.keyboard.press('Shift+Tab');
  await expect(lastInput).toBeFocused();

  await page.keyboard.press('Tab');
  await expect(copyButton).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(overlay).toBeHidden();
  await expect(page).toHaveURL('/');
  await expect(trigger).toBeFocused();
});
