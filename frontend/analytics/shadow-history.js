(() => {
  const currentPanel = document.querySelector('[data-analytics-consensus]');
  const form = document.getElementById('analytics-history-form');
  const tickerInput = document.getElementById('analytics-ticker');
  if (!currentPanel || !form || !tickerInput) return;

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const dateFormatter = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' });
  const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  });
  let panel = null;
  let status = null;
  let empty = null;
  let body = null;
  let summary = null;
  let chart = null;
  let rowsBody = null;
  let reasons = null;
  let requestSeq = 0;

  function finite(value) {
    return value !== null && value !== undefined && Number.isFinite(Number(value));
  }

  function formatPrice(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))} ₽` : '—';
  }

  function formatPercent(value, signed = false) {
    if (!finite(value)) return '—';
    const number = Number(value);
    return `${signed && number > 0 ? '+' : ''}${percentFormatter.format(number)} %`;
  }

  function formatRatio(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))}×` : '—';
  }

  function formatHours(value) {
    if (!finite(value)) return '—';
    const hours = Number(value);
    if (hours >= 48) return `${numberFormatter.format(hours / 24)} дн.`;
    return `${numberFormatter.format(hours)} ч.`;
  }

  function formatDateTime(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.valueOf()) ? dateTimeFormatter.format(date) : '—';
  }

  function reasonLabel(value) {
    const labels = {
      no_history: 'история ещё не накоплена',
      too_few_snapshots: 'меньше трёх snapshot',
      history_too_short: 'история короче 24 часов',
      large_baseline_divergence: 'weighted заметно отклонился от median baseline',
      rapid_divergence_change: 'расхождение быстро изменилось между snapshot',
      weight_concentration: 'весовая концентрация повышена',
      relative_movement_gap: 'weighted и median движутся с заметно разной скоростью',
      training_snapshot_changed: 'сменился исторический training horizon',
    };
    return labels[value] || String(value || '');
  }

  function statusLabel(value) {
    if (value === 'stable') return 'STABLE';
    if (value === 'watch') return 'WATCH';
    if (value === 'alert') return 'ALERT';
    return 'НАКОПЛЕНИЕ';
  }

  function ensurePanel() {
    if (panel) return;
    panel = document.createElement('section');
    panel.className = 'analytics-panel shadow-history-panel';
    panel.dataset.shadowHistory = '';
    panel.hidden = true;
    panel.innerHTML = `
      <header class="analytics-panel-heading">
        <div>
          <span class="analytics-panel-kicker">Forward monitoring</span>
          <h2>Shadow history и drift</h2>
          <p>Forward-only история production median и shadow weighted. Drift здесь — инженерная диагностика расхождения моделей, а не статистический тест и не инвестиционный сигнал.</p>
        </div>
        <span class="analytics-consensus-status" data-shadow-history-status role="status" aria-live="polite">—</span>
      </header>
      <div class="analytics-consensus-empty" data-shadow-history-empty hidden></div>
      <div class="shadow-history-body" data-shadow-history-body hidden>
        <div class="consensus-history-summary" data-shadow-history-summary></div>
        <article class="consensus-history-chart-card">
          <h3>Median vs shadow weighted</h3>
          <p>Линии не соединяются между разными target year. История начинается только после развёртывания v0.18.0.</p>
          <div class="consensus-history-chart" data-shadow-history-chart></div>
          <div class="shadow-history-legend"><span>Median baseline</span><span>Shadow weighted</span></div>
        </article>
        <p class="analytics-consensus-formula" data-shadow-history-reasons></p>
        <div class="source-accuracy-table-wrap">
          <table class="source-accuracy-table">
            <thead><tr><th>Время</th><th>Год</th><th>Median</th><th>Weighted</th><th>Δ</th><th>Max weight</th><th>Training</th></tr></thead>
            <tbody data-shadow-history-rows></tbody>
          </table>
        </div>
      </div>
    `;
    status = panel.querySelector('[data-shadow-history-status]');
    empty = panel.querySelector('[data-shadow-history-empty]');
    body = panel.querySelector('[data-shadow-history-body]');
    summary = panel.querySelector('[data-shadow-history-summary]');
    chart = panel.querySelector('[data-shadow-history-chart]');
    rowsBody = panel.querySelector('[data-shadow-history-rows]');
    reasons = panel.querySelector('[data-shadow-history-reasons]');

    const shadowPanel = document.querySelector('[data-shadow-consensus]');
    (shadowPanel || currentPanel).insertAdjacentElement('afterend', panel);
  }

  function reset() {
    requestSeq += 1;
    ensurePanel();
    panel.hidden = true;
    body.hidden = true;
    empty.hidden = true;
  }

  function renderSummary(drift) {
    const items = [
      ['Drift status', statusLabel(drift.status)],
      ['Snapshot', String(drift.snapshots ?? 0)],
      ['Охват', formatHours(drift.history_span_hours)],
      ['Последняя Δ', formatPercent(drift.latest_delta_percent, true)],
      ['Md |Δ|', formatPercent(drift.median_abs_delta_percent)],
      ['Концентрация', formatRatio(drift.latest_weight_concentration_ratio)],
      ['Δ движения', finite(drift.relative_movement_gap_percentage_points)
        ? `${Number(drift.relative_movement_gap_percentage_points) > 0 ? '+' : ''}${percentFormatter.format(Number(drift.relative_movement_gap_percentage_points))} п.п.`
        : '—'],
    ];
    summary.replaceChildren();
    for (const [label, value] of items) {
      const article = document.createElement('article');
      const span = document.createElement('span');
      const strong = document.createElement('strong');
      span.textContent = label;
      strong.textContent = value;
      article.append(span, strong);
      summary.append(article);
    }
  }

  function svgElement(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
    return element;
  }

  function renderChart(history) {
    chart.replaceChildren();
    if (!history.length) return;
    const latestYear = history[history.length - 1].target_year;
    const points = history
      .filter((item) => item.target_year === latestYear)
      .map((item) => ({
        ...item,
        timestamp: Date.parse(item.captured_at),
      }))
      .filter((item) => Number.isFinite(item.timestamp)
        && finite(item.median_target_price)
        && finite(item.weighted_target_price));
    if (!points.length) return;

    const width = 920;
    const height = 230;
    const margin = { top: 20, right: 20, bottom: 42, left: 68 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const values = points.flatMap((item) => [
      Number(item.median_target_price),
      Number(item.weighted_target_price),
    ]);
    const minTime = Math.min(...points.map((item) => item.timestamp));
    const maxTime = Math.max(...points.map((item) => item.timestamp));
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const padding = rawMax > rawMin ? (rawMax - rawMin) * 0.12 : Math.max(Math.abs(rawMax) * 0.05, 5);
    const minValue = Math.max(0, rawMin - padding);
    const maxValue = rawMax + padding;
    const span = Math.max(maxValue - minValue, 1);
    const x = (time) => maxTime === minTime
      ? margin.left + plotWidth / 2
      : margin.left + ((time - minTime) / (maxTime - minTime)) * plotWidth;
    const y = (value) => margin.top + ((maxValue - value) / span) * plotHeight;

    const svg = svgElement('svg', {
      class: 'consensus-history-svg',
      viewBox: `0 0 ${width} ${height}`,
      role: 'img',
      'aria-label': `Forward shadow history ${points[0].ticker}`,
    });
    for (let index = 0; index <= 4; index += 1) {
      const value = minValue + (span * index) / 4;
      const yPosition = y(value);
      svg.append(svgElement('line', {
        class: 'consensus-history-grid',
        x1: margin.left,
        x2: width - margin.right,
        y1: yPosition,
        y2: yPosition,
      }));
      const label = svgElement('text', {
        class: 'consensus-history-axis-label',
        x: margin.left - 10,
        y: yPosition + 4,
        'text-anchor': 'end',
      });
      label.textContent = formatPrice(value);
      svg.append(label);
    }

    const firstDate = svgElement('text', {
      class: 'consensus-history-axis-label', x: margin.left, y: height - 12, 'text-anchor': 'start',
    });
    firstDate.textContent = dateFormatter.format(new Date(minTime));
    const lastDate = svgElement('text', {
      class: 'consensus-history-axis-label', x: width - margin.right, y: height - 12, 'text-anchor': 'end',
    });
    lastDate.textContent = dateFormatter.format(new Date(maxTime));
    svg.append(firstDate, lastDate);

    const addSeries = (key, className) => {
      if (points.length > 1) {
        const d = points.map((item, index) => `${index ? 'L' : 'M'} ${x(item.timestamp).toFixed(2)} ${y(Number(item[key])).toFixed(2)}`).join(' ');
        svg.append(svgElement('path', { class: `consensus-history-line ${className}`, d }));
      }
      for (const item of points) {
        const circle = svgElement('circle', {
          class: `consensus-history-point ${className}`,
          cx: x(item.timestamp).toFixed(2),
          cy: y(Number(item[key])).toFixed(2),
          r: 4,
        });
        const title = svgElement('title');
        title.textContent = `${formatPrice(item[key])} · ${formatDateTime(item.captured_at)}`;
        circle.append(title);
        svg.append(circle);
      }
    };
    addSeries('median_target_price', 'shadow-history-median');
    addSeries('weighted_target_price', 'shadow-history-weighted');
    chart.append(svg);
  }

  function renderRows(history) {
    rowsBody.replaceChildren();
    for (const item of [...history].reverse().slice(0, 12)) {
      const tr = document.createElement('tr');
      const values = [
        formatDateTime(item.captured_at),
        String(item.target_year),
        formatPrice(item.median_target_price),
        formatPrice(item.weighted_target_price),
        formatPercent(item.weighted_vs_median_target_delta_percent, true),
        formatPercent(item.max_source_weight_percent),
        String(item.training_samples),
      ];
      for (const value of values) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      }
      rowsBody.append(tr);
    }
  }

  function render(history, drift, ticker) {
    ensurePanel();
    panel.hidden = false;
    if (!history.length) {
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = `Для ${ticker} forward shadow history ещё не накоплена. Worker начнёт сохранять snapshot после обновления и далее по расписанию.`;
      status.textContent = 'Истории пока нет';
      return;
    }

    empty.hidden = true;
    body.hidden = false;
    renderSummary(drift);
    renderChart(history);
    renderRows(history);
    const reasonList = Array.isArray(drift.reasons) ? drift.reasons.map(reasonLabel).filter(Boolean) : [];
    reasons.textContent = reasonList.length
      ? `Причины статуса: ${reasonList.join(' · ')}.`
      : 'Пороговых drift-признаков в текущем 30-дневном окне нет.';
    status.textContent = `${statusLabel(drift.status)} · ${history.length} точек`;
    status.dataset.status = drift.status || 'insufficient';
  }

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  async function load(rawTicker) {
    const ticker = String(rawTicker || '').trim().toLocaleUpperCase('ru');
    if (!ticker) {
      reset();
      return;
    }
    ensurePanel();
    const seq = requestSeq + 1;
    requestSeq = seq;
    panel.hidden = false;
    body.hidden = true;
    empty.hidden = true;
    status.textContent = `История ${ticker}…`;
    try {
      const [history, drift] = await Promise.all([
        fetchJson(`/api/analytics/shadow-consensus/history?ticker=${encodeURIComponent(ticker)}&days=90`),
        fetchJson(`/api/analytics/shadow-consensus/drift?ticker=${encodeURIComponent(ticker)}&days=30`),
      ]);
      if (seq !== requestSeq) return;
      render(Array.isArray(history) ? history : [], drift || {}, ticker);
    } catch (_error) {
      if (seq !== requestSeq) return;
      panel.hidden = false;
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = 'Не удалось загрузить forward shadow history. Текущий production consensus от этого не зависит.';
      status.textContent = 'Monitoring недоступен';
    }
  }

  form.addEventListener('submit', () => load(tickerInput.value));
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    load(params.get('ticker') || '');
  });

  const initialTicker = new URLSearchParams(window.location.search).get('ticker') || tickerInput.value;
  if (initialTicker) load(initialTicker);
})();
