(() => {
  const body = document.getElementById('watchlist-body');
  const tableWrap = document.querySelector('[data-watchlist-table]');
  const empty = document.querySelector('[data-watchlist-empty]');
  const filterEmpty = document.querySelector('[data-watchlist-filter-empty]');
  const status = document.getElementById('watchlist-status');
  const searchInput = document.getElementById('watchlist-search');
  const filterSelect = document.getElementById('watchlist-filter');
  const resetViewBtn = document.getElementById('watchlist-reset-view');
  const savedViewSelect = document.getElementById('watchlist-saved-view');
  const viewNameInput = document.getElementById('watchlist-view-name');
  const saveViewBtn = document.getElementById('watchlist-save-view');
  const deleteViewBtn = document.getElementById('watchlist-delete-view');
  const sortButtons = [...document.querySelectorAll('[data-watchlist-sort]')];
  if (!body || !tableWrap || !empty || !filterEmpty || !status || !searchInput || !filterSelect || !resetViewBtn || !savedViewSelect || !viewNameInput || !saveViewBtn || !deleteViewBtn) return;

  const VIEW_STORAGE_KEY = 'moex.watchlist.view.v1';
  const PIN_STORAGE_KEY = 'moex.watchlist.pins.v1';
  const SAVED_VIEWS_STORAGE_KEY = 'moex.watchlist.saved_views.v1';
  const MAX_SAVED_VIEWS = 10;
  const validFilters = new Set(['all', 'pinned', 'signals', 'positive', 'negative']);
  const validSortFields = new Set(['ticker', 'current', 'fair', 'upside', 'dividend', 'ratio']);

  const viewState = {
    total: 0,
    matchedVolumes: 0,
    volumeAvailable: true,
  };
  const sortState = {
    field: null,
    direction: 'asc',
  };
  const pinnedTickers = loadPinnedTickers();
  let savedViews = loadSavedViews();

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

  function normalizeTicker(value) {
    return String(value || '').trim().toLocaleUpperCase('ru').slice(0, 32);
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

  function loadPinnedTickers() {
    try {
      const raw = localStorage.getItem(PIN_STORAGE_KEY);
      if (!raw) return new Set();
      const saved = JSON.parse(raw);
      if (!Array.isArray(saved)) return new Set();
      return new Set(saved.map(normalizeTicker).filter(Boolean));
    } catch (_error) {
      return new Set();
    }
  }

  function persistPins() {
    try {
      localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify([...pinnedTickers].sort()));
    } catch (_error) {
      // Pinning remains usable for the current page even when storage is unavailable.
    }
  }

  function sanitizeSavedView(item) {
    if (!item || typeof item !== 'object') return null;
    const name = typeof item.name === 'string' ? item.name.trim().slice(0, 32) : '';
    if (!name) return null;
    const sortField = validSortFields.has(item.sortField) ? item.sortField : null;
    const sortDirection = item.sortDirection === 'desc' ? 'desc' : 'asc';
    return {
      name,
      search: typeof item.search === 'string' ? item.search.slice(0, 64) : '',
      filter: validFilters.has(item.filter) ? item.filter : 'all',
      sortField,
      sortDirection,
    };
  }

  function loadSavedViews() {
    try {
      const raw = localStorage.getItem(SAVED_VIEWS_STORAGE_KEY);
      if (!raw) return [];
      const saved = JSON.parse(raw);
      if (!Array.isArray(saved)) return [];
      const byName = new Map();
      saved.forEach((item) => {
        const sanitized = sanitizeSavedView(item);
        if (sanitized) byName.set(sanitized.name, sanitized);
      });
      return [...byName.values()].slice(-MAX_SAVED_VIEWS);
    } catch (_error) {
      return [];
    }
  }

  function persistSavedViews() {
    try {
      localStorage.setItem(SAVED_VIEWS_STORAGE_KEY, JSON.stringify(savedViews));
    } catch (_error) {
      // Named views remain usable for the current page when storage is unavailable.
    }
  }

  function persistView() {
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify({
        search: searchInput.value,
        filter: filterSelect.value,
        sortField: sortState.field,
        sortDirection: sortState.direction,
      }));
    } catch (_error) {
      // Storage can be disabled by the browser; Watchlist remains fully usable without persistence.
    }
  }

  function restoreView() {
    try {
      const raw = localStorage.getItem(VIEW_STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (!saved || typeof saved !== 'object') return;

      if (typeof saved.search === 'string') {
        searchInput.value = saved.search.slice(0, 64);
      }
      if (validFilters.has(saved.filter)) {
        filterSelect.value = saved.filter;
      }
      if (validSortFields.has(saved.sortField)) {
        sortState.field = saved.sortField;
        sortState.direction = saved.sortDirection === 'asc' ? 'asc' : 'desc';
      }
    } catch (_error) {
      // Ignore malformed or inaccessible storage and keep the default view.
    }
  }

  function clearPersistedView() {
    try {
      localStorage.removeItem(VIEW_STORAGE_KEY);
    } catch (_error) {
      // Nothing else is required when browser storage is unavailable.
    }
  }

  function renderSavedViews(selectedName = '') {
    savedViewSelect.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Сохранённые виды';
    savedViewSelect.appendChild(placeholder);

    [...savedViews]
      .sort((left, right) => left.name.localeCompare(right.name, 'ru'))
      .forEach((view) => {
        const option = document.createElement('option');
        option.value = view.name;
        option.textContent = view.name;
        savedViewSelect.appendChild(option);
      });

    savedViewSelect.value = savedViews.some((view) => view.name === selectedName) ? selectedName : '';
    updateSavedViewActions();
  }

  function updateSavedViewActions() {
    const enabled = !viewNameInput.disabled;
    saveViewBtn.disabled = !enabled || !viewNameInput.value.trim();
    deleteViewBtn.disabled = !enabled || !savedViewSelect.value;
  }

  function detachSavedViewSelection({ keepName = true } = {}) {
    if (savedViewSelect.value) savedViewSelect.value = '';
    if (!keepName) viewNameInput.value = '';
    updateSavedViewActions();
  }

  function captureCurrentView(name) {
    return {
      name,
      search: searchInput.value,
      filter: validFilters.has(filterSelect.value) ? filterSelect.value : 'all',
      sortField: validSortFields.has(sortState.field) ? sortState.field : null,
      sortDirection: sortState.direction === 'desc' ? 'desc' : 'asc',
    };
  }

  function saveNamedView() {
    const name = viewNameInput.value.trim().slice(0, 32);
    if (!name) return;
    const next = captureCurrentView(name);
    const existingIndex = savedViews.findIndex((view) => view.name === name);
    if (existingIndex >= 0) {
      savedViews[existingIndex] = next;
    } else {
      if (savedViews.length >= MAX_SAVED_VIEWS) savedViews.shift();
      savedViews.push(next);
    }
    persistSavedViews();
    viewNameInput.value = name;
    renderSavedViews(name);
  }

  function applyNamedView(name) {
    const view = savedViews.find((item) => item.name === name);
    if (!view) return;
    viewNameInput.value = view.name;
    searchInput.value = view.search;
    filterSelect.value = validFilters.has(view.filter) ? view.filter : 'all';
    sortState.field = validSortFields.has(view.sortField) ? view.sortField : null;
    sortState.direction = view.sortDirection === 'desc' ? 'desc' : 'asc';
    persistView();
    sortRows();
    applyFilters();
    updateSavedViewActions();
  }

  function deleteNamedView() {
    const name = savedViewSelect.value;
    if (!name) return;
    savedViews = savedViews.filter((view) => view.name !== name);
    persistSavedViews();
    viewNameInput.value = '';
    renderSavedViews();
  }

  function setControlsEnabled(enabled) {
    searchInput.disabled = !enabled;
    filterSelect.disabled = !enabled;
    resetViewBtn.disabled = !enabled;
    savedViewSelect.disabled = !enabled;
    viewNameInput.disabled = !enabled;
    sortButtons.forEach((button) => {
      button.disabled = !enabled;
    });
    updateSavedViewActions();
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

    if (filter === 'pinned') return row.dataset.watchlistPinned === 'true';
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
    const rows = [...body.querySelectorAll(':scope > tr')];
    if (sortState.field) {
      rows.sort(compareRows);
    } else {
      rows.sort((left, right) => Number(left.dataset.watchlistOrder) - Number(right.dataset.watchlistOrder));
    }
    rows.forEach((row) => body.appendChild(row));
    updateSortIndicators();
  }

  function changeSort(field) {
    detachSavedViewSelection();
    if (sortState.field === field) {
      sortState.direction = sortState.direction === 'asc' ? 'desc' : 'asc';
    } else {
      sortState.field = field;
      sortState.direction = field === 'ticker' ? 'asc' : 'desc';
    }
    persistView();
    sortRows();
    applyFilters();
  }

  function resetView() {
    searchInput.value = '';
    filterSelect.value = 'all';
    sortState.field = null;
    sortState.direction = 'asc';
    clearPersistedView();
    detachSavedViewSelection({ keepName: false });
    sortRows();
    applyFilters();
  }

  function updatePinButton(button, ticker, pinned) {
    button.setAttribute('aria-pressed', String(pinned));
    button.setAttribute('aria-label', `${pinned ? 'Открепить' : 'Закрепить'} ${ticker}`);
    button.title = `${pinned ? 'Открепить' : 'Закрепить'} ${ticker}`;
  }

  function togglePin(button) {
    const ticker = normalizeTicker(button.dataset.watchlistPin);
    if (!ticker) return;
    const row = button.closest('tr');
    const pinned = !pinnedTickers.has(ticker);
    if (pinned) pinnedTickers.add(ticker);
    else pinnedTickers.delete(ticker);
    persistPins();
    if (row) row.dataset.watchlistPinned = String(pinned);
    updatePinButton(button, ticker, pinned);
    applyFilters();
  }

  function render(rows, volumeRows, primaryTable, { volumeAvailable = true } = {}) {
    if (!rows.length) {
      showEmpty('Основная таблица оценок пуста', 'Добавьте бумаги в таблицу №1 — они появятся здесь автоматически.');
      return;
    }

    const volumeMap = new Map(
      (volumeRows || []).map((item) => [normalizeTicker(item.ticker), item]),
    );
    const year = Number(primaryTable.forecast_start_year) || new Date().getFullYear();
    let matchedVolumes = 0;

    body.innerHTML = rows.map((row, index) => {
      const ticker = normalizeTicker(row.ticker);
      const volume = volumeMap.get(ticker) || null;
      if (volume) matchedVolumes += 1;
      const latest = volume?.latest || null;
      const ratio = latest?.ratio;
      const yieldPercent = dividendYield(row, year);
      const signalStatus = latest?.signal_status || '';
      const pinned = pinnedTickers.has(ticker);

      return `
        <tr
          data-watchlist-order="${index}"
          data-watchlist-ticker="${escapeHtml(ticker)}"
          data-watchlist-pinned="${pinned}"
          data-watchlist-current="${escapeHtml(dataNumber(row.current_price))}"
          data-watchlist-fair="${escapeHtml(dataNumber(row.forecast_price_year1))}"
          data-watchlist-upside="${escapeHtml(dataNumber(row.upside_percent_year1))}"
          data-watchlist-dividend="${escapeHtml(dataNumber(yieldPercent))}"
          data-watchlist-ratio="${escapeHtml(dataNumber(ratio))}"
          data-watchlist-signal="${escapeHtml(signalStatus)}"
        >
          <td class="watchlist-pin-cell">
            <button
              class="watchlist-pin-btn"
              type="button"
              data-watchlist-pin="${escapeHtml(ticker)}"
              aria-pressed="${pinned}"
              aria-label="${pinned ? 'Открепить' : 'Закрепить'} ${escapeHtml(ticker)}"
              title="${pinned ? 'Открепить' : 'Закрепить'} ${escapeHtml(ticker)}"
            >★</button>
          </td>
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

  searchInput.addEventListener('input', () => {
    detachSavedViewSelection();
    persistView();
    applyFilters();
  });
  filterSelect.addEventListener('change', () => {
    detachSavedViewSelection();
    persistView();
    applyFilters();
  });
  resetViewBtn.addEventListener('click', resetView);
  viewNameInput.addEventListener('input', updateSavedViewActions);
  savedViewSelect.addEventListener('change', () => applyNamedView(savedViewSelect.value));
  saveViewBtn.addEventListener('click', saveNamedView);
  deleteViewBtn.addEventListener('click', deleteNamedView);
  body.addEventListener('click', (event) => {
    const button = event.target.closest('[data-watchlist-pin]');
    if (button) togglePin(button);
  });
  sortButtons.forEach((button) => {
    button.addEventListener('click', () => changeSort(button.dataset.watchlistSort));
  });

  restoreView();
  renderSavedViews();
  load();
})();
