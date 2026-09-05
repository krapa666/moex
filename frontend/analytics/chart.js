(() => {
  const panel = document.querySelector('[data-analytics-chart-panel]');
  const chart = document.querySelector('[data-analytics-chart]');
  const legend = document.querySelector('[data-analytics-chart-legend]');
  if (!panel || !chart || !legend) return;

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const width = 960;
  const height = 320;
  const margin = { top: 22, right: 22, bottom: 46, left: 66 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const dateFormatter = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function svgElement(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
    return element;
  }

  function groupSeries(revisions) {
    const series = new Map();
    revisions.forEach((revision) => {
      const timestamp = Date.parse(revision.created_at || '');
      if (!finite(revision.forecast_price_year1) || !Number.isFinite(timestamp)) return;
      const key = String(revision.table_id);
      if (!series.has(key)) {
        series.set(key, {
          tableId: key,
          analystName: revision.analyst_name || `Таблица ${key}`,
          points: [],
        });
      }
      series.get(key).points.push({
        revisionId: revision.id,
        timestamp,
        value: Number(revision.forecast_price_year1),
        createdAt: revision.created_at,
      });
    });
    return [...series.values()]
      .map((item) => ({ ...item, points: item.points.sort((a, b) => a.timestamp - b.timestamp) }))
      .sort((a, b) => Number(a.tableId) - Number(b.tableId));
  }

  function renderLegend(series) {
    legend.replaceChildren();
    series.forEach((item, index) => {
      const entry = document.createElement('span');
      entry.className = 'analytics-chart-legend-item';
      const swatch = document.createElement('span');
      swatch.className = `analytics-chart-swatch analytics-chart-series-${index % 6}`;
      swatch.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span');
      label.textContent = item.analystName;
      entry.append(swatch, label);
      legend.append(entry);
    });
  }

  function render(revisions) {
    const series = groupSeries(revisions);
    const points = series.flatMap((item) => item.points);
    chart.replaceChildren();
    legend.replaceChildren();

    if (!points.length) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    renderLegend(series);

    const ticker = revisions.find((item) => item?.ticker)?.ticker || 'акции';
    const minTime = Math.min(...points.map((point) => point.timestamp));
    const maxTime = Math.max(...points.map((point) => point.timestamp));
    const rawMin = Math.min(...points.map((point) => point.value));
    const rawMax = Math.max(...points.map((point) => point.value));
    const span = rawMax - rawMin;
    const padding = span > 0 ? span * 0.12 : Math.max(Math.abs(rawMax) * 0.08, 10);
    const minValue = Math.max(0, rawMin - padding);
    const maxValue = rawMax + padding;
    const valueSpan = Math.max(maxValue - minValue, 1);

    const x = (timestamp) => {
      if (maxTime === minTime) return margin.left + plotWidth / 2;
      return margin.left + ((timestamp - minTime) / (maxTime - minTime)) * plotWidth;
    };
    const y = (value) => margin.top + ((maxValue - value) / valueSpan) * plotHeight;

    const svg = svgElement('svg', {
      class: 'analytics-chart-svg',
      viewBox: `0 0 ${width} ${height}`,
      role: 'img',
      'aria-label': `Динамика fair value ${ticker} по ревизиям прогнозов`,
    });
    const title = svgElement('title');
    title.textContent = `Динамика fair value ${ticker}`;
    svg.append(title);

    const yTicks = 5;
    for (let index = 0; index <= yTicks; index += 1) {
      const value = minValue + (valueSpan * index) / yTicks;
      const yPosition = y(value);
      const grid = svgElement('line', {
        class: 'analytics-chart-grid',
        x1: margin.left,
        x2: width - margin.right,
        y1: yPosition,
        y2: yPosition,
      });
      const label = svgElement('text', {
        class: 'analytics-chart-axis-label',
        x: margin.left - 10,
        y: yPosition + 4,
        'text-anchor': 'end',
      });
      label.textContent = `${numberFormatter.format(value)} ₽`;
      svg.append(grid, label);
    }

    const firstDate = svgElement('text', {
      class: 'analytics-chart-axis-label',
      x: margin.left,
      y: height - 14,
      'text-anchor': 'start',
    });
    firstDate.textContent = dateFormatter.format(new Date(minTime));
    const lastDate = svgElement('text', {
      class: 'analytics-chart-axis-label',
      x: width - margin.right,
      y: height - 14,
      'text-anchor': 'end',
    });
    lastDate.textContent = dateFormatter.format(new Date(maxTime));
    svg.append(firstDate, lastDate);

    series.forEach((item, index) => {
      const className = `analytics-chart-series-${index % 6}`;
      if (item.points.length > 1) {
        const pathData = item.points
          .map((point, pointIndex) => `${pointIndex ? 'L' : 'M'} ${x(point.timestamp).toFixed(2)} ${y(point.value).toFixed(2)}`)
          .join(' ');
        svg.append(svgElement('path', {
          class: `analytics-chart-line ${className}`,
          d: pathData,
          'data-chart-series': item.tableId,
        }));
      }

      item.points.forEach((point) => {
        const circle = svgElement('circle', {
          class: `analytics-chart-point ${className}`,
          cx: x(point.timestamp).toFixed(2),
          cy: y(point.value).toFixed(2),
          r: 4.5,
          'data-chart-point': point.revisionId,
          'data-chart-table': item.tableId,
        });
        const tooltip = svgElement('title');
        tooltip.textContent = `${item.analystName}: ${numberFormatter.format(point.value)} ₽ · ${dateFormatter.format(new Date(point.timestamp))}`;
        circle.append(tooltip);
        svg.append(circle);
      });
    });

    chart.append(svg);
  }

  document.addEventListener('moex:analytics-revisions', (event) => {
    render(Array.isArray(event.detail?.revisions) ? event.detail.revisions : []);
  });
})();
