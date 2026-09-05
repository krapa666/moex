const state = {
  user: { username: 'guest', is_admin: false },
  config: null,
  rows: [],
  sort: { field: 'ticker', direction: 'asc' },
  filters: { query: '', index: 'all' },
  collectionStartedAt: null,
};

const overviewBody = document.getElementById('volume-overview-body');
const detailBody = document.getElementById('volume-detail-body');
const overviewSection = document.getElementById('overview-section');
const detailSection = document.getElementById('detail-section');
const globalStatus = document.getElementById('volume-global-status');
const authLabel = document.getElementById('volume-auth-label');
const collectBtn = document.getElementById('collect-btn');
const notificationCard = document.getElementById('notification-card');
const notificationForm = document.getElementById('notification-form');
const notificationScope = document.getElementById('notification-scope');
const baselineSessions = document.getElementById('baseline-sessions');
const notificationStatus = document.getElementById('notification-status');
const testEmailBtn = document.getElementById('test-email-btn');
const securitySearch = document.getElementById('security-search');
const indexFilter = document.getElementById('index-filter');
const requestedTicker = new URLSearchParams(window.location.search).get('ticker')?.trim() || '';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function setTickerQuery(ticker) {
  const url = new URL(window.location.href);
  if (ticker) {
    url.searchParams.set('ticker', ticker);
  } else {
    url.searchParams.delete('ticker');
  }
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = payload.detail || '';
    } catch (_error) {
      detail = '';
    }
    throw new Error(detail || `Ошибка API: ${response.status}`);
  }
  return response.json();
}

function setStatus(text) {
  globalStatus.textContent = text;
}

const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const dateFormatter = new Intl.DateTimeFormat('ru-RU');
const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'short',
});

function formatNumber(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(number);
}

function formatMillions(value) {
  const number = Number(value);
  return Number.isFinite(number) ? formatNumber(number / 1_000_000, 1) : '—';
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.valueOf()) ? '—' : dateFormatter.format(date);
}

function statusLabel(status) {
  return {
    signal: 'Сигнал',
    above_range: 'Выше диапазона',
    normal: 'Обычно',
    insufficient: 'Мало истории',
  }[status] || 'Нет данных';
}

function statusHtml(observation) {
  if (!observation) return '<span class="volume-status volume-status-insufficient">Нет данных</span>';
  const status = observation.signal_status || 'insufficient';
  const preliminary = observation.is_final ? '' : '<span class="preliminary-mark">предварительно</span>';
  return `<span class="volume-status volume-status-${escapeHtml(status)}">${statusLabel(status)}</span>${preliminary}`;
}

function sortValue(row, field) {
  if (field === 'ticker') return row.ticker || '';
  if (field === 'type') return row.security_type || '';
  if (field === 'weight') return Number(row.weight ?? Number.NEGATIVE_INFINITY);
  if (field === 'turnover') return Number(row.latest?.turnover_rub ?? Number.NEGATIVE_INFINITY);
  if (field === 'ratio') return Number(row.latest?.ratio ?? Number.NEGATIVE_INFINITY);
  return '';
}

function visibleRows() {
  const query = state.filters.query.toLocaleLowerCase('ru');
  return state.rows.filter((row) => {
    if (state.filters.index === 'imoex' && !row.is_imoex) return false;
    if (state.filters.index === 'outside' && row.is_imoex) return false;
    if (!query) return true;
    return `${row.ticker || ''} ${row.short_name || ''}`.toLocaleLowerCase('ru').includes(query);
  });
}

function sortedRows() {
  const factor = state.sort.direction === 'asc' ? 1 : -1;
  return visibleRows().sort((left, right) => {
    const a = sortValue(left, state.sort.field);
    const b = sortValue(right, state.sort.field);
    if (typeof a === 'string') return a.localeCompare(b, 'ru') * factor;
    return (a - b) * factor;
  });
}

function renderOverview() {
  const rows = sortedRows();
  if (!rows.length) {
    const message = state.rows.length
      ? 'По заданному фильтру бумаг нет.'
      : 'Данные появятся после первого сбора с MOEX.';
    overviewBody.innerHTML = `<tr class="empty-volume-row"><td colspan="9">${message}</td></tr>`;
    updateOverviewStatus();
    return;
  }
  overviewBody.innerHTML = rows.map((row) => {
    const latest = row.latest;
    const securityType = row.security_type === 'preferred' ? 'ап' : 'ао';
    return `
      <tr>
        <td><button class="ticker-link" data-ticker="${escapeHtml(row.ticker)}">${escapeHtml(row.ticker)}</button></td>
        <td>${escapeHtml(row.short_name)}</td>
        <td>${securityType}</td>
        <td>${row.weight == null ? '—' : formatNumber(row.weight, 2)}</td>
        <td>${formatDate(latest?.trade_date)}</td>
        <td>${formatMillions(latest?.turnover_rub)}</td>
        <td>${formatMillions(latest?.baseline_average_rub)}</td>
        <td>${latest?.ratio == null ? '—' : `${formatNumber(latest.ratio, 2)}×`}</td>
        <td>${statusHtml(latest)}</td>
      </tr>`;
  }).join('');
  updateOverviewStatus();
}

function updateOverviewStatus() {
  const shown = visibleRows().length;
  setStatus(shown === state.rows.length
    ? `Показано бумаг: ${shown}`
    : `Показано бумаг: ${shown} из ${state.rows.length}`);
}

async function loadOverview() {
  state.rows = await api('/api/volume/overview');
  renderOverview();
}

function renderLastRun(run) {
  const label = document.getElementById('last-run-label');
  const detail = document.getElementById('last-run-detail');
  if (!run) {
    label.textContent = 'Данных пока нет';
    detail.textContent = 'Worker выполнит первичную загрузку после запуска.';
    return;
  }
  const when = new Date(run.finished_at || run.started_at);
  label.textContent = `${run.status === 'success' ? 'Успешно' : run.status} · ${dateTimeFormatter.format(when)}`;
  detail.textContent =
    `Обновлено ${run.securities_updated} из ${run.securities_total}; аномалий: ${run.signals_found}; ` +
    `IMOEX: ${run.imoex_anomalies_found || 0}; отправлено: ${run.notifications_sent || 0}; ` +
    `подавлено: ${run.notifications_suppressed || 0}; история обновлена для ` +
    `${run.history_securities_refreshed || 0} бумаг.`;
  if (run.error_message) detail.textContent += ` Ошибка: ${run.error_message}`;
}

async function loadLastRun() {
  const run = await api('/api/volume/runs/latest');
  renderLastRun(run);
  return run;
}

async function loadConfig() {
  state.config = await api('/api/volume/config');
  const min = formatNumber(state.config.signal_min_ratio, 1);
  const max = formatNumber(state.config.signal_max_ratio, 1);
  const schedule = (state.config.schedule_minutes || [])
    .map((minute) => `${String(state.config.schedule_hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`)
    .join(', ');
  const broadMarketThreshold = state.config.broad_market_signal_threshold || 10;
  document.getElementById('signal-range-label').textContent = `${min}×–${max}×`;
  document.getElementById('signal-policy-label').textContent =
    `Коэффициенты выше ${max}× отправляются, кроме случаев, когда аномалии одновременно есть более чем у ` +
    `${broadMarketThreshold} акций IMOEX.`;
  document.getElementById('volume-subtitle').textContent =
    `Текущий оборот сравнивается с ${state.config.baseline_sessions} предыдущими торговыми сессиями. ` +
    `Сбор по будням в ${schedule} ` +
    `${state.config.schedule_timezone}.`;
}

async function loadAuthAndSettings() {
  try {
    state.user = await api('/api/auth/me');
  } catch (_error) {
    state.user = { username: 'guest', is_admin: false };
  }
  authLabel.textContent = state.user.is_admin ? 'Локальная сеть · управление' : 'Гость · только чтение';
  collectBtn.hidden = !state.user.is_admin;
  notificationCard.hidden = !state.user.is_admin;
  if (!state.user.is_admin) return;

  const settings = await api('/api/volume/settings');
  notificationScope.value = settings.notification_scope || 'imoex';
  baselineSessions.value = settings.baseline_sessions || 60;
  notificationStatus.textContent = settings.smtp_configured
    ? (settings.notifications_enabled
      ? 'Уведомления включены.'
      : 'Задайте VOLUME_NOTIFICATION_EMAIL в .env.')
    : 'Настройте SMTP и VOLUME_NOTIFICATION_EMAIL в .env.';
}

async function openDetail(ticker) {
  const normalizedTicker = String(ticker || '').trim().toLocaleUpperCase('ru');
  if (!normalizedTicker) return;

  setStatus(`Загрузка ${normalizedTicker}...`);
  try {
    const data = await api(`/api/volume/securities/${encodeURIComponent(normalizedTicker)}/observations?limit=${state.config?.display_sessions || 60}`);
    setTickerQuery(data.ticker || normalizedTicker);
    document.getElementById('detail-title').textContent = `${data.ticker} — история объёмов`;
    document.getElementById('detail-subtitle').textContent = data.short_name || '';
    detailBody.innerHTML = data.observations.map((item) => `
      <tr>
        <td>${formatDate(item.trade_date)}</td>
        <td>${formatMillions(item.turnover_rub)}</td>
        <td>${item.volume_units == null ? '—' : numberFormatter.format(Number(item.volume_units))}</td>
        <td>${formatNumber(item.close_price, 4)}</td>
        <td>${formatMillions(item.baseline_average_rub)}</td>
        <td>${item.baseline_count}</td>
        <td>${item.ratio == null ? '—' : `${formatNumber(item.ratio, 2)}×`}</td>
        <td>${statusHtml(item)}</td>
      </tr>`).join('');
    overviewSection.hidden = true;
    detailSection.hidden = false;
    setStatus(`${data.ticker}: ${data.observations.length} сессий`);
  } catch (error) {
    setStatus(error.message);
  }
}

async function pollCollection() {
  for (let attempt = 0; attempt < 36; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const run = await loadLastRun();
    if (run?.finished_at && new Date(run.started_at).valueOf() >= state.collectionStartedAt) {
      await loadOverview();
      setStatus(run.status === 'success' ? 'Сбор завершён' : `Сбор завершён: ${run.status}`);
      collectBtn.disabled = false;
      return;
    }
  }
  setStatus('Сбор продолжается в фоне');
  collectBtn.disabled = false;
}

document.querySelectorAll('.volume-sort').forEach((button) => {
  button.addEventListener('click', () => {
    const field = button.dataset.sort;
    if (state.sort.field === field) {
      state.sort.direction = state.sort.direction === 'asc' ? 'desc' : 'asc';
    } else {
      state.sort = { field, direction: field === 'ticker' ? 'asc' : 'desc' };
    }
    renderOverview();
  });
});

overviewBody.addEventListener('click', (event) => {
  const button = event.target.closest('[data-ticker]');
  if (button) openDetail(button.dataset.ticker);
});

document.getElementById('detail-back-btn').addEventListener('click', () => {
  detailSection.hidden = true;
  overviewSection.hidden = false;
  setTickerQuery('');
  updateOverviewStatus();
});

securitySearch.addEventListener('input', () => {
  state.filters.query = securitySearch.value.trim();
  renderOverview();
});

indexFilter.addEventListener('change', () => {
  state.filters.index = indexFilter.value;
  renderOverview();
});

notificationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  notificationStatus.textContent = 'Сохранение...';
  try {
    const settings = await api('/api/volume/settings', {
      method: 'PUT',
      body: JSON.stringify({
        notification_scope: notificationScope.value,
        baseline_sessions: Number(baselineSessions.value),
      }),
    });
    state.config.baseline_sessions = settings.baseline_sessions;
    await loadConfig();
    notificationStatus.textContent = settings.smtp_configured
      ? (settings.notifications_enabled
        ? 'Настройки сохранены; новый период среднего применится при следующем сборе.'
        : 'Настройки сохранены; уведомления выключены без получателя.')
      : 'Настройки сохранены. Для отправки писем настройте SMTP в .env.';
  } catch (error) {
    notificationStatus.textContent = error.message;
  }
});

testEmailBtn.addEventListener('click', async () => {
  testEmailBtn.disabled = true;
  notificationStatus.textContent = 'Отправка тестового письма...';
  try {
    const result = await api('/api/volume/notifications/test', {
      method: 'POST',
      body: '{}',
    });
    notificationStatus.textContent = result.detail;
  } catch (error) {
    notificationStatus.textContent = error.message;
  } finally {
    testEmailBtn.disabled = false;
  }
});

collectBtn.addEventListener('click', async () => {
  collectBtn.disabled = true;
  setStatus('Запуск сбора...');
  try {
    state.collectionStartedAt = Date.now() - 2000;
    await api('/api/volume/collect', { method: 'POST', body: '{}' });
    setStatus('Сбор выполняется...');
    pollCollection();
  } catch (error) {
    setStatus(error.message);
    collectBtn.disabled = false;
  }
});

async function initialize() {
  try {
    await Promise.all([loadConfig(), loadAuthAndSettings(), loadLastRun(), loadOverview()]);
    updateOverviewStatus();
    if (requestedTicker) {
      await openDetail(requestedTicker);
    }
  } catch (error) {
    setStatus(error.message);
  }
}

initialize();