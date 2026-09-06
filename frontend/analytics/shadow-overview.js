(() => {
  const anchor = document.querySelector('[data-analytics-today]');
  if (!anchor) return;

  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const statusRank = { alert: 0, watch: 1, stable: 2, insufficient: 3 };
  const reasonLabels = {
    large_baseline_divergence: 'большое расхождение с медианой',
    rapid_divergence_change: 'быстрый скачок расхождения',
    weight_concentration: 'повышенная концентрация веса',
    relative_movement_gap: 'weighted и median движутся по-разному',
    training_snapshot_changed: 'сменился historical snapshot',
    too_few_snapshots: 'мало snapshot',
    history_too_short: 'история короче 24 часов',
    no_history: 'история ещё не накоплена',
  };
  const statusLabels = {
    alert: 'ALERT',
    watch: 'WATCH',
    stable: 'STABLE',
    insufficient: 'НАКОПЛЕНИЕ',
  };

  let current = null;
  let requestSeq = 0;

  const panel = document.createElement('section');
  panel.className = 'analytics-panel shadow-overview-panel';
  panel.dataset.shadowOverview = '';
  panel.innerHTML = `
    <header class="analytics-panel-heading shadow-overview-heading">
      <div>
        <span class="analytics-panel-kicker">Forward model monitoring</span>
        <h2>Shadow drift — весь universe</h2>
        <p>Единый forward-монитор weighted-модели. ALERT и WATCH показаны первыми; production consensus остаётся медианным.</p>
      </div>
      <div class="shadow-overview-controls">
        <label>
          <span>Окно</span>
          <select data-shadow-overview-days>
            <option value="7">7 дней</option>
            <option value="30" selected>30 дней</option>
            <option value="90">90 дней</option>
            <option value="180">180 дней</option>
          </select>
        </label>
        <label>
          <span>Статус</span>
          <select data-shadow-overview-filter>
            <option value="all">Все</option>
            <option value="actionable">ALERT + WATCH</option>
            <option value="alert">ALERT</option>
            <option value="watch">WATCH</option>
            <option value="stable">STABLE</option>
            <option value="insufficient">Накопление</option>
          </select>
        </label>
        <span class="shadow-overview-status" data-shadow-overview-status role="status" aria-live="polite">Загрузка…</span>
      </div>
    </header>
    <div class="shadow-overview-summary" data-shadow-overview-summary hidden></div>
    <div class="shadow-overview-empty" data-shadow-overview-empty hidden></div>
    <div class="shadow-overview-table-wrap" data-shadow-overview-table-wrap hidden>
      <table class="shadow-overview-table">
        <thead>
          <tr>
            <th>Тикер</th>
            <th>Статус</th>
            <th>Δ weighted / median</th>
            <th>Шаг Δ</th>
            <th>Концентрация</th>
            <th>Разница движения</th>
            <th>История</th>
            <th>Причины</th>
          </tr>
        </thead>
        <tbody data-shadow-overview-body></tbody>
      </table>
    </div>
  `;
  anchor.insertAdjacentElement('afterend', panel);

  const daysSelect = panel.querySelector('[data-shadow-overview-days]');
  const filterSelect = panel.querySelector('[data-shadow-overview-filter]');
  const status = panel.querySelector('[data-shadow-overview-status]');
  const summary = panel.querySelector('[data-shadow-overview-summary]');
  const empty = panel.querySelector('[data-shadow-overview-empty]');
  const tableWrap = panel.querySelector('[data-shadow-overview-table-wrap]');
  const body = panel.querySelector('[data-shadow-overview-body]');

  function finite(value) {
    return value !== null && value !== undefined && Number.isFinite(Number(value));
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function signedPercent(value, suffix = ' %') {
    if (!finite(value)) return '—';
    const number = Number(value);
    return `${number > 0 ? '+' : ''}${percentFormatter.format(number)}${suffix}`;
  }

  function ratio(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))}×` : '—';
  }

  function historyLabel(item) {
    if (!item.snapshots) return '0 точек';
    const days = Number(item.history_span_hours || 0) / 24;
    return `${item.snapshots} · ${numberFormatter.format(days)} дн.`;
  }

  function reasonsLabel(item) {
    if (!Array.isArray(item.reasons) || !item.reasons.length) return '—';
    return item.reasons.map((reason) => reasonLabels[reason] || reason).join('; ');
  }

  function renderSummary(result) {
    summary.hidden = false;
    summary.innerHTML = `
      <article><span>Universe</span><strong>${result.universe_tickers}</strong></article>
      <article><span>Есть history</span><strong>${percentFormatter.format(result.history_coverage_percent)}%</strong></article>
      <article><span>Классифицировано</span><strong>${result.classified_tickers}</strong></article>
      <article class="shadow-overview-alert"><span>ALERT</span><strong>${result.alert_tickers}</strong></article>
      <article class="shadow-overview-watch"><span>WATCH</span><strong>${result.watch_tickers}</strong></article>
      <article class="shadow-overview-stable"><span>STABLE</span><strong>${result.stable_tickers}</strong></article>
      <article><span>Накопление</span><strong>${result.insufficient_tickers}</strong></article>
      <article><span>Требуют внимания</span><strong>${result.actionable_tickers}</strong></article>
    `;
  }

  function filteredItems(result) {
    const selected = filterSelect.value;
    const items = [...(result.items || [])];
    items.sort((left, right) => {
      const statusDelta = (statusRank[left.status] ?? 99) - (statusRank[right.status] ?? 99);
      if (statusDelta) return statusDelta;
      const leftDelta = finite(left.latest_delta_percent) ? Math.abs(Number(left.latest_delta_percent)) : -1;
      const rightDelta = finite(right.latest_delta_percent) ? Math.abs(Number(right.latest_delta_percent)) : -1;
      return rightDelta - leftDelta || String(left.ticker).localeCompare(String(right.ticker));
    });
    if (selected === 'all') return items;
    if (selected === 'actionable') return items.filter((item) => item.status === 'alert' || item.status === 'watch');
    return items.filter((item) => item.status === selected);
  }

  function renderRows(result) {
    const items = filteredItems(result);
    if (!items.length) {
      tableWrap.hidden = true;
      empty.hidden = false;
      empty.textContent = filterSelect.value === 'all'
        ? 'В основной таблице пока нет бумаг для shadow monitoring.'
        : 'Для выбранного фильтра бумаг нет.';
      return;
    }

    empty.hidden = true;
    tableWrap.hidden = false;
    body.innerHTML = items.map((item) => `
      <tr data-shadow-overview-row="${escapeHtml(item.ticker)}" data-shadow-overview-status-value="${escapeHtml(item.status)}">
        <td><a href="/analytics/?ticker=${encodeURIComponent(item.ticker)}">${escapeHtml(item.ticker)}</a>${item.target_year ? `<small>${item.target_year}</small>` : ''}</td>
        <td><span class="shadow-overview-badge shadow-overview-badge-${escapeHtml(item.status)}">${escapeHtml(statusLabels[item.status] || item.status)}</span></td>
        <td>${escapeHtml(signedPercent(item.latest_delta_percent))}</td>
        <td>${escapeHtml(signedPercent(item.delta_step_percentage_points, ' п.п.'))}</td>
        <td>${escapeHtml(ratio(item.latest_weight_concentration_ratio))}</td>
        <td>${escapeHtml(signedPercent(item.relative_movement_gap_percentage_points, ' п.п.'))}</td>
        <td>${escapeHtml(historyLabel(item))}</td>
        <td class="shadow-overview-reasons">${escapeHtml(reasonsLabel(item))}</td>
      </tr>
    `).join('');
  }

  function render(result) {
    current = result;
    renderSummary(result);
    renderRows(result);
    const actionable = Number(result.actionable_tickers || 0);
    status.textContent = actionable
      ? `Требуют внимания: ${actionable}`
      : `Universe: ${result.universe_tickers}`;
  }

  async function load() {
    const seq = requestSeq + 1;
    requestSeq = seq;
    const days = Number(daysSelect.value) || 30;
    status.textContent = 'Обновление…';
    try {
      const response = await fetch(`/api/analytics/shadow-consensus/overview?days=${days}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (seq !== requestSeq) return;
      render(result || {});
    } catch (_error) {
      if (seq !== requestSeq) return;
      current = null;
      summary.hidden = true;
      tableWrap.hidden = true;
      empty.hidden = false;
      empty.textContent = 'Не удалось загрузить глобальный shadow drift. Детальный production consensus работает независимо.';
      status.textContent = 'Монитор недоступен';
    }
  }

  daysSelect.addEventListener('change', load);
  filterSelect.addEventListener('change', () => {
    if (current) renderRows(current);
  });

  load();
})();
