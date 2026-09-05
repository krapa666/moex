(() => {
  const kpi = (name) => document.querySelector(`[data-dashboard-kpi="${name}"]`);
  const list = (name) => document.querySelector(`[data-dashboard-list="${name}"]`);
  const empty = (name) => document.querySelector(`[data-dashboard-empty="${name}"]`);

  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
  const priceFormatter = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 2,
  });
  const ratioFormatter = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
  const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  });
  const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
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

  function isFiniteValue(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function finiteNumbers(values) {
    return values
      .filter(isFiniteValue)
      .map(Number)
      .sort((a, b) => a - b);
  }

  function median(values) {
    const numbers = finiteNumbers(values);
    if (!numbers.length) return null;
    const middle = Math.floor(numbers.length / 2);
    return numbers.length % 2
      ? numbers[middle]
      : (numbers[middle - 1] + numbers[middle]) / 2;
  }

  function setKpi(name, value, fallback = '—') {
    const element = kpi(name);
    if (element) element.textContent = value ?? fallback;
  }

  function setEmptyState(name, message) {
    const listElement = list(name);
    const emptyElement = empty(name);
    if (listElement) {
      listElement.hidden = true;
      listElement.innerHTML = '';
    }
    if (emptyElement) {
      emptyElement.hidden = false;
      emptyElement.textContent = message;
    }
  }

  function showList(name, html) {
    const listElement = list(name);
    const emptyElement = empty(name);
    if (!listElement) return;
    listElement.innerHTML = html;
    listElement.hidden = false;
    if (emptyElement) emptyElement.hidden = true;
  }

  function formatPrice(value) {
    return isFiniteValue(value) ? `${priceFormatter.format(Number(value))} ₽` : '—';
  }

  function formatTradeDate(value) {
    if (!value) return '—';
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(date.valueOf()) ? escapeHtml(value) : dateFormatter.format(date);
  }

  function renderOpportunities(rows) {
    const leaders = rows
      .filter((row) => isFiniteValue(row.upside_percent_year1))
      .sort((a, b) => Number(b.upside_percent_year1) - Number(a.upside_percent_year1))
      .slice(0, 5);

    if (!leaders.length) {
      setEmptyState('opportunities', 'Нет бумаг с рассчитанным потенциалом на ближайший прогнозный год.');
      return;
    }

    showList(
      'opportunities',
      leaders.map((row, index) => {
        const upside = Number(row.upside_percent_year1);
        const upsideClass = upside >= 0 ? 'dashboard-upside-positive' : 'dashboard-upside-negative';
        const ticker = row.ticker || '';
        return `
          <a class="dashboard-list-row dashboard-list-link" href="/?ticker=${encodeURIComponent(ticker)}" data-dashboard-opportunity="${escapeHtml(ticker)}" aria-label="Открыть оценку ${escapeHtml(ticker)}">
            <div class="dashboard-list-rank">${index + 1}</div>
            <div class="dashboard-list-main">
              <strong class="dashboard-list-ticker">${escapeHtml(ticker || '—')}</strong>
              <span class="dashboard-list-name">Текущая ${formatPrice(row.current_price)} · цель ${formatPrice(row.forecast_price_year1)}</span>
            </div>
            <div class="dashboard-list-metrics">
              <span class="dashboard-metric-label">Потенциал</span>
              <strong class="${upsideClass}">${percentFormatter.format(upside)} %</strong>
            </div>
          </a>
        `;
      }).join(''),
    );
  }

  function volumeStatus(status) {
    if (status === 'signal') return { label: 'Сигнал', className: 'dashboard-volume-signal' };
    if (status === 'above_range') return { label: 'Выше диапазона', className: 'dashboard-volume-above' };
    return { label: status || '—', className: '' };
  }

  function renderVolumeHighlights(rows) {
    const anomalies = rows
      .filter((row) => ['signal', 'above_range'].includes(row.latest?.signal_status))
      .filter((row) => isFiniteValue(row.latest?.ratio))
      .sort((a, b) => Number(b.latest.ratio) - Number(a.latest.ratio))
      .slice(0, 5);

    if (!anomalies.length) {
      setEmptyState('volumes', 'Аномалий торгового объёма в последней доступной сессии нет.');
      return;
    }

    showList(
      'volumes',
      anomalies.map((row, index) => {
        const status = volumeStatus(row.latest.signal_status);
        const ticker = row.ticker || '';
        return `
          <a class="dashboard-list-row dashboard-list-link" href="/volumes/?ticker=${encodeURIComponent(ticker)}" data-dashboard-volume="${escapeHtml(ticker)}" aria-label="Открыть историю объёмов ${escapeHtml(ticker)}">
            <div class="dashboard-list-rank">${index + 1}</div>
            <div class="dashboard-list-main">
              <strong class="dashboard-list-ticker">${escapeHtml(ticker || '—')}</strong>
              <span class="dashboard-list-name">${escapeHtml(row.short_name || '')}${row.latest?.trade_date ? ` · ${formatTradeDate(row.latest.trade_date)}` : ''}</span>
            </div>
            <div class="dashboard-list-metrics dashboard-volume-metrics">
              <strong>${ratioFormatter.format(Number(row.latest.ratio))}×</strong>
              <span class="dashboard-volume-status ${status.className}">${status.label}</span>
            </div>
          </a>
        `;
      }).join(''),
    );
  }

  async function loadValuationData() {
    try {
      const tables = await api('/api/tables');
      const primaryTable = tables.find((table) => Number(table.table_number) === 1) || tables[0];
      if (!primaryTable) {
        setKpi('securities', '0');
        setKpi('median-upside', '—');
        setEmptyState('opportunities', 'Основная таблица оценок пока пуста.');
        return;
      }

      const rows = await api(`/api/rows?table_id=${encodeURIComponent(primaryTable.id)}`);
      setKpi('securities', String(rows.length));

      const medianUpside = median(rows.map((row) => row.upside_percent_year1));
      setKpi(
        'median-upside',
        medianUpside == null ? '—' : `${percentFormatter.format(medianUpside)} %`,
      );
      renderOpportunities(rows);
    } catch (_error) {
      setKpi('securities', '—');
      setKpi('median-upside', '—');
      setEmptyState('opportunities', 'Не удалось загрузить данные оценок.');
    }
  }

  async function loadVolumeData() {
    const [overviewResult, runResult] = await Promise.allSettled([
      api('/api/volume/overview'),
      api('/api/volume/runs/latest'),
    ]);

    if (overviewResult.status === 'fulfilled') {
      const rows = overviewResult.value;
      const signals = rows.filter(
        (row) => row.latest?.signal_status === 'signal',
      ).length;
      setKpi('volume-signals', String(signals));
      renderVolumeHighlights(rows);
    } else {
      setKpi('volume-signals', '—');
      setEmptyState('volumes', 'Не удалось загрузить мониторинг торговых объёмов.');
    }

    if (runResult.status === 'fulfilled' && runResult.value) {
      const rawDate = runResult.value.finished_at || runResult.value.started_at;
      const date = rawDate ? new Date(rawDate) : null;
      setKpi(
        'last-volume-run',
        date && !Number.isNaN(date.valueOf()) ? dateTimeFormatter.format(date) : '—',
      );
    } else {
      setKpi('last-volume-run', '—');
    }
  }

  Promise.allSettled([loadValuationData(), loadVolumeData()]);
})();
