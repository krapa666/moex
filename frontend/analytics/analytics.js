(() => {
  const form = document.getElementById('analytics-history-form');
  const tickerInput = document.getElementById('analytics-ticker');
  const tableSelect = document.getElementById('analytics-table');
  const status = document.getElementById('analytics-status');
  const summary = document.querySelector('[data-analytics-summary]');
  const empty = document.querySelector('[data-analytics-empty]');
  const timeline = document.querySelector('[data-analytics-timeline]');
  if (!form || !tickerInput || !tableSelect || !status || !summary || !empty || !timeline) return;

  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  });

  async function api(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function formatNumber(value, suffix = '') {
    return finite(value) ? `${numberFormatter.format(Number(value))}${suffix}` : '—';
  }

  function formatPercent(value) {
    return finite(value) ? `${percentFormatter.format(Number(value))} %` : '—';
  }

  function formatDateTime(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.valueOf()) ? dateTimeFormatter.format(date) : '—';
  }

  function publishRevisions(revisions) {
    document.dispatchEvent(new CustomEvent('moex:analytics-revisions', {
      detail: { revisions },
    }));
  }

  function setKpi(name, value) {
    const element = summary.querySelector(`[data-analytics-kpi="${name}"]`);
    if (element) element.textContent = value;
  }

  function setEmpty(title, message) {
    summary.hidden = true;
    timeline.hidden = true;
    timeline.innerHTML = '';
    empty.hidden = false;
    empty.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
  }

  function deltaHtml(current, previous, label) {
    if (!finite(current) || !finite(previous)) return '';
    const delta = Number(current) - Number(previous);
    if (Math.abs(delta) < 0.000001) return `<span class="analytics-revision-delta">${escapeHtml(label)} без изменения</span>`;
    const className = delta > 0 ? 'positive' : 'negative';
    const sign = delta > 0 ? '+' : '';
    return `<span class="analytics-revision-delta ${className}">${escapeHtml(label)} ${sign}${numberFormatter.format(delta)}</span>`;
  }

  function previousForTable(revisions, index) {
    const current = revisions[index];
    for (let cursor = index + 1; cursor < revisions.length; cursor += 1) {
      if (revisions[cursor].table_id === current.table_id) return revisions[cursor];
    }
    return null;
  }

  function render(revisions) {
    publishRevisions(revisions);
    if (!revisions.length) {
      status.textContent = 'Ревизий: 0';
      setEmpty('История не найдена', 'Для выбранного тикера и аналитика сохранённых ревизий пока нет.');
      return;
    }

    const latest = revisions[0];
    setKpi('revisions', String(revisions.length));
    setKpi('analysts', String(new Set(revisions.map((item) => item.table_id)).size));
    setKpi('last-change', formatDateTime(latest.created_at));
    setKpi('latest-fair', formatNumber(latest.forecast_price_year1, ' ₽'));
    summary.hidden = false;
    empty.hidden = true;

    timeline.innerHTML = revisions.map((revision, index) => {
      const year = Number(revision.forecast_start_year);
      const profit = revision.net_profit_year_map?.[String(year)];
      const dividend = revision.dividend_year_map?.[String(year)];
      const previous = previousForTable(revisions, index);
      const previousProfit = previous?.net_profit_year_map?.[String(year)];
      const eventLabel = revision.event_type === 'created' ? 'Первичный прогноз' : 'Ревизия';
      const fairDelta = previous
        ? deltaHtml(revision.forecast_price_year1, previous.forecast_price_year1, 'Fair value')
        : '';
      const profitDelta = previous ? deltaHtml(profit, previousProfit, 'ЧП') : '';
      const source = (revision.net_profit_source_comment || '').trim();

      return `
        <article class="analytics-revision" data-analytics-revision="${revision.id}">
          <div class="analytics-revision-meta">
            <time datetime="${escapeHtml(revision.created_at)}">${formatDateTime(revision.created_at)}</time>
            <span class="analytics-revision-event">${eventLabel}</span>
            <span class="analytics-revision-analyst">${escapeHtml(revision.analyst_name)} · таблица ${revision.table_id}</span>
          </div>
          <div class="analytics-revision-body">
            <div class="analytics-revision-title">
              <strong>${escapeHtml(revision.ticker)} · прогноз ${year}</strong>
              <span>${fairDelta}${fairDelta && profitDelta ? ' · ' : ''}${profitDelta}</span>
            </div>
            <div class="analytics-metrics">
              <div class="analytics-metric"><span>Прогноз ЧП</span><strong>${formatNumber(profit, ' млрд ₽')}</strong></div>
              <div class="analytics-metric"><span>Fair value</span><strong>${formatNumber(revision.forecast_price_year1, ' ₽')}</strong></div>
              <div class="analytics-metric"><span>Полная доходность</span><strong>${formatPercent(revision.upside_percent_year1)}</strong></div>
              <div class="analytics-metric"><span>Дивиденды</span><strong>${formatNumber(dividend, ' ₽/акц.')}</strong></div>
              <div class="analytics-metric"><span>P/E</span><strong>${formatNumber(revision.pe_avg_5y)}</strong></div>
            </div>
            ${source ? `<p class="analytics-source">${escapeHtml(source)}</p>` : ''}
          </div>
        </article>
      `;
    }).join('');
    timeline.hidden = false;
    status.textContent = `Ревизий: ${revisions.length}`;
  }

  function syncUrl(ticker, tableId, { push = true } = {}) {
    const url = new URL(window.location.href);
    if (ticker) url.searchParams.set('ticker', ticker);
    else url.searchParams.delete('ticker');
    if (tableId) url.searchParams.set('table_id', tableId);
    else url.searchParams.delete('table_id');
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (push) window.history.pushState({}, '', next);
    else window.history.replaceState(window.history.state, '', next);
  }

  async function loadHistory({ sync = false, push = true } = {}) {
    const ticker = tickerInput.value.trim().toLocaleUpperCase('ru');
    const tableId = tableSelect.value;
    tickerInput.value = ticker;

    if (!ticker) {
      publishRevisions([]);
      status.textContent = 'Введите тикер';
      setEmpty('История ещё не выбрана', 'Введите тикер, чтобы увидеть сохранённые ревизии прогноза.');
      if (sync) syncUrl('', '', { push });
      return;
    }

    if (sync) syncUrl(ticker, tableId, { push });
    publishRevisions([]);
    status.textContent = `Загрузка ${ticker}…`;
    setEmpty('Загрузка истории…', `Получаем сохранённые ревизии ${ticker}.`);

    const params = new URLSearchParams({ ticker, limit: '200' });
    if (tableId) params.set('table_id', tableId);

    try {
      const revisions = await api(`/api/analytics/forecast-revisions?${params.toString()}`);
      render(revisions);
    } catch (error) {
      publishRevisions([]);
      status.textContent = error.message;
      setEmpty('Не удалось загрузить историю', 'Проверьте доступность Analytics API и повторите запрос.');
    }
  }

  async function loadTables() {
    try {
      const tables = await api('/api/tables');
      const options = tables.map((table) => (
        `<option value="${table.id}">${escapeHtml(table.analyst_name)} · таблица ${table.table_number}</option>`
      )).join('');
      tableSelect.insertAdjacentHTML('beforeend', options);
    } catch (_error) {
      tableSelect.disabled = true;
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    loadHistory({ sync: true, push: true });
  });

  tableSelect.addEventListener('change', () => {
    if (tickerInput.value.trim()) loadHistory({ sync: true, push: true });
  });

  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    tickerInput.value = params.get('ticker') || '';
    tableSelect.value = params.get('table_id') || '';
    loadHistory();
  });

  async function initialize() {
    const params = new URLSearchParams(window.location.search);
    tickerInput.value = params.get('ticker') || '';
    await loadTables();
    const requestedTable = params.get('table_id') || '';
    if ([...tableSelect.options].some((option) => option.value === requestedTable)) {
      tableSelect.value = requestedTable;
    }
    if (tickerInput.value.trim()) await loadHistory();
  }

  initialize();
})();
