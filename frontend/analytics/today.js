(() => {
  const panel = document.querySelector('[data-analytics-today]');
  const status = document.querySelector('[data-analytics-today-status]');
  const list = document.querySelector('[data-analytics-today-list]');
  const empty = document.querySelector('[data-analytics-today-empty]');
  const access = window.MoexAnalyticsAccess;
  if (!panel || !status || !list || !empty || !access) return;

  const timeFormatter = new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  });
  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function formatNumber(value, suffix = '') {
    return finite(value) ? `${numberFormatter.format(Number(value))}${suffix}` : '—';
  }

  function formatTime(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.valueOf()) ? timeFormatter.format(date) : '—';
  }

  function buildItem(revision) {
    const year = Number(revision.forecast_start_year);
    const profit = revision.net_profit_year_map?.[String(year)];
    const item = document.createElement('a');
    item.className = 'analytics-today-item';
    item.dataset.analyticsTodayRevision = String(revision.id);
    item.href = `/analytics/?${new URLSearchParams({
      ticker: revision.ticker,
      table_id: String(revision.table_id),
    }).toString()}`;

    const heading = document.createElement('div');
    heading.className = 'analytics-today-item-heading';
    const ticker = document.createElement('strong');
    ticker.textContent = revision.ticker;
    const event = document.createElement('span');
    event.textContent = revision.event_type === 'created' ? 'Новый прогноз' : 'Ревизия';
    heading.append(ticker, event);

    const meta = document.createElement('div');
    meta.className = 'analytics-today-item-meta';
    meta.textContent = `${revision.analyst_name} · ${formatTime(revision.created_at)}`;

    const metrics = document.createElement('div');
    metrics.className = 'analytics-today-item-metrics';
    const fair = document.createElement('span');
    fair.textContent = `Fair value ${formatNumber(revision.forecast_price_year1, ' ₽')}`;
    const profitMetric = document.createElement('span');
    profitMetric.textContent = `ЧП ${year}: ${formatNumber(profit, ' млрд ₽')}`;
    metrics.append(fair, profitMetric);

    item.append(heading, meta, metrics);

    const sourceText = String(revision.net_profit_source_comment || '').trim();
    if (sourceText) {
      const source = document.createElement('p');
      source.textContent = sourceText;
      item.append(source);
    }
    return item;
  }

  async function loadToday() {
    const since = new Date();
    since.setHours(0, 0, 0, 0);
    const params = new URLSearchParams({
      since: since.toISOString(),
      limit: '50',
    });

    try {
      await access.load();
      const response = await fetch(`/api/analytics/forecast-revisions?${params.toString()}`);
      if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
      const rawRevisions = await response.json();
      const revisions = access.maskRevisions(rawRevisions);

      list.replaceChildren();
      if (!revisions.length) {
        status.textContent = 'Ревизий сегодня: 0';
        empty.hidden = false;
        list.hidden = true;
        return;
      }

      revisions.forEach((revision) => list.append(buildItem(revision)));
      status.textContent = `Ревизий сегодня: ${revisions.length}`;
      empty.hidden = true;
      list.hidden = false;
    } catch (error) {
      status.textContent = error.message;
      empty.textContent = 'Не удалось загрузить изменения за сегодня.';
      empty.hidden = false;
      list.hidden = true;
    }
  }

  loadToday();
})();
