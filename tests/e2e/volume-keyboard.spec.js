const { test, expect } = require('@playwright/test');

const overview = [
  {
    ticker: 'SBER',
    short_name: 'Сбербанк',
    security_type: 'common',
    is_imoex: true,
    weight: 12.5,
    latest: {
      trade_date: '2026-09-05',
      turnover_rub: 4000000000,
      baseline_average_rub: 1000000000,
      ratio: 4,
      signal_status: 'signal',
      is_final: true,
    },
  },
];

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/auth/me') {
      return route.fulfill({ json: { username: 'local-network', is_admin: true } });
    }
    if (url.pathname === '/api/volume/config') {
      return route.fulfill({
        json: {
          baseline_sessions: 60,
          display_sessions: 60,
          signal_min_ratio: 3.6,
          signal_max_ratio: 6.5,
          broad_market_signal_threshold: 10,
          schedule_hour: 18,
          schedule_minutes: [20, 35, 45],
          schedule_timezone: 'Europe/Moscow',
          smtp_configured: true,
        },
      });
    }
    if (url.pathname === '/api/volume/settings') {
      return route.fulfill({
        json: {
          notification_scope: 'imoex',
          baseline_sessions: 60,
          smtp_configured: true,
          notifications_enabled: true,
        },
      });
    }
    if (url.pathname === '/api/volume/runs/latest') {
      return route.fulfill({ json: null });
    }
    if (url.pathname === '/api/volume/overview') {
      return route.fulfill({ json: overview });
    }
    if (url.pathname === '/api/volume/securities/SBER/observations') {
      return route.fulfill({
        json: {
          ticker: 'SBER',
          short_name: 'Сбербанк',
          security_type: 'common',
          is_imoex: true,
          weight: 12.5,
          observations: [
            {
              ...overview[0].latest,
              volume_units: 12000000,
              close_price: 320.5,
              baseline_count: 60,
            },
          ],
        },
      });
    }

    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test('Escape returns from volume history and restores focus to the ticker', async ({ page }) => {
  await mockApi(page);
  await page.goto('/volumes/');

  const tickerButton = page.getByRole('button', { name: 'SBER' });
  await expect(tickerButton).toBeVisible();
  await tickerButton.click();
  await expect(page.locator('#detail-section')).toBeVisible();
  await expect(page).toHaveURL('/volumes/?ticker=SBER');

  await page.keyboard.press('Escape');

  await expect(page.locator('#overview-section')).toBeVisible();
  await expect(page.locator('#detail-section')).toBeHidden();
  await expect(page).toHaveURL('/volumes/');
  await expect(tickerButton).toBeFocused();
});

test('Escape closes a direct volume deep link without navigating away', async ({ page }) => {
  await mockApi(page);
  await page.goto('/volumes/?ticker=SBER');

  await expect(page.locator('#detail-section')).toBeVisible();
  await expect(page).toHaveURL('/volumes/?ticker=SBER');

  await page.keyboard.press('Escape');

  await expect(page.locator('#overview-section')).toBeVisible();
  await expect(page.locator('#detail-section')).toBeHidden();
  await expect(page).toHaveURL('/volumes/');
});
