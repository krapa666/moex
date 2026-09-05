(() => {
  const body = document.getElementById('watchlist-body');
  const tableWrap = document.querySelector('[data-watchlist-table]');
  const empty = document.querySelector('[data-watchlist-empty]');
  const filterEmpty = document.querySelector('[data-watchlist-filter-empty]');
  const status = document.getElementById('watchlist-status');
  const searchInput = document.getElementById('watchlist-search');
  const filterSelect = document.getElementById('watchlist-filter');
  const sortButtons = [...document.querySelectorAll('[data-watchlist-sort]')];
  if (!body || !tableWrap || !empty || !filterEmpty || !status || !searchInput || !filterSelect) return;

  const viewState = {
    total: 0,
    matchedVolumes: 0,
    volumeAvailable: true,
  };
  const sortState = {
    field: 'ticker',
    direction: 'asc',
  };

  const priceFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const ratioFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
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

  function dataNumber(value) {
    return isFiniteValue(value) ? String(Number(value)) : '';
  }

  function formatPrice(value) {
    return isFiniteValue(value) ? priceFormatter.format(Number(value)) : '—';
  }

  function formatPercent(value) {
    return isFiniteValue(value) ? `${percentFormatter.format(Number(value))} %` : '—';
  }

  function dividendYield(row, year) {
    const dividendMap = row.dividend_year_map || {};
    const dividend = dividendMap[String(year)] ?? row.dividends_year1;
    if (!isFiniteValue(dividend) || !isFiniteValue(row.current_price) || Number(row.current_price) <= 0) {
      return null;
    }
    return (Number(dividend) / Number(row.current_price)) * 100;
  }

  function signalLabel(statusValue) {
    return {
      signal: 'Сигнал',
      above_range: 'Выше диапазона',
      normal: 'Обычно',
      insufficient: 'Мало истории',
    }[statusValue] || 'Нет данных';
  }

  function signalClass(statusValue) {
    if (statusValue === 'signal') return 'watchlist-signal watchlist-signal-active';
    if (statusValue === 'above_range') return 'watchlist-signal watchlist-signal-high';
    if (statusValue === 'normal') return 'watchlist-signal watchlist-signal-normal';
    return 'watchlist-signal';
  }

  function upsideClass(value) {
    if (!isFiniteValue(value)) return 'watchlist-value-muted';
    const number = Number(value);
    if (number > 0) return 'watchlist-value-positive';
    if (number < 0) return 'watchlist-value-negative';
    return 'watchlist-value-muted';
  }

  function setControlsEnabled(enabled) {
    searchInput.disabled = !enabled;
    filterSelect.disabled = !enabled;
    sortButtons.forEach((button) => {
      button.disabled = !enabled;
    });
  }

  function showEmpty(title, message, state = 'empty') {
    setControlsEnabled(false);
    tableWrap.hidden = true;
    filterEmpty.hidden = true;
    body.innerHTML = '';
    empty.hidden = false;
    empty.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
    status.textContent = state === 'error' ? 'Ошибка загрузки' : 'Нет бумаг';
    status.dataset.state = state;
  }

  function rowMatches(row) {
    const query = searchInput.value.trim().toLocaleUpperCase('ru');
    const ticker = row.dataset.watchlistTicker || '';
    if (query && !ticker.includes(query)) return false;

    const filter = filterSelect.value;
    const signal = row.dataset.watchlistSignal || '';
    const upsideRaw = row.dataset.watchlistUpside;
    const upside = upsideRaw === '' || upsideRaw == null ? null : Number(upsideRaw);

    if (filter === 'signals') return ['signal', 'above_range'].includes(signal);
    if (filter === 'positive') return Number.isFinite(upside) && upside > 0;
    if (filter === 'negative') return Number.isFinite(upside) && upside < 0;
    return true;
  }

  function updateStatus(visibleCount) {
    const filtered = visibleCount !== viewState.total || searchInput.value.trim() || filterSelect.value !== 'all';
    const prefix = filtered ? `Показано: ${visibleCount} из ${viewState.total}` : `Бумаги: ${viewState.total}`;
    status.textContent = viewState.volumeAvailable
      ? `${prefix} · объёмы: ${viewState.matchedVolumes}`
      : `${prefix} · объёмы недоступны`;
    status.dataset.state = viewState.volumeAvailable && viewState.matchedVolumes === viewState.total
      ? 'complete'
      : 'partial';
  }

  function applyFilters() {
    if (!viewState.total) return;
    let visibleCount = 0;
    [...body.querySelectorAll(':scope > tr')].forEach((row) => {
      const matches = rowMatches(row);
      row.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    filterEmpty.hidden = visibleCount !== 0;
    updateStatus(visibleCount);
  }

  function sortRawValue(row, field) {
    if (field === 'ticker') return row.dataset.watchlistTicker || '';
    const datasetKey = {
      current: 'watchlistCurrent',
      fair: 'watchlistFair',
      upside: 'watchlistUpside',
      dividend: 'watchlistDividend',
      ratio: 'watchlistRatio',
    }[field];
    const raw = datasetKey ? row.dataset[datasetKey] : '';
    return raw === '' || raw == null ? null : Number(raw);
  }

  function compareRows(left, right) {
    if (sortState.field === 'ticker') {
      const result = sortRawValue(left, 'ticker').localeCompare(sortRawValue(right, 'ticker'), 'ru');
      return sortState.direction === 'asc' ? result : -result;
    }

    const leftValue = sortRawValue(left, sortState.field);
    const rightValue = sortRawValue(right, sortState.field);
    const leftMissing = !Number.isFinite(leftValue);
    const rightMissing = !Number.isFinite(rightValue);
    if (leftMissing && rightMissing) {
      return (left.dataset.watchlistTicker || '').localeCompare(right.dataset.watchlistTicker || '', 'ru');
    }
    if (leftMissing) return 1;
    if (rightMissing) return -1;

    const result = leftValue - rightValue;
    if (result !== 0) return sortState.direction === 'asc' ? result : -result;
    return (left.dataset.watchlistTicker || '').localeCompare(right.dataset.watchlistTicker || '', 'ru');
  }

  function updateSortIndicators() {
    sortButtons.forEach((button) => {
      const active = button.dataset.watchlistSort === sortState.field;
      const indicator = button.querySelector('[data-sort-indicator]');
      if (indicator) indicator.textContent = active ? (sortState.direction === 'asc' ? '↑' : '↓') : '⇅';
      const header = button.closest('th');
      if (!header) return;
      if (active) header.setAttribute('aria-sort', sortState.direction === 'asc' ? 'ascending' : 'descending');
      else header.removeAttribute('aria-sort');
    });
  }

  function sortRows() {
    const rows = [...body.querySelectorAll(':scope > tr')].sort(compareRows);
    rows.forEach((row) => body.appendChild(row));
    updateSortIndicators();
  }

  function changeSort(field) {
    if (sortState.field === field) {
      sortState.direction = sortState.direction === 'asc' ? 'desc' : 'asc';
    } else {
      sortState.field = field;
      sortState.direction = field === 'ticker' ? 'asc' : 'desc';
    }
    sortRows();
    applyFilters();
  }

  function render(rows, volumeRows, primaryTable, { volumeAvailable = true } = {}) {
    if (!rows.length) {
      showEmpty('Основная таблица оценок пуста', 'Добавьте бумаги в таблицу №1 — они появятся здесь автоматически.');
      return;
    }

    const volumeMap = new Map(
      (volumeRows || []).map((item) => [String(item.ticker || '').toLocaleUpperCase('ru'), item]),
    );
    const year = Number(primaryTable.forecast_start_year) || new Date().getFullYear();
    let matchedVolumes = 0;

    body.innerHTML = rows.map((row) => {
      const ticker = String(row.ticker || '').trim().toLocaleUpperCase('ru');
      const volume = volumeMap.get(ticker) || null;
      if (volume) matchedVolumes += 1;
      const latest = volume?.latest || null;
      const ratio = latest?.ratio;
      const yieldPercent = dividendYield(row, year);
      const signalStatus = latest?.signal_status || '';

      return `
        <tr
          data-watchlist-ticker="${escapeHtml(ticker)}"
          data-watchlist-current="${escapeHtml(dataNumber(row.current_price))}"
          data-watchlist-fair="${escapeHtml(dataNumber(row.forecast_price_year1))}"
          data-watchlist-upside="${escapeHtml(dataNumber(row.upside_percent_year1))}"
          data-watchlist-dividend="${escapeHtml(dataNumber(yieldPercent))}"
          data-watchlist-ratio="${escapeHtml(dataNumber(ratio))}"
          data-watchlist-signal="${escapeHtml(signalStatus)}"
        >
          <td>
            <a class="watchlist-ticker-link" href="/?ticker=${encodeURIComponent(ticker)}">${escapeHtml(ticker || '—')}</a>
          </td>
          <td class="watchlist-number">${formatPrice(row.current_price)}</td>
          <td class="watchlist-number">${formatPrice(row.forecast_price_year1)}</td>
          <td class="watchlist-number ${upsideClass(row.upside_percent_year1)}">${formatPercent(row.upside_percent_year1)}</td>
          <td class="watchlist-number">${formatPercent(yieldPercent)}</td>
          <td class="watchlist-number">
            ${isFiniteValue(ratio)
              ? `<a class="watchlist-volume-link" href="/volumes/?ticker=${encodeURIComponent(ticker)}">${ratioFormatter.format(Number(ratio))}×</a>`
              : '—'}
          </td>
          <td><span class="${signalClass(signalStatus)}">${signalLabel(signalStatus)}</span></td>
        </tr>
      `;
    }).join('');

    viewState.total = rows.length;
    viewState.matchedVolumes = matchedVolumes;
    viewState.volumeAvailable = volumeAvailable;
    empty.hidden = true;
    tableWrap.hidden = false;
    setControlsEnabled(true);
    sortRows();
    applyFilters();
  }

  async function load() {
    status.textContent = 'Загрузка…';
    delete status.dataset.state;

    try {
      const tables = await api('/api/tables');
      const primaryTable = tables.find((table) => Number(table.table_number) === 1) || tables[0];
      if (!primaryTable) {
        showEmpty('Нет таблиц оценок', 'Создайте основную таблицу оценок, чтобы сформировать Watchlist.');
        return;
      }

      const [rowsResult, volumesResult] = await Promise.allSettled([
        api(`/api/rows?table_id=${encodeURIComponent(primaryTable.id)}`),
        api('/api/volume/overview'),
      ]);

      if (rowsResult.status !== 'fulfilled') {
        showEmpty('Не удалось загрузить оценки', 'Watchlist требует доступ к основной таблице оценок.', 'error');
        return;
      }

      const volumeAvailable = volumesResult.status === 'fulfilled';
      const volumeRows = volumeAvailable ? volumesResult.value : [];
      render(rowsResult.value, volumeRows, primaryTable, { volumeAvailable });
    } catch (_error) {
      showEmpty('Не удалось загрузить Watchlist', 'Проверьте доступность API и повторите загрузку страницы.', 'error');
    }
  }

  searchInput.addEventListener('input', applyFilters);
  filterSelect.addEventListener('change', applyFilters);
  sortButtons.forEach((button) => {
    button.addEventListener('click', () => changeSort(button.dataset.watchlistSort));
  });
  load();
})();
