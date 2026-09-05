const { test, expect } = require('@playwright/test');

const overview = [
  {
    ticker: 'SBER',
    short_name: 'Сбербанк',
    weight: 12.5,
    latest: {
      trade_date: '2026-08-10',
      turnover_rub: 4000000000,
      baseline_average_rub: 1000000000,
      ratio: 4,
      signal_status: 'signal',
      is_final: false,
    },
  },
  {
    ticker: 'GAZP',
    short_name: 'Газпром',
    weight: 8.2,
    latest: {
      trade_date: '2026-08-10',
      turnover_rub: 7000000000,
      baseline_average_rub: 1000000000,
      ratio: 7,
      signal_status: 'above_range',
      is_final: false,
    },
  },
  {
    ticker: 'YRSBP',
    short_name: 'ТНС энерго Ярославль-п',
    security_type: 'preferred',
    is_imoex: false,
    weight: null,
    latest: {
      trade_date: '2026-08-10',
      turnover_rub: 12000000,
      baseline_average_rub: 10000000,
      ratio: 1.2,
      signal_status: 'normal',
      is_final: false,
    },
  },
];

overview[0].security_type = 'common';
overview[0].is_imoex = true;
overview[1].security_type = 'common';
overview[1].is_imoex = true;

async function mockVolumeApi(page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
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
          schedule: '18:20, 18:35, 18:45 Europe/Moscow',
        },
      });
    }
    if (url.pathname === '/api/volume/runs/latest') {
      return route.fulfill({
        json: {
          started_at: '2026-08-10T15:40:00Z',
          finished_at: '2026-08-10T15:41:00Z',
          status: 'success',
          securities_total: 2,
          securities_updated: 2,
          signals_found: 1,
          imoex_anomalies_found: 1,
          notifications_sent: 1,
          notifications_suppressed: 0,
          history_securities_refreshed: 2,
          error_message: null,
        },
      });
    }
    if (url.pathname === '/api/volume/overview') {
      return route.fulfill({ json: overview });
    }
    if (url.pathname === '/api/volume/notifications/test') {
      return route.fulfill({ json: { status: 'sent', detail: 'Тестовое письмо отправлено' } });
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
              source: 'intraday',
            },
          ],
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: `Unexpected ${url.pathname}` } });
  });
}

test.beforeEach(async ({ page }) => {
  await mockVolumeApi(page);
  await page.goto('/volumes/');
  await expect(page.locator('#volume-overview-body > tr')).toHaveCount(3);
});

test('shows unified navigation and the integrated volume table', async ({ page }) => {
  await expect(page.getByRole('link', { name: 'Оценки' })).toHaveAttribute('href', '/');
  await expect(page.getByRole('link', { name: 'Объёмы' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByText('3,6×–6,5×', { exact: true })).toBeVisible();
  await expect(page.getByText(/Сбор по будням в 18:20, 18:35, 18:45/)).toBeVisible();
  await expect(page.locator('#notification-scope')).toHaveValue('imoex');
  await expect(page.locator('#baseline-sessions')).toHaveValue('60');
  await expect(page.getByText('Сигнал', { exact: true })).toBeVisible();
  await expect(page.getByText('Выше диапазона', { exact: true })).toBeVisible();
});

test('opens per-ticker history without horizontal scrolling', async ({ page }) => {
  await page.getByRole('button', { name: 'SBER' }).click();
  await expect(page.locator('#detail-title')).toHaveText('SBER — история объёмов');
  await expect(page.locator('#volume-detail-body > tr')).toHaveCount(1);
  expect(new URL(page.url()).searchParams.get('ticker')).toBe('SBER');

  const layout = await page.locator('#detail-section .table-wrap').evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);

  await page.getByRole('button', { name: '← К списку' }).click();
  await expect(page.locator('#overview-section')).toBeVisible();
  expect(new URL(page.url()).searchParams.get('ticker')).toBeNull();
});

test('opens per-ticker history directly from a ticker query parameter', async ({ page }) => {
  await page.goto('/volumes/?ticker=sber');

  await expect(page.locator('#detail-title')).toHaveText('SBER — история объёмов');
  await expect(page.locator('#detail-section')).toBeVisible();
  await expect(page.locator('#overview-section')).toBeHidden();
  await expect(page.locator('#volume-detail-body > tr')).toHaveCount(1);
  expect(new URL(page.url()).searchParams.get('ticker')).toBe('SBER');

  await page.getByRole('button', { name: '← К списку' }).click();
  await expect(page.locator('#overview-section')).toBeVisible();
  await expect(page).toHaveURL('/volumes/');
});

test('copies the canonical volume deep link from ticker history', async ({ page }) => {
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text) => {
          window.__copiedMoexUrl = text;
        },
      },
    });
  });

  await page.getByRole('button', { name: 'SBER' }).click();
  await expect(page).toHaveURL('/volumes/?ticker=SBER');

  const copyButton = page.locator('#detail-section [data-copy-current-url]');
  await copyButton.click();

  expect(await page.evaluate(() => window.__copiedMoexUrl)).toBe(page.url());
  await expect(copyButton).toHaveText('Ссылка скопирована');
  await expect(copyButton).toHaveAttribute('data-copy-state', 'success');
});

test('cleans a missing volume ticker deep link and keeps the overview usable', async ({ page }) => {
  await page.goto('/volumes/?ticker=UNKNOWN');

  await expect(page.locator('#overview-section')).toBeVisible();
  await expect(page.locator('#detail-section')).toBeHidden();
  await expect(page).toHaveURL('/volumes/');
  await expect(page.locator('#volume-global-status')).toContainText('Не удалось открыть UNKNOWN');
});

test('uses browser back and forward for volume details without refetching cached history', async ({ page }) => {
  let observationRequests = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/volume/securities/SBER/observations') {
      observationRequests += 1;
    }
  });

  await page.getByRole('button', { name: 'SBER' }).click();
  await expect(page.locator('#detail-section')).toBeVisible();
  await expect(page).toHaveURL('/volumes/?ticker=SBER');
  expect(observationRequests).toBe(1);

  await page.goBack();
  await expect(page.locator('#overview-section')).toBeVisible();
  await expect(page.locator('#detail-section')).toBeHidden();
  await expect(page).toHaveURL('/volumes/');

  await page.goForward();
  await expect(page.locator('#detail-section')).toBeVisible();
  await expect(page.locator('#detail-title')).toHaveText('SBER — история объёмов');
  await expect(page).toHaveURL('/volumes/?ticker=SBER');
  expect(observationRequests).toBe(1);
});

test('sorts overview by ratio', async ({ page }) => {
  await page.getByRole('button', { name: /Коэффициент/ }).click();
  const tickers = await page.locator('#volume-overview-body .ticker-link').allTextContents();
  expect(tickers).toEqual(['GAZP', 'SBER', 'YRSBP']);
});

test('filters the full TQBR universe by index and search text', async ({ page }) => {
  await page.locator('#index-filter').selectOption('outside');
  await expect(page.locator('#volume-overview-body .ticker-link')).toHaveText(['YRSBP']);
  await expect(page.locator('#volume-global-status')).toHaveText('Показано бумаг: 1 из 3');

  await page.locator('#index-filter').selectOption('all');
  await page.locator('#security-search').fill('сбер');
  await expect(page.locator('#volume-overview-body .ticker-link')).toHaveText(['SBER']);
});

test('saves notification scope and baseline then sends a test email', async ({ page }) => {
  await page.locator('#notification-scope').selectOption('all');
  await page.locator('#baseline-sessions').fill('90');
  const settingsRequest = page.waitForRequest((request) =>
    request.url().endsWith('/api/volume/settings') && request.method() === 'PUT');
  await page.getByRole('button', { name: 'Сохранить' }).click();
  const request = await settingsRequest;
  expect(request.postDataJSON()).toEqual({
    notification_scope: 'all',
    baseline_sessions: 90,
  });

  await page.getByRole('button', { name: 'Тест письма' }).click();
  await expect(page.locator('#notification-status')).toHaveText('Тестовое письмо отправлено');
});
