(() => {
  const panel = document.querySelector('[data-consensus-history-panel]');
  const status = document.querySelector('[data-consensus-history-status]');
  const empty = document.querySelector('[data-consensus-history-empty]');
  const body = document.querySelector('[data-consensus-history-body]');
  const summary = document.querySelector('[data-consensus-history-summary]');
  const medianChart = document.querySelector('[data-consensus-history-median-chart]');
  const spreadChart = document.querySelector('[data-consensus-history-spread-chart]');
  const list = document.querySelector('[data-consensus-history-list]');
  const form = document.getElementById('analytics-history-form');
  const tickerInput = document.getElementById('analytics-ticker');
  const access = window.MoexAnalyticsAccess;
  if (!panel || !status || !empty || !body || !summary || !medianChart || !spreadChart || !list || !form || !tickerInput || !access) return;

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const chartWidth = 920;
  const chartHeight = 230;
  const margin = { top: 20, right: 20, bottom: 42, left: 68 };
  const plotWidth = chartWidth - margin.left - margin.right;
  const plotHeight = chartHeight - margin.top - margin.bottom;
  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const dateFormatter = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
  const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
  let requestSeq = 0;

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function formatPrice(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))} ₽` : '—';
  }

  function formatPercent(value) {
    return finite(value) ? `${percentFormatter.format(Number(value))} %` : '—';
  }

  function formatDateTime(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.valueOf()) ? dateTimeFormatter.format(date) : '—';
  }

  function median(values) {
    const sorted = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    if (!sorted.length) return null;
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function targetForYear(revision, year) {
    const startYear = Number(revision?.forecast_start_year);
    if (!Number.isFinite(startYear)) return null;
    if (startYear === year && finite(revision.forecast_price_year1)) return Number(revision.forecast_price_year1);
    if (startYear + 1 === year && finite(revision.forecast_price_year2)) return Number(revision.forecast_price_year2);
    return null;
  }

  function sameNumber(left, right) {
    if (left === null && right === null) return true;
    if (!finite(left) || !finite(right)) return false;
    return Math.abs(Number(left) - Number(right)) < 0.000001;
  }

  function sameConsensus(left, right) {
    return Boolean(left && right)
      && left.year === right.year
      && left.targetCount === right.targetCount
      && sameNumber(left.medianTarget, right.medianTarget)
      && sameNumber(left.spreadPercent, right.spreadPercent);
  }

  function reconstructConsensus(revisions, primaryTableId) {
    const ordered = [...revisions]
      .filter((revision) => Number.isFinite(Date.parse(revision?.created_at || '')))
      .sort((left, right) => {
        const timeDelta = Date.parse(left.created_at) - Date.parse(right.created_at);
        return timeDelta || Number(left.id) - Number(right.id);
      });
    const state = new Map();
    const points = [];

    ordered.forEach((revision) => {
      state.set(String(revision.table_id), revision);
      const baseline = state.get(String(primaryTableId));
      const year = Number(baseline?.forecast_start_year);
      if (!Number.isFinite(year)) return;

      const targets = [...state.values()]
        .map((item) => targetForYear(item, year))
        .filter(finite)
        .map(Number)
        .sort((a, b) => a - b);
      if (!targets.length) return;

      const medianTarget = median(targets);
      const minTarget = targets[0];
      const maxTarget = targets[targets.length - 1];
      const spreadPercent = targets.length >= 2 && Number(medianTarget) > 0
        ? ((maxTarget - minTarget) / Number(medianTarget)) * 100
        : null;
      const point = {
        revisionId: revision.id,
        createdAt: revision.created_at,
        timestamp: Date.parse(revision.created_at),
        year,
        medianTarget,
        spreadPercent,
        targetCount: targets.length,
      };

      if (!sameConsensus(points[points.length - 1], point)) points.push(point);
    });

    return points;
  }

  function svgElement(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
    return element;
  }

  function segmentsFor(points, key) {
    const segments = [];
    let current = [];
    points.forEach((point) => {
      if (!finite(point[key])) {
        if (current.length) segments.push(current);
        current = [];
        return;
      }
      if (current.length && current[current.length - 1].year !== point.year) {
        segments.push(current);
        current = [];
      }
      current.push(point);
    });
    if (current.length) segments.push(current);
    return segments;
  }

  function renderChart(container, points, {
    key,
    ariaLabel,
    suffix,
    dataPointAttribute,
  }) {
    container.replaceChildren();
    const validPoints = points.filter((point) => finite(point[key]));
    if (!validPoints.length) {
      const message = document.createElement('p');
      message.className = 'consensus-history-chart-empty';
      message.textContent = key === 'spreadPercent'
        ? 'Для разброса нужны минимум две сопоставимые цели.'
        : 'Недостаточно данных для графика.';
      container.append(message);
      return;
    }

    const minTime = Math.min(...validPoints.map((point) => point.timestamp));
    const maxTime = Math.max(...validPoints.map((point) => point.timestamp));
    const rawMin = Math.min(...validPoints.map((point) => Number(point[key])));
    const rawMax = Math.max(...validPoints.map((point) => Number(point[key])));
    const rawSpan = rawMax - rawMin;
    const padding = rawSpan > 0 ? rawSpan * 0.12 : Math.max(Math.abs(rawMax) * 0.08, key === 'spreadPercent' ? 1 : 10);
    const minValue = key === 'spreadPercent' ? Math.max(0, rawMin - padding) : Math.max(0, rawMin - padding);
    const maxValue = rawMax + padding;
    const valueSpan = Math.max(maxValue - minValue, 1);
    const x = (timestamp) => {
      if (maxTime === minTime) return margin.left + plotWidth / 2;
      return margin.left + ((timestamp - minTime) / (maxTime - minTime)) * plotWidth;
    };
    const y = (value) => margin.top + ((maxValue - value) / valueSpan) * plotHeight;

    const svg = svgElement('svg', {
      class: 'consensus-history-svg',
      viewBox: `0 0 ${chartWidth} ${chartHeight}`,
      role: 'img',
      'aria-label': ariaLabel,
    });
    const title = svgElement('title');
    title.textContent = ariaLabel;
    svg.append(title);

    const yTicks = 4;
    for (let index = 0; index <= yTicks; index += 1) {
      const value = minValue + (valueSpan * index) / yTicks;
      const yPosition = y(value);
      svg.append(svgElement('line', {
        class: 'consensus-history-grid',
        x1: margin.left,
        x2: chartWidth - margin.right,
        y1: yPosition,
        y2: yPosition,
      }));
      const label = svgElement('text', {
        class: 'consensus-history-axis-label',
        x: margin.left - 10,
        y: yPosition + 4,
        'text-anchor': 'end',
      });
      label.textContent = suffix === ' ₽'
        ? `${numberFormatter.format(value)} ₽`
        : `${percentFormatter.format(value)} %`;
      svg.append(label);
    }

    const firstDate = svgElement('text', {
      class: 'consensus-history-axis-label',
      x: margin.left,
      y: chartHeight - 12,
      'text-anchor': 'start',
    });
    firstDate.textContent = dateFormatter.format(new Date(minTime));
    const lastDate = svgElement('text', {
      class: 'consensus-history-axis-label',
      x: chartWidth - margin.right,
      y: chartHeight - 12,
      'text-anchor': 'end',
    });
    lastDate.textContent = dateFormatter.format(new Date(maxTime));
    svg.append(firstDate, lastDate);

    segmentsFor(points, key).forEach((segment) => {
      if (segment.length > 1) {
        const pathData = segment
          .map((point, index) => `${index ? 'L' : 'M'} ${x(point.timestamp).toFixed(2)} ${y(Number(point[key])).toFixed(2)}`)
          .join(' ');
        svg.append(svgElement('path', {
          class: `consensus-history-line consensus-history-${key === 'medianTarget' ? 'median' : 'spread'}`,
          d: pathData,
          'data-consensus-history-series': key,
          'data-consensus-history-year': segment[0].year,
        }));
      }

      segment.forEach((point) => {
        const circle = svgElement('circle', {
          class: `consensus-history-point consensus-history-${key === 'medianTarget' ? 'median' : 'spread'}`,
          cx: x(point.timestamp).toFixed(2),
          cy: y(Number(point[key])).toFixed(2),
          r: 4.5,
          [dataPointAttribute]: point.revisionId,
        });
        const tooltip = svgElement('title');
        const valueText = suffix === ' ₽' ? formatPrice(point[key]) : formatPercent(point[key]);
        tooltip.textContent = `${valueText} · ${point.year} · целей ${point.targetCount} · ${formatDateTime(point.createdAt)}`;
        circle.append(tooltip);
        svg.append(circle);
      });
    });

    container.append(svg);
  }

  function setSummary(name, value) {
    const target = summary.querySelector(`[data-consensus-history-kpi="${name}"]`);
    if (target) target.textContent = value;
  }

  function showEmpty(message) {
    panel.hidden = false;
    body.hidden = true;
    empty.hidden = false;
    empty.textContent = message;
    medianChart.replaceChildren();
    spreadChart.replaceChildren();
    list.replaceChildren();
  }

  function reset() {
    requestSeq += 1;
    panel.hidden = true;
    body.hidden = true;
    empty.hidden = true;
    medianChart.replaceChildren();
    spreadChart.replaceChildren();
    list.replaceChildren();
    status.textContent = '—';
  }

  function render(revisions, primaryTableId, ticker) {
    const points = reconstructConsensus(revisions, primaryTableId);
    if (!points.length) {
      status.textContent = revisions.length ? 'Точек: 0' : 'Ревизий: 0';
      showEmpty(revisions.length
        ? 'В истории пока нет сохранённого состояния основной таблицы, достаточного для восстановления консенсуса.'
        : `Для ${ticker} пока нет сохранённых ревизий прогноза.`);
      return;
    }

    const latest = points[points.length - 1];
    setSummary('points', String(points.length));
    setSummary('median', formatPrice(latest.medianTarget));
    setSummary('spread', formatPercent(latest.spreadPercent));
    setSummary('targets', String(latest.targetCount));

    renderChart(medianChart, points, {
      key: 'medianTarget',
      ariaLabel: `Динамика медианной цели ${ticker} по сохранённым ревизиям`,
      suffix: ' ₽',
      dataPointAttribute: 'data-consensus-history-median-point',
    });
    renderChart(spreadChart, points, {
      key: 'spreadPercent',
      ariaLabel: `Динамика разброса целей ${ticker} по сохранённым ревизиям`,
      suffix: ' %',
      dataPointAttribute: 'data-consensus-history-spread-point',
    });

    list.innerHTML = [...points].reverse().slice(0, 6).map((point) => `
      <article class="consensus-history-row" data-consensus-history-row="${point.revisionId}">
        <time datetime="${escapeHtml(point.createdAt)}">${escapeHtml(formatDateTime(point.createdAt))}</time>
        <strong>${escapeHtml(formatPrice(point.medianTarget))}</strong>
        <span>${point.year} · разброс ${escapeHtml(formatPercent(point.spreadPercent))} · целей ${point.targetCount}</span>
      </article>
    `).join('');

    panel.hidden = false;
    empty.hidden = true;
    body.hidden = false;
    const limitNote = revisions.length >= 500 ? ' · последние 500 ревизий' : '';
    status.textContent = `${latest.year} · точек: ${points.length}${limitNote}`;
  }

  async function load(rawTicker) {
    const ticker = String(rawTicker || '').trim().toLocaleUpperCase('ru');
    if (!ticker) {
      reset();
      return;
    }

    const seq = requestSeq + 1;
    requestSeq = seq;
    panel.hidden = false;
    body.hidden = true;
    empty.hidden = true;
    status.textContent = `Загрузка ${ticker}…`;

    try {
      const accessState = await access.load();
      const primaryTable = accessState.tables.find((table) => Number(table.table_number) === 1);
      if (!primaryTable) throw new Error('Не найдена основная таблица');
      const params = new URLSearchParams({ ticker, limit: '500' });
      const response = await fetch(`/api/analytics/forecast-revisions?${params.toString()}`, {
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
      const revisions = await response.json();
      if (seq !== requestSeq) return;
      render(Array.isArray(revisions) ? revisions : [], primaryTable.id, ticker);
    } catch (_error) {
      if (seq !== requestSeq) return;
      status.textContent = 'Динамика недоступна';
      showEmpty('Не удалось восстановить динамику консенсуса. Текущая оценка и обычная история прогнозов остаются доступными.');
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
