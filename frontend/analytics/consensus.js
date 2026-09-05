(() => {
  const panel = document.querySelector('[data-analytics-consensus]');
  const status = document.querySelector('[data-analytics-consensus-status]');
  const empty = document.querySelector('[data-analytics-consensus-empty]');
  const body = document.querySelector('[data-analytics-consensus-body]');
  const form = document.getElementById('analytics-history-form');
  const tickerInput = document.getElementById('analytics-ticker');
  const tableSelect = document.getElementById('analytics-table');
  if (!panel || !status || !empty || !body || !form || !tickerInput || !tableSelect) return;

  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  let requestSeq = 0;

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

  function formatPrice(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))} ₽` : '—';
  }

  function formatPercent(value) {
    return finite(value) ? `${percentFormatter.format(Number(value))} %` : '—';
  }

  function median(values) {
    const numbers = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    if (!numbers.length) return null;
    const middle = Math.floor(numbers.length / 2);
    return numbers.length % 2 ? numbers[middle] : (numbers[middle - 1] + numbers[middle]) / 2;
  }

  function position(value, minValue, maxValue) {
    if (Math.abs(maxValue - minValue) < 0.000001) return 50;
    return Math.max(0, Math.min(100, ((value - minValue) / (maxValue - minValue)) * 100));
  }

  function agreementSummary(values, medianValue) {
    if (values.length < 2 || !finite(medianValue) || Number(medianValue) <= 0) {
      return {
        spreadPercent: null,
        label: 'Недостаточно данных',
        className: 'insufficient',
      };
    }

    const minValue = values[0];
    const maxValue = values[values.length - 1];
    const spreadPercent = ((maxValue - minValue) / Number(medianValue)) * 100;
    if (spreadPercent <= 10) {
      return { spreadPercent, label: 'Высокая', className: 'high' };
    }
    if (spreadPercent <= 25) {
      return { spreadPercent, label: 'Средняя', className: 'medium' };
    }
    return { spreadPercent, label: 'Низкая', className: 'low' };
  }

  function resetConsensus() {
    requestSeq += 1;
    panel.hidden = true;
    empty.hidden = true;
    body.hidden = true;
    body.innerHTML = '';
    status.textContent = '—';
  }

  function renderEmpty(ticker, year, totalItems) {
    panel.hidden = false;
    body.hidden = true;
    body.innerHTML = '';
    empty.hidden = false;
    empty.textContent = year
      ? `Для ${ticker} нет сопоставимых целевых цен на ${year} год.`
      : `Для ${ticker} нет текущих целевых цен аналитиков.`;
    status.textContent = totalItems ? 'Сопоставимых целей: 0' : 'Целей: 0';
  }

  function renderConsensus(items, ticker) {
    const ordered = [...items].sort((a, b) => Number(a.table_number) - Number(b.table_number));
    const baseline = ordered.find((item) => Number(item.table_number) === 1) || ordered[0];
    const year = Number(baseline?.forecast_start_year);
    if (!Number.isFinite(year)) {
      renderEmpty(ticker, null, ordered.length);
      return;
    }

    const targets = ordered.map((item) => {
      const yearData = (item.years || []).find((entry) => Number(entry.year) === year);
      if (!yearData || !finite(yearData.forecast_price)) return null;
      return {
        tableId: item.table_id,
        tableNumber: item.table_number,
        analystName: item.analyst_name,
        value: Number(yearData.forecast_price),
      };
    }).filter(Boolean);

    if (!targets.length) {
      renderEmpty(ticker, year, ordered.length);
      return;
    }

    const values = targets.map((item) => item.value).sort((a, b) => a - b);
    const minValue = values[0];
    const maxValue = values[values.length - 1];
    const medianValue = median(values);
    const currentPrice = median(ordered.map((item) => item.current_price).filter(finite));
    const agreement = agreementSummary(values, medianValue);
    const medianPosition = position(medianValue, minValue, maxValue);
    const rangeLabel = `Диапазон целей ${ticker} на ${year}: минимум ${formatPrice(minValue)}, медиана ${formatPrice(medianValue)}, максимум ${formatPrice(maxValue)}`;

    const markers = targets.map((target) => (
      `<span class="analytics-consensus-marker" style="left:${position(target.value, minValue, maxValue)}%" title="${escapeHtml(target.analystName)}: ${escapeHtml(formatPrice(target.value))}" aria-hidden="true"></span>`
    )).join('');

    const targetRows = [...targets]
      .sort((a, b) => b.value - a.value || Number(a.tableNumber) - Number(b.tableNumber))
      .map((target) => `
        <div class="analytics-consensus-target" data-consensus-target="${target.tableId}">
          <span>${escapeHtml(target.analystName)} · таблица ${target.tableNumber}</span>
          <strong>${escapeHtml(formatPrice(target.value))}</strong>
        </div>
      `).join('');

    const agreementNote = agreement.spreadPercent === null
      ? 'Для оценки согласованности нужны минимум две сопоставимые цели.'
      : 'Разброс = (максимум − минимум) / медиана. ≤10% — высокая, >10–25% — средняя, >25% — низкая согласованность.';

    body.innerHTML = `
      <div class="analytics-consensus-kpis" aria-label="Сводка консенсуса ${escapeHtml(ticker)}">
        <article><span>Минимум</span><strong data-consensus-kpi="min">${formatPrice(minValue)}</strong></article>
        <article><span>Медиана</span><strong data-consensus-kpi="median">${formatPrice(medianValue)}</strong></article>
        <article><span>Максимум</span><strong data-consensus-kpi="max">${formatPrice(maxValue)}</strong></article>
        <article><span>Рынок</span><strong data-consensus-kpi="market">${formatPrice(currentPrice)}</strong></article>
        <article><span>Разброс</span><strong data-consensus-kpi="spread">${formatPercent(agreement.spreadPercent)}</strong></article>
        <article><span>Согласованность</span><strong class="analytics-consensus-agreement ${agreement.className}" data-consensus-kpi="agreement">${escapeHtml(agreement.label)}</strong></article>
      </div>
      <p class="analytics-consensus-formula">${escapeHtml(agreementNote)}</p>
      <div class="analytics-consensus-range" role="img" aria-label="${escapeHtml(rangeLabel)}">
        <div class="analytics-consensus-track">
          ${markers}
          <span class="analytics-consensus-median" style="left:${medianPosition}%" aria-hidden="true"></span>
        </div>
        <div class="analytics-consensus-axis" aria-hidden="true">
          <span>${formatPrice(minValue)}</span>
          <span>медиана ${formatPrice(medianValue)}</span>
          <span>${formatPrice(maxValue)}</span>
        </div>
      </div>
      <div class="analytics-consensus-targets" aria-label="Целевые цены аналитиков">
        ${targetRows}
      </div>
    `;

    panel.hidden = false;
    empty.hidden = true;
    body.hidden = false;
    status.textContent = `${year} · целей: ${targets.length}/${ordered.length}`;
  }

  async function loadConsensus(rawTicker) {
    const ticker = String(rawTicker || '').trim().toLocaleUpperCase('ru');
    if (!ticker) {
      resetConsensus();
      return;
    }

    const seq = requestSeq + 1;
    requestSeq = seq;
    panel.hidden = false;
    empty.hidden = true;
    body.hidden = true;
    body.innerHTML = '';
    status.textContent = `Загрузка ${ticker}…`;

    try {
      const response = await fetch(`/api/ticker-comparison?ticker=${encodeURIComponent(ticker)}`, {
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
      const items = await response.json();
      if (seq !== requestSeq) return;
      renderConsensus(Array.isArray(items) ? items : [], ticker);
    } catch (_error) {
      if (seq !== requestSeq) return;
      panel.hidden = false;
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = 'Не удалось загрузить текущий консенсус. История прогнозов остаётся доступна.';
      status.textContent = 'Консенсус недоступен';
    }
  }

  form.addEventListener('submit', () => loadConsensus(tickerInput.value));
  tableSelect.addEventListener('change', () => {
    if (tickerInput.value.trim()) loadConsensus(tickerInput.value);
  });
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    loadConsensus(params.get('ticker') || '');
  });

  const initialTicker = new URLSearchParams(window.location.search).get('ticker') || tickerInput.value;
  if (initialTicker) loadConsensus(initialTicker);
})();
