(() => {
  const panel = document.querySelector('[data-source-accuracy]');
  if (!panel) return;

  const snapshotSelect = panel.querySelector('[data-accuracy-snapshot]');
  const adminBlock = panel.querySelector('[data-actual-admin]');
  const factsBody = panel.querySelector('[data-actual-facts-body]');
  if (!snapshotSelect || !adminBlock) return;

  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = '/analytics/coverage.css';
  document.head.append(stylesheet);

  const section = document.createElement('section');
  section.className = 'actual-coverage';
  section.dataset.actualCoverage = '';
  section.innerHTML = `
    <div class="actual-coverage-heading">
      <div>
        <span class="analytics-panel-kicker">Actual results coverage</span>
        <h3>Покрытие фактическими результатами</h3>
        <p>Доля исторических пар «источник × бумага × год», для которых прогноз уже существовал на выбранной отсечке и теперь есть канонический факт ЧП. Незавершённые финансовые годы в знаменатель не попадают.</p>
      </div>
      <span class="analytics-status" data-actual-coverage-status role="status" aria-live="polite">Расчёт…</span>
    </div>
    <div class="source-accuracy-empty" data-actual-coverage-empty hidden></div>
    <div data-actual-coverage-body hidden>
      <div class="actual-coverage-summary" aria-label="Сводка покрытия фактическими результатами">
        <article><span>Покрытие</span><strong data-actual-coverage-kpi="coverage">—</strong></article>
        <article><span>Оцениваемых пар</span><strong data-actual-coverage-kpi="covered">—</strong></article>
        <article><span>Не хватает фактов</span><strong data-actual-coverage-kpi="missing">—</strong></article>
        <article><span>Фактов в реестре</span><strong data-actual-coverage-kpi="actuals">—</strong></article>
      </div>
      <div class="actual-coverage-grid">
        <div>
          <h4>По финансовым годам</h4>
          <div class="actual-coverage-table-wrap">
            <table class="actual-coverage-table">
              <thead><tr><th>Год</th><th>Пар прогнозов</th><th>С фактом</th><th>Без факта</th><th>Покрытие</th><th>Фактов</th></tr></thead>
              <tbody data-actual-coverage-year-body></tbody>
            </table>
          </div>
        </div>
        <div>
          <h4>По источникам</h4>
          <div class="actual-coverage-table-wrap">
            <table class="actual-coverage-table">
              <thead><tr><th>Источник</th><th>Пар</th><th>С фактом</th><th>Без факта</th><th>Покрытие</th></tr></thead>
              <tbody data-actual-coverage-source-body></tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="actual-coverage-missing" data-actual-coverage-missing hidden>
        <h4>Приоритет заполнения фактов</h4>
        <p>Сначала показаны тикеры и годы, отсутствие которых блокирует оценку большего числа источников.</p>
        <div class="actual-coverage-missing-list" data-actual-coverage-missing-list></div>
      </div>
    </div>
  `;
  adminBlock.insertAdjacentElement('beforebegin', section);

  const status = section.querySelector('[data-actual-coverage-status]');
  const empty = section.querySelector('[data-actual-coverage-empty]');
  const body = section.querySelector('[data-actual-coverage-body]');
  const yearBody = section.querySelector('[data-actual-coverage-year-body]');
  const sourceBody = section.querySelector('[data-actual-coverage-source-body]');
  const missingBlock = section.querySelector('[data-actual-coverage-missing]');
  const missingList = section.querySelector('[data-actual-coverage-missing-list]');

  function formatNumber(value, digits = 0) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    return Number(value).toLocaleString('ru-RU', {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    });
  }

  function formatPercent(value) {
    const formatted = formatNumber(value, 1);
    return formatted === '—' ? formatted : `${formatted}%`;
  }

  function createCell(text, className = '') {
    const cell = document.createElement('td');
    cell.textContent = text;
    if (className) cell.className = className;
    return cell;
  }

  function displaySource(row) {
    const access = window.MoexAnalyticsAccess;
    if (!access) return row.analyst_name || 'Источник';
    const tableNumber = access.tableNumberForId(row.table_id);
    return access.displayAnalystName(tableNumber, row.analyst_name);
  }

  function renderCoverage(result) {
    const total = Number(result?.forecast_pairs || 0);
    if (!total) {
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = 'В выбранном окне пока нет исторических прогнозов, существовавших до этой отсечки.';
      status.textContent = 'Нет исторической базы';
      return;
    }

    empty.hidden = true;
    body.hidden = false;

    section.querySelector('[data-actual-coverage-kpi="coverage"]').textContent = formatPercent(result.coverage_percent);
    section.querySelector('[data-actual-coverage-kpi="covered"]').textContent = `${formatNumber(result.covered_pairs)} / ${formatNumber(result.forecast_pairs)}`;
    section.querySelector('[data-actual-coverage-kpi="missing"]').textContent = formatNumber(result.missing_actual_records);
    section.querySelector('[data-actual-coverage-kpi="actuals"]').textContent = formatNumber(result.actual_records);

    yearBody.replaceChildren();
    for (const row of result.by_year || []) {
      const tr = document.createElement('tr');
      tr.append(
        createCell(String(row.fiscal_year), 'actual-coverage-key'),
        createCell(formatNumber(row.forecast_pairs)),
        createCell(formatNumber(row.covered_pairs)),
        createCell(formatNumber(row.missing_forecast_pairs)),
        createCell(formatPercent(row.coverage_percent)),
        createCell(formatNumber(row.actual_records)),
      );
      yearBody.append(tr);
    }

    sourceBody.replaceChildren();
    for (const row of result.by_source || []) {
      const tr = document.createElement('tr');
      tr.append(
        createCell(displaySource(row), 'actual-coverage-key'),
        createCell(formatNumber(row.forecast_pairs)),
        createCell(formatNumber(row.covered_pairs)),
        createCell(formatNumber(row.missing_forecast_pairs)),
        createCell(formatPercent(row.coverage_percent)),
      );
      sourceBody.append(tr);
    }

    missingList.replaceChildren();
    const missing = Array.isArray(result.missing_actuals) ? result.missing_actuals : [];
    missingBlock.hidden = !missing.length;
    for (const row of missing) {
      const item = document.createElement('span');
      item.className = 'actual-coverage-missing-item';
      item.textContent = `${row.ticker} ${row.fiscal_year} · ${row.sources} ист.`;
      missingList.append(item);
    }

    status.textContent = `${formatNumber(result.covered_pairs)} из ${formatNumber(result.forecast_pairs)} · ${formatPercent(result.coverage_percent)}`;
  }

  async function loadCoverage() {
    status.textContent = 'Расчёт…';
    const snapshot = snapshotSelect.value || 'pre_year';
    try {
      const response = await fetch(
        `/api/analytics/actual-net-profits/coverage?snapshot=${encodeURIComponent(snapshot)}&years=5&missing_limit=20`,
      );
      if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
      renderCoverage(await response.json());
    } catch (error) {
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = error.message;
      status.textContent = 'Ошибка';
    }
  }

  let reloadTimer = null;
  function scheduleReload() {
    window.clearTimeout(reloadTimer);
    reloadTimer = window.setTimeout(loadCoverage, 0);
  }

  snapshotSelect.addEventListener('change', loadCoverage);
  if (factsBody) {
    new MutationObserver(scheduleReload).observe(factsBody, { childList: true });
  }

  window.MoexActualCoverage = { reload: loadCoverage };
  loadCoverage();
})();
