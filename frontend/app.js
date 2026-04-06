const tbody = document.getElementById('rows-table-body');
const addRowBtn = document.getElementById('add-row-btn');
const addTableBtn = document.getElementById('add-table-btn');
const makePrimaryTableBtn = document.getElementById('make-primary-table-btn');
const deleteTableBtn = document.getElementById('delete-table-btn');
const tableSelect = document.getElementById('table-select');
const analystNameInput = document.getElementById('analyst-name-input');
const saveAnalystBtn = document.getElementById('save-analyst-btn');
const shiftYearBackBtn = document.getElementById('shift-year-back-btn');
const shiftYearBtn = document.getElementById('shift-year-btn');
const globalStatus = document.getElementById('global-status');
const sortButtons = document.querySelectorAll('.th-sort');
const sortTicker = document.getElementById('sort-ticker');
const sortMarketCap = document.getElementById('sort-market-cap');
const sortUpsideYear1 = document.getElementById('sort-upside-year1');
const sortUpsideYear2 = document.getElementById('sort-upside-year2');
const sortUpsideYear3 = document.getElementById('sort-upside-year3');
const sortUpsideYear4 = document.getElementById('sort-upside-year4');
const headerProfitYear1 = document.getElementById('header-profit-year1');
const headerProfitYear2 = document.getElementById('header-profit-year2');
const headerProfitYear3 = document.getElementById('header-profit-year3');
const headerProfitYear4 = document.getElementById('header-profit-year4');
const headerPriceYear1 = document.getElementById('header-price-year1');
const headerPriceYear2 = document.getElementById('header-price-year2');
const headerPriceYear3 = document.getElementById('header-price-year3');
const headerPriceYear4 = document.getElementById('header-price-year4');

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'medium',
});
const saveTimers = new Map();
const rowDrafts = new Map();
const dirtyRows = new Set();
const comparisonCache = new Map();
let comparisonHoverHideTimer = null;
let activeComparisonRowId = null;
const sortState = { key: null, direction: 'asc' };
const appState = {
  tables: [],
  activeTableId: null,
};
const AUTOSAVE_DELAY_MS = 1800;
const BASE_FORECAST_YEAR = new Date().getFullYear();
const RU_TO_EN_LAYOUT_MAP = {
  й: 'q',
  ц: 'w',
  у: 'e',
  к: 'r',
  е: 't',
  н: 'y',
  г: 'u',
  ш: 'i',
  щ: 'o',
  з: 'p',
  х: '[',
  ъ: ']',
  ф: 'a',
  ы: 's',
  в: 'd',
  а: 'f',
  п: 'g',
  р: 'h',
  о: 'j',
  л: 'k',
  д: 'l',
  ж: ';',
  э: "'",
  я: 'z',
  ч: 'x',
  с: 'c',
  м: 'v',
  и: 'b',
  т: 'n',
  ь: 'm',
  б: ',',
  ю: '.',
};

function normalizeDecimals(decimals) {
  if (!Number.isFinite(decimals)) return 2;
  return Math.min(Math.max(Math.trunc(decimals), 0), 10);
}

function detectDecimals(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 2;
  const str = String(value);
  const dot = str.indexOf('.');
  if (dot < 0) return 0;
  return normalizeDecimals(str.length - dot - 1);
}

function formatNumber(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  const safeDecimals = normalizeDecimals(decimals);
  const formatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: safeDecimals,
    maximumFractionDigits: safeDecimals,
  });
  return formatter.format(Number(value));
}

function formatCurrency(value, decimals = 2) {
  const formatted = formatNumber(value, decimals);
  return formatted === '—' ? formatted : `${formatted} ₽`;
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  const formatted = formatNumber(Math.round(Number(value)), 0);
  return formatted === '—' ? formatted : `${formatted} %`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function parseInputNumber(value) {
  if (value === '' || value === null || value === undefined) {
    return null;
  }
  const normalized = normalizeNumericInput(value).trim();
  if (!normalized) return null;
  const num = Number(normalized);
  return Number.isFinite(num) ? num : null;
}

function normalizeNumericInput(value) {
  return String(value ?? '').replace(/,/g, '.');
}

function normalizeTickerInput(value) {
  return String(value ?? '')
    .split('')
    .map((char) => {
      const lower = char.toLowerCase();
      const mapped = RU_TO_EN_LAYOUT_MAP[lower];
      if (!mapped) return char;
      return char === lower ? mapped : mapped.toUpperCase();
    })
    .join('')
    .toUpperCase();
}

const INPUT_NORMALIZERS = {
  ticker: normalizeTickerInput,
  shares_billion: normalizeNumericInput,
  pe_avg_5y: normalizeNumericInput,
  forecast_profit_year1_billion_rub: normalizeNumericInput,
  forecast_profit_year2_billion_rub: normalizeNumericInput,
  forecast_profit_year3_billion_rub: normalizeNumericInput,
};

function normalizeInputByField(field, value) {
  const normalizer = INPUT_NORMALIZERS[field];
  return normalizer ? normalizer(value) : String(value ?? '');
}

function formatDate(value) {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.valueOf())) return '—';
  return dateFormatter.format(dt);
}

function setGlobalStatus(text) {
  if (globalStatus) {
    globalStatus.textContent = text;
  }
}

function activeTable() {
  return appState.tables.find((table) => table.id === appState.activeTableId) || null;
}

function activeYears() {
  const offset = activeTable()?.year_offset ?? 0;
  return [
    BASE_FORECAST_YEAR + offset,
    BASE_FORECAST_YEAR + offset + 1,
    BASE_FORECAST_YEAR + offset + 2,
    BASE_FORECAST_YEAR + offset + 3,
  ];
}

function applyYearHeaders() {
  const [y1, y2, y3, y4] = activeYears();
  if (headerProfitYear1) headerProfitYear1.textContent = `Прогнозная ЧП (${y1}), млрд ₽`;
  if (headerProfitYear2) headerProfitYear2.textContent = `Прогнозная ЧП (${y2}), млрд ₽`;
  if (headerProfitYear3) headerProfitYear3.textContent = `Прогнозная ЧП (${y3}), млрд ₽`;
  if (headerProfitYear4) headerProfitYear4.textContent = `Прогнозная ЧП (${y4}), млрд ₽`;
  if (headerPriceYear1) headerPriceYear1.textContent = `Прогнозная цена (${y1}), ₽`;
  if (headerPriceYear2) headerPriceYear2.textContent = `Прогнозная цена (${y2}), ₽`;
  if (headerPriceYear3) headerPriceYear3.textContent = `Прогнозная цена (${y3}), ₽`;
  if (headerPriceYear4) headerPriceYear4.textContent = `Прогнозная цена (${y4}), ₽`;
}

function yearKeyByIndex(index) {
  const years = activeYears();
  return String(years[index]);
}

function mapProfitByYear(row, index) {
  const key = yearKeyByIndex(index);
  const map = row.net_profit_year_map || {};
  return map[key] ?? null;
}

function renderTableSelector() {
  if (!tableSelect) return;
  tableSelect.innerHTML = '';
  appState.tables.forEach((table) => {
    const option = document.createElement('option');
    option.value = String(table.id);
    option.textContent = `№${table.table_number} — ${table.analyst_name}`;
    if (table.id === appState.activeTableId) option.selected = true;
    tableSelect.appendChild(option);
  });
  const current = activeTable();
  if (analystNameInput && current) analystNameInput.value = current.analyst_name;
  if (deleteTableBtn) {
    deleteTableBtn.disabled = !current || current.table_number === 1;
    deleteTableBtn.title = current?.table_number === 1 ? 'Таблица №1 защищена от удаления' : '';
  }
  if (makePrimaryTableBtn) {
    makePrimaryTableBtn.disabled = !current || current.table_number === 1;
    makePrimaryTableBtn.title = current?.table_number === 1 ? 'Эта таблица уже основная' : '';
  }
  applyYearHeaders();
  updateSortIndicators();
}

function isEditingInput() {
  const activeElement = document.activeElement;
  return Boolean(activeElement && activeElement.tagName === 'INPUT' && tbody.contains(activeElement));
}

function upsideClass(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 'upside-flat';
  if (num > 0) return 'upside-up';
  if (num < 0) return 'upside-down';
  return 'upside-flat';
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!res.ok) {
    let details = '';
    try {
      details = await res.text();
    } catch (_err) {
      details = '';
    }
    throw new Error(`Ошибка API: ${res.status}${details ? ` (${details})` : ''}`);
  }
  return res.json();
}

async function loadTables() {
  const tables = await api('/api/tables');
  appState.tables = tables;
  if (!tables.length) {
    throw new Error('Нет доступных таблиц аналитиков');
  }
  if (!appState.activeTableId || !tables.find((table) => table.id === appState.activeTableId)) {
    appState.activeTableId = tables[0].id;
  }
  renderTableSelector();
}

async function loadRows() {
  if (!appState.activeTableId) {
    await loadTables();
  }
  comparisonCache.clear();
  setGlobalStatus('Загрузка данных...');
  const maxAttempts = 5;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const rows = await api(`/api/rows?table_id=${appState.activeTableId}`);
      renderRows(rows);
      setGlobalStatus(`Обновлено: ${new Date().toLocaleTimeString('ru-RU')}`);
      return;
    } catch (err) {
      lastError = err;
      await new Promise((resolve) => setTimeout(resolve, attempt * 1200));
    }
  }

  throw lastError || new Error('Не удалось загрузить данные');
}

function clearInlineComparisonRows() {
  if (comparisonHoverHideTimer) {
    clearTimeout(comparisonHoverHideTimer);
    comparisonHoverHideTimer = null;
  }
  tbody.querySelectorAll('tr.comparison-inline-row').forEach((row) => row.remove());
  tbody.querySelectorAll('tr.ticker-compare-highlight').forEach((row) => row.classList.remove('ticker-compare-highlight'));
  activeComparisonRowId = null;
}

function getComparisonYear(item, index) {
  return (item.years || [])[index] || null;
}

function createInlineComparisonRow(item) {
  const y1 = getComparisonYear(item, 0);
  const y2 = getComparisonYear(item, 1);
  const y3 = getComparisonYear(item, 2);
  const y4 = getComparisonYear(item, 3);
  const priceDecimals = detectDecimals(item.current_price);
  const tr = document.createElement('tr');
  tr.className = 'comparison-inline-row ticker-compare-highlight';
  tr.innerHTML = `
    <td><input value="${item.ticker ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(item.current_price, priceDecimals)}</span></td>
    <td><input value="${item.shares_billion ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(item.market_cap_billion_rub)}</span></td>
    <td><input value="${item.pe_avg_5y ?? ''}" disabled /></td>
    <td><input value="${y1?.forecast_profit_billion_rub ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(y1?.forecast_price, priceDecimals)}</span></td>
    <td class="readonly-cell ${upsideClass(y1?.upside_percent)}">${formatPercent(y1?.upside_percent)}</td>
    <td><input value="${y2?.forecast_profit_billion_rub ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(y2?.forecast_price, priceDecimals)}</span></td>
    <td class="readonly-cell ${upsideClass(y2?.upside_percent)}">${formatPercent(y2?.upside_percent)}</td>
    <td><input value="${y3?.forecast_profit_billion_rub ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(y3?.forecast_price, priceDecimals)}</span></td>
    <td class="readonly-cell ${upsideClass(y3?.upside_percent)}">${formatPercent(y3?.upside_percent)}</td>
    <td><input value="${y4?.forecast_profit_billion_rub ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(y4?.forecast_price, priceDecimals)}</span></td>
    <td class="readonly-cell ${upsideClass(y4?.upside_percent)}">${formatPercent(y4?.upside_percent)}</td>
    <td class="readonly-cell"><span>${formatDate(item.price_updated_at)}</span></td>
    <td><span class="comparison-source">№${item.table_number} — ${escapeHtml(item.analyst_name)}</span></td>
  `;
  return tr;
}

async function showInlineComparisonRows(anchorTr, ticker, rowId) {
  if (comparisonHoverHideTimer) {
    clearTimeout(comparisonHoverHideTimer);
    comparisonHoverHideTimer = null;
  }
  if (activeComparisonRowId === rowId && anchorTr.nextElementSibling?.classList.contains('comparison-inline-row')) {
    return;
  }
  const normalizedTicker = normalizeTickerInput(ticker).trim();
  clearInlineComparisonRows();
  if (!normalizedTicker) return;

  let items = comparisonCache.get(normalizedTicker);
  if (!items) {
    try {
      items = await api(`/api/ticker-comparison?ticker=${encodeURIComponent(normalizedTicker)}`);
      comparisonCache.set(normalizedTicker, items);
    } catch (_err) {
      return;
    }
  }

  const otherTables = (items || []).filter((item) => item.table_id !== appState.activeTableId);
  if (!otherTables.length) return;

  anchorTr.classList.add('ticker-compare-highlight');
  activeComparisonRowId = rowId;
  const baseRows = Array.from(tbody.querySelectorAll('tr:not(.comparison-inline-row)'));
  const anchorIndex = baseRows.indexOf(anchorTr);
  const isTopHalf = anchorIndex < 0 || anchorIndex < baseRows.length / 2;

  if (isTopHalf) {
    let insertAfter = anchorTr;
    otherTables.forEach((item) => {
      const row = createInlineComparisonRow(item);
      insertAfter.insertAdjacentElement('afterend', row);
      insertAfter = row;
    });
  } else {
    let insertBefore = anchorTr;
    otherTables.forEach((item) => {
      const row = createInlineComparisonRow(item);
      insertBefore.insertAdjacentElement('beforebegin', row);
      insertBefore = row;
    });
  }
}

function rowToPayload(row) {
  const profitMap = row.net_profit_year_map || {};
  return {
    table_id: appState.activeTableId,
    ticker: row.ticker || '',
    shares_billion: parseInputNumber(row.shares_billion),
    pe_avg_5y: parseInputNumber(row.pe_avg_5y),
    forecast_profit_year1_billion_rub: parseInputNumber(profitMap[yearKeyByIndex(0)]),
    forecast_profit_year2_billion_rub: parseInputNumber(profitMap[yearKeyByIndex(1)]),
    forecast_profit_year3_billion_rub: parseInputNumber(profitMap[yearKeyByIndex(2)]),
    forecast_profit_year4_billion_rub: parseInputNumber(profitMap[yearKeyByIndex(3)]),
    net_profit_year_map: profitMap,
  };
}

function updateCalculatedCells(tr, row) {
  const priceDecimals = detectDecimals(row.current_price);
  const setCellText = (cellName, value) => {
    const cell = tr.querySelector(`[data-cell="${cellName}"]`);
    if (cell) cell.textContent = value;
  };
  const setUpsideCell = (cellName, value) => {
    const cell = tr.querySelector(`[data-cell="${cellName}"]`);
    if (!cell) return;
    cell.textContent = formatPercent(value);
    cell.classList.remove('upside-up', 'upside-down', 'upside-flat');
    cell.classList.add(upsideClass(value));
  };

  setCellText('current_price', formatCurrency(row.current_price, priceDecimals));
  setCellText('market_cap', formatCurrency(row.market_cap_billion_rub));
  setCellText('forecast_price_year1', formatCurrency(row.forecast_price_year1, priceDecimals));
  setCellText('forecast_price_year2', formatCurrency(row.forecast_price_year2, priceDecimals));
  setCellText('forecast_price_year3', formatCurrency(row.forecast_price_year3, priceDecimals));
  setCellText('forecast_price_year4', formatCurrency(row.forecast_price_year4, priceDecimals));
  setUpsideCell('upside_year1', row.upside_percent_year1);
  setUpsideCell('upside_year2', row.upside_percent_year2);
  setUpsideCell('upside_year3', row.upside_percent_year3);
  setUpsideCell('upside_year4', row.upside_percent_year4);
  setCellText('price_updated_at', formatDate(row.price_updated_at));
}

async function saveRowChanges(row, tr, { force = false } = {}) {
  if (!force && !dirtyRows.has(row.id)) return;
  const draft = rowDrafts.get(row.id) || row;
  const savedRow = await api(`/api/rows/${row.id}`, {
    method: 'PUT',
    body: JSON.stringify(rowToPayload(draft)),
  });
  Object.assign(row, savedRow);
  rowDrafts.set(row.id, { ...savedRow });
  dirtyRows.delete(row.id);

  if (!isEditingInput()) {
    await loadRows();
  } else {
    updateCalculatedCells(tr, row);
    setGlobalStatus('Изменения сохранены');
  }
}

function compareValues(a, b, direction = 'asc') {
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;

  const aNum = Number(a);
  const bNum = Number(b);
  if (Number.isFinite(aNum) && Number.isFinite(bNum)) {
    return direction === 'asc' ? aNum - bNum : bNum - aNum;
  }

  const aText = String(a).toUpperCase();
  const bText = String(b).toUpperCase();
  if (aText < bText) return direction === 'asc' ? -1 : 1;
  if (aText > bText) return direction === 'asc' ? 1 : -1;
  return 0;
}

function sortRows(rows) {
  if (!sortState.key) return rows;
  return [...rows].sort((left, right) => compareValues(left[sortState.key], right[sortState.key], sortState.direction));
}

function updateSortIndicators() {
  const [year1, year2, year3, year4] = activeYears();
  const sortableHeaders = [
    { element: sortTicker, key: 'ticker', label: 'Тикер' },
    { element: sortMarketCap, key: 'market_cap_billion_rub', label: 'Капитализация, млрд ₽' },
    { element: sortUpsideYear1, key: 'upside_percent_year1', label: `Upside (${year1}), %` },
    { element: sortUpsideYear2, key: 'upside_percent_year2', label: `Upside (${year2}), %` },
    { element: sortUpsideYear3, key: 'upside_percent_year3', label: `Upside (${year3}), %` },
    { element: sortUpsideYear4, key: 'upside_percent_year4', label: `Upside (${year4}), %` },
  ];

  sortableHeaders.forEach(({ element, key, label }) => {
    if (!element) return;
    if (sortState.key === key) {
      element.textContent = `${label} ${sortState.direction === 'asc' ? '↑' : '↓'}`;
    } else {
      element.textContent = `${label} ⇅`;
    }
  });
}

function renderRows(rows) {
  const sortedRows = sortRows(rows);
  tbody.innerHTML = '';

  sortedRows.forEach((row) => {
    const priceDecimals = detectDecimals(row.current_price);
    const primaryEditable = activeTable()?.table_number === 1;
    const tr = document.createElement('tr');

    tr.innerHTML = `
      <td><input data-field="ticker" value="${row.ticker ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="current_price">${formatCurrency(row.current_price, priceDecimals)}</span></td>
      <td><input data-field="shares_billion" value="${row.shares_billion ?? ''}" ${primaryEditable ? '' : 'readonly'} /></td>
      <td class="readonly-cell"><span data-cell="market_cap">${formatCurrency(row.market_cap_billion_rub)}</span></td>
      <td><input data-field="pe_avg_5y" value="${row.pe_avg_5y ?? ''}" ${primaryEditable ? '' : 'readonly'} /></td>
      <td><input data-field="forecast_profit_year1_billion_rub" value="${mapProfitByYear(row, 0) ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year1">${formatCurrency(row.forecast_price_year1, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year1)}" data-cell="upside_year1">${formatPercent(row.upside_percent_year1)}</td>
      <td><input data-field="forecast_profit_year2_billion_rub" value="${mapProfitByYear(row, 1) ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year2">${formatCurrency(row.forecast_price_year2, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year2)}" data-cell="upside_year2">${formatPercent(row.upside_percent_year2)}</td>
      <td><input data-field="forecast_profit_year3_billion_rub" value="${mapProfitByYear(row, 2) ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year3">${formatCurrency(row.forecast_price_year3, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year3)}" data-cell="upside_year3">${formatPercent(row.upside_percent_year3)}</td>
      <td><input data-field="forecast_profit_year4_billion_rub" value="${mapProfitByYear(row, 3) ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year4">${formatCurrency(row.forecast_price_year4, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year4)}" data-cell="upside_year4">${formatPercent(row.upside_percent_year4)}</td>
      <td class="readonly-cell"><span data-cell="price_updated_at">${formatDate(row.price_updated_at)}</span></td>
      <td>
        <button data-action="delete" class="btn-danger">Удалить</button>
        ${row.status_message ? `<div class="status-error">${row.status_message}</div>` : ''}
      </td>
    `;

    tr.querySelectorAll('input').forEach((input) => {
      input.addEventListener('input', async () => {
        const normalizedValue = normalizeInputByField(input.dataset.field, input.value);
        if (input.value !== normalizedValue) {
          input.value = normalizedValue;
        }

        const updated = {
          ...(rowDrafts.get(row.id) || row),
          [input.dataset.field]: normalizedValue,
        };
        if (input.dataset.field.startsWith('forecast_profit_year')) {
          const map = { ...(updated.net_profit_year_map || {}) };
          const yearIndexMap = {
            forecast_profit_year1_billion_rub: 0,
            forecast_profit_year2_billion_rub: 1,
            forecast_profit_year3_billion_rub: 2,
            forecast_profit_year4_billion_rub: 3,
          };
          const yearIndex = yearIndexMap[input.dataset.field];
          if (yearIndex !== undefined) {
            map[yearKeyByIndex(yearIndex)] = parseInputNumber(normalizedValue);
            updated.net_profit_year_map = map;
          }
        }
        rowDrafts.set(row.id, updated);
        dirtyRows.add(row.id);

        if (saveTimers.has(row.id)) {
          clearTimeout(saveTimers.get(row.id));
        }
        saveTimers.set(row.id, setTimeout(async () => {
          try {
            await saveRowChanges(row, tr);
          } catch (err) {
            alert(err.message);
          }
        }, AUTOSAVE_DELAY_MS));
      });

      input.addEventListener('blur', async () => {
        if (saveTimers.has(row.id)) {
          clearTimeout(saveTimers.get(row.id));
          saveTimers.delete(row.id);
        }
        try {
          await saveRowChanges(row, tr, { force: false });
        } catch (err) {
          alert(err.message);
        }
      });
    });

    const tickerInput = tr.querySelector('input[data-field="ticker"]');
    tickerInput?.addEventListener('mouseenter', () => {
      const draft = rowDrafts.get(row.id) || row;
      showInlineComparisonRows(tr, draft.ticker, row.id);
    });
    tickerInput?.addEventListener('mouseleave', () => {
      comparisonHoverHideTimer = setTimeout(() => {
        const isAnchorHovered = tr.matches(':hover');
        const isTickerHovered = tickerInput.matches(':hover');
        const isComparisonHovered = Boolean(tbody.querySelector('tr.comparison-inline-row:hover'));
        if (isAnchorHovered || isTickerHovered || isComparisonHovered) {
          return;
        }
        clearInlineComparisonRows();
      }, 120);
    });
    tickerInput?.addEventListener('blur', clearInlineComparisonRows);

    tr.querySelector('[data-action="delete"]').addEventListener('click', async () => {
      try {
        await api(`/api/rows/${row.id}`, { method: 'DELETE' });
        await loadRows();
      } catch (err) {
        alert(err.message);
      }
    });

    tbody.appendChild(tr);
  });
}

tbody.addEventListener('focusout', () => {
  setTimeout(() => {
    if (!isEditingInput()) {
      loadRows().catch((err) => {
        console.error(err);
        setGlobalStatus('Ошибка загрузки');
      });
    }
  }, 0);
});

document.addEventListener('click', clearInlineComparisonRows, true);
window.addEventListener('blur', clearInlineComparisonRows);

tableSelect?.addEventListener('change', async () => {
  appState.activeTableId = Number(tableSelect.value);
  renderTableSelector();
  await loadRows();
});

saveAnalystBtn?.addEventListener('click', async () => {
  const current = activeTable();
  if (!current) return;
  const analystName = (analystNameInput?.value || '').trim();
  if (!analystName) return;
  await api(`/api/tables/${current.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ analyst_name: analystName }),
  });
  await loadTables();
  await loadRows();
});

addTableBtn?.addEventListener('click', async () => {
  const desiredName = prompt('Введите имя аналитика для новой таблицы');
  if (!desiredName) return;
  await api('/api/tables', {
    method: 'POST',
    body: JSON.stringify({ analyst_name: desiredName }),
  });
  await loadTables();
  appState.activeTableId = appState.tables.at(-1)?.id ?? appState.activeTableId;
  renderTableSelector();
  await loadRows();
});

makePrimaryTableBtn?.addEventListener('click', async () => {
  const current = activeTable();
  if (!current || current.table_number === 1) return;
  await api(`/api/tables/${current.id}/make-primary`, { method: 'POST' });
  await loadTables();
  appState.activeTableId = current.id;
  renderTableSelector();
  await loadRows();
});

deleteTableBtn?.addEventListener('click', async () => {
  const current = activeTable();
  if (!current) return;
  if (current.table_number === 1) {
    alert('Таблица №1 является основной и не может быть удалена.');
    return;
  }
  const approved = confirm(`Удалить таблицу №${current.table_number} «${current.analyst_name}»?`);
  if (!approved) return;
  await api(`/api/tables/${current.id}`, { method: 'DELETE' });
  await loadTables();
  appState.activeTableId = appState.tables[0]?.id ?? null;
  renderTableSelector();
  await loadRows();
});

shiftYearBtn?.addEventListener('click', async () => {
  const current = activeTable();
  if (!current) return;
  await api(`/api/tables/${current.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ year_offset: (current.year_offset ?? 0) + 1 }),
  });
  await loadTables();
  await loadRows();
});

shiftYearBackBtn?.addEventListener('click', async () => {
  const current = activeTable();
  if (!current) return;
  await api(`/api/tables/${current.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ year_offset: (current.year_offset ?? 0) - 1 }),
  });
  await loadTables();
  await loadRows();
});

addRowBtn.addEventListener('click', async () => {
  try {
    await api('/api/rows', {
      method: 'POST',
      body: JSON.stringify({
        table_id: appState.activeTableId,
        ticker: '',
        shares_billion: null,
        pe_avg_5y: null,
        forecast_profit_year1_billion_rub: null,
        forecast_profit_year2_billion_rub: null,
        forecast_profit_year3_billion_rub: null,
        forecast_profit_year4_billion_rub: null,
      }),
    });
    await loadRows();
  } catch (err) {
    alert(err.message);
  }
});

setInterval(async () => {
  if (isEditingInput()) return;
  try {
    await loadRows();
  } catch (err) {
    console.error('Не удалось обновить таблицу:', err);
  }
}, 60 * 1000);

sortButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const nextKey = button.dataset.sort;
    if (sortState.key === nextKey) {
      sortState.direction = sortState.direction === 'asc' ? 'desc' : 'asc';
    } else {
      sortState.key = nextKey;
      sortState.direction = 'asc';
    }
    loadRows().catch((err) => {
      console.error(err);
      setGlobalStatus('Ошибка сортировки');
    });
    updateSortIndicators();
  });
});

async function initApp() {
  try {
    await loadTables();
    updateSortIndicators();
    await loadRows();
  } catch (err) {
    console.error(err);
    setGlobalStatus('Ошибка загрузки');
    alert(`Не удалось загрузить данные. Проверьте, что backend поднят и доступен: ${err.message}`);
  }
}

initApp();
