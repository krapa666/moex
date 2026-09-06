(() => {
  const panel = document.querySelector('[data-source-accuracy]');
  if (!panel) return;

  const snapshotSelect = panel.querySelector('[data-accuracy-snapshot]');
  if (!snapshotSelect) return;

  let status = null;
  let summary = null;
  let yearBody = null;
  let tickerBody = null;
  let parameterBody = null;
  let empty = null;
  let content = null;

  function formatNumber(value, digits = 1) {
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

  function formatDelta(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    const number = Number(value);
    if (Math.abs(number) < 0.05) return '0 п.п.';
    return `${number > 0 ? '+' : ''}${formatNumber(number, 1)} п.п.`;
  }

  function createCell(text, className = '') {
    const td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) {
      let detail = `Ошибка API: ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) detail = String(payload.detail);
      } catch (_error) {
        // Keep the HTTP status fallback.
      }
      throw new Error(detail);
    }
    return response.json();
  }

  function tableWithBody(headers, bodyAttribute) {
    const wrap = document.createElement('div');
    wrap.className = 'source-accuracy-table-wrap';
    const table = document.createElement('table');
    table.className = 'source-accuracy-table';
    const thead = document.createElement('thead');
    const tr = document.createElement('tr');
    for (const header of headers) {
      const th = document.createElement('th');
      th.textContent = header;
      tr.append(th);
    }
    thead.append(tr);
    const tbody = document.createElement('tbody');
    tbody.dataset[bodyAttribute] = '';
    table.append(thead, tbody);
    wrap.append(table);
    return { wrap, tbody };
  }

  function ensureSection() {
    if (content) return;

    const section = document.createElement('div');
    section.className = 'actual-facts consensus-robustness';
    section.dataset.consensusRobustness = '';

    const heading = document.createElement('div');
    heading.className = 'source-accuracy-controls';
    const titleWrap = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = 'Устойчивость weighted backtest';
    const description = document.createElement('p');
    description.textContent = 'Проверка по годам, тикерам, leave-one-out и 27 наборам параметров. Положительная Δ означает меньшую sMAPE, чем у медианы. Это диагностика, а не переключатель боевого consensus.';
    titleWrap.append(title, description);

    status = document.createElement('span');
    status.className = 'analytics-status';
    status.dataset.consensusRobustnessStatus = '';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.textContent = 'Расчёт…';
    heading.append(titleWrap, status);

    empty = document.createElement('div');
    empty.className = 'source-accuracy-empty';
    empty.dataset.consensusRobustnessEmpty = '';
    empty.hidden = true;

    content = document.createElement('div');
    content.dataset.consensusRobustnessContent = '';

    summary = document.createElement('p');
    summary.dataset.consensusRobustnessSummary = '';
    content.append(summary);

    const yearTitle = document.createElement('h4');
    yearTitle.textContent = 'По годам';
    const yearTable = tableWithBody(
      ['Год', 'Набл.', 'Md медианы', 'Md weighted', 'Δ Md', 'Δ Mean'],
      'consensusRobustnessYearBody',
    );
    yearBody = yearTable.tbody;
    content.append(yearTitle, yearTable.wrap);

    const tickerDetails = document.createElement('details');
    tickerDetails.open = true;
    tickerDetails.dataset.consensusRobustnessTickerDetails = '';
    const tickerSummary = document.createElement('summary');
    tickerSummary.textContent = 'По тикерам — слабые результаты сверху';
    const tickerTable = tableWithBody(
      ['Тикер', 'Набл.', 'Md медианы', 'Md weighted', 'Δ Md', 'Δ Mean'],
      'consensusRobustnessTickerBody',
    );
    tickerBody = tickerTable.tbody;
    tickerDetails.append(tickerSummary, tickerTable.wrap);
    content.append(tickerDetails);

    const parameterDetails = document.createElement('details');
    parameterDetails.dataset.consensusRobustnessParameterDetails = '';
    const parameterSummary = document.createElement('summary');
    parameterSummary.textContent = 'Чувствительность к параметрам weighting — 27 комбинаций';
    const parameterTable = tableWithBody(
      ['Shrinkage', 'Floor', 'Cap', 'Набл.', 'Md weighted', 'Δ Md', 'Δ Mean'],
      'consensusRobustnessParameterBody',
    );
    parameterBody = parameterTable.tbody;
    parameterDetails.append(parameterSummary, parameterTable.wrap);
    content.append(parameterDetails);

    section.append(heading, empty, content);
    panel.append(section);
  }

  function renderSliceRows(body, rows, keyLabel) {
    body.replaceChildren();
    for (const row of rows) {
      const tr = document.createElement('tr');
      if (Number(row.weighted_median_delta_pp) < 0) tr.classList.add('accuracy-row-unranked');
      tr.append(
        createCell(String(row[keyLabel] ?? '—'), 'accuracy-source'),
        createCell(String(row.observations ?? '—')),
        createCell(formatPercent(row.baseline_median_smape_percent)),
        createCell(formatPercent(row.weighted_median_smape_percent)),
        createCell(formatDelta(row.weighted_median_delta_pp)),
        createCell(formatDelta(row.weighted_mean_delta_pp)),
      );
      body.append(tr);
    }
  }

  function renderParameterRows(rows) {
    parameterBody.replaceChildren();
    const sorted = [...rows].sort(
      (a, b) => Number(a.weighted_median_delta_pp) - Number(b.weighted_median_delta_pp),
    );
    for (const row of sorted) {
      const tr = document.createElement('tr');
      if (Number(row.weighted_median_delta_pp) < 0) tr.classList.add('accuracy-row-unranked');
      tr.append(
        createCell(String(row.shrinkage_samples)),
        createCell(formatPercent(row.error_floor_percent)),
        createCell(formatNumber(row.relative_score_cap, 1)),
        createCell(String(row.observations)),
        createCell(formatPercent(row.weighted_median_smape_percent)),
        createCell(formatDelta(row.weighted_median_delta_pp)),
        createCell(formatDelta(row.weighted_mean_delta_pp)),
      );
      parameterBody.append(tr);
    }
  }

  function render(result) {
    ensureSection();
    const observations = Number(result?.observations || 0);
    if (!observations) {
      empty.hidden = false;
      content.hidden = true;
      empty.textContent = 'Недостаточно исторических наблюдений для robustness-проверки.';
      status.textContent = 'Недостаточно истории';
      return;
    }

    empty.hidden = true;
    content.hidden = false;
    const yearRows = Array.isArray(result.by_year) ? result.by_year : [];
    const tickerRows = Array.isArray(result.by_ticker) ? result.by_ticker : [];
    const parameterRows = Array.isArray(result.parameter_sweep) ? result.parameter_sweep : [];

    const tickerJackknife = `${result.ticker_jackknife_preserved}/${result.ticker_jackknife_cases}`;
    const yearJackknife = `${result.year_jackknife_preserved}/${result.year_jackknife_cases}`;
    summary.textContent = [
      `Общий Δ Md: ${formatDelta(result.weighted_median_delta_pp)}`,
      `по тикерам: ${result.positive_ticker_slices}/${result.ticker_slices}`,
      `по годам: ${result.positive_year_slices}/${result.year_slices}`,
      `leave-one-ticker-out: ${tickerJackknife}`,
      `leave-one-year-out: ${yearJackknife}`,
      `параметры: ${result.positive_parameter_cases}/${result.parameter_cases}`,
      `диапазон Δ Md: ${formatDelta(result.parameter_min_median_delta_pp)} … ${formatDelta(result.parameter_max_median_delta_pp)}`,
    ].join(' · ');

    renderSliceRows(yearBody, yearRows, 'key');
    renderSliceRows(
      tickerBody,
      [...tickerRows].sort(
        (a, b) => Number(a.weighted_median_delta_pp) - Number(b.weighted_median_delta_pp),
      ),
      'key',
    );
    renderParameterRows(parameterRows);
    status.textContent = `${observations} наблюдений · ${result.tickers} бумаг · ${result.years} лет`;
  }

  async function load() {
    ensureSection();
    status.textContent = 'Расчёт…';
    const snapshot = snapshotSelect.value || 'pre_year';
    try {
      const result = await fetchJson(
        `/api/analytics/consensus-backtest/robustness?snapshot=${encodeURIComponent(snapshot)}`,
      );
      render(result || {});
    } catch (error) {
      empty.hidden = false;
      content.hidden = true;
      empty.textContent = error.message;
      status.textContent = 'Ошибка';
    }
  }

  ensureSection();
  snapshotSelect.addEventListener('change', load);
  load();
})();
