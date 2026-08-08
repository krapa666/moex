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
const refreshPricesBtn = document.getElementById('refresh-prices-btn');
const exportDataBtn = document.getElementById('export-data-btn');
const importDataBtn = document.getElementById('import-data-btn');
const importDataFileInput = document.getElementById('import-data-file-input');
const authUserLabel = document.getElementById('auth-user-label');
const globalStatus = document.getElementById('global-status');
const sortButtons = document.querySelectorAll('.th-sort');
const sortTicker = document.getElementById('sort-ticker');
const sortMarketCap = document.getElementById('sort-market-cap');
const sortUpsideYear1 = document.getElementById('sort-upside-year1');
const sortUpsideYear2 = document.getElementById('sort-upside-year2');
const headerProfitYear1 = document.getElementById('header-profit-year1');
const headerProfitYear2 = document.getElementById('header-profit-year2');
const headerPriceYear1 = document.getElementById('header-price-year1');
const headerPriceYear2 = document.getElementById('header-price-year2');
const headerDividendsYear1 = document.getElementById('header-dividends-year1');
const headerDividendsYear2 = document.getElementById('header-dividends-year2');
const headerYear1Group = document.getElementById('header-year1-group');
const headerYear2Group = document.getElementById('header-year2-group');

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'medium',
});
const saveTimers = new Map();
const rowDrafts = new Map();
const dirtyRows = new Set();
const rowDraftVersions = new Map();
const rowSaveInFlight = new Map();
const comparisonCache = new Map();
let comparisonHoverHideTimer = null;
let activeComparisonRowId = null;
let comparisonRequestSeq = 0;
const sortState = { key: null, direction: 'asc' };
const appState = {
  tables: [],
  activeTableId: null,
};
const authState = {
  user: null,
};
const AUTOSAVE_DELAY_MS = 1800;
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
    .toUpperCase()
    .replace(/[^A-Z0-9._-]/g, '');
}

function applyTickerInputSizing(input) {
  if (!input) return;
  const length = String(input.value ?? '').trim().length;
  const adaptiveChars = Math.max(5, Math.min(10, length || 5));
  input.style.setProperty('--ticker-ch', String(adaptiveChars + 1));
}

const INPUT_NORMALIZERS = {
  ticker: normalizeTickerInput,
  shares_billion: normalizeNumericInput,
  pe_avg_5y: normalizeNumericInput,
  forecast_profit_year1_billion_rub: normalizeNumericInput,
  forecast_profit_year2_billion_rub: normalizeNumericInput,
  dividends_year1: normalizeNumericInput,
  dividends_year2: normalizeNumericInput,
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

function formatPriceUpdated(value) {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.valueOf())) return '—';
  const ageMinutes = Math.max(0, Math.floor((Date.now() - dt.valueOf()) / 60000));
  let ageText = 'сейчас';
  if (ageMinutes >= 24 * 60) ageText = `${Math.floor(ageMinutes / (24 * 60))} дн. назад`;
  else if (ageMinutes >= 60) ageText = `${Math.floor(ageMinutes / 60)} ч. назад`;
  else if (ageMinutes >= 1) ageText = `${ageMinutes} мин. назад`;
  return `${dateFormatter.format(dt)} · ${ageText}`;
}

function setGlobalStatus(text) {
  if (globalStatus) {
    globalStatus.textContent = text;
  }
}

function activeTable() {
  return appState.tables.find((table) => table.id === appState.activeTableId) || null;
}

function isPrimaryActiveTable() {
  return activeTable()?.table_number === 1;
}

function canEditData() {
  return Boolean(authState.user?.is_admin);
}

function displayAnalystName(tableNumber, analystName) {
  if (canEditData()) {
    return `№${tableNumber} — ${analystName}`;
  }
  return `Аналитик ${tableNumber}`;
}

function activeYears() {
  const startYear = activeTable()?.forecast_start_year ?? new Date().getFullYear();
  return [
    startYear,
    startYear + 1,
  ];
}

function applyYearHeaders() {
  const [y1, y2] = activeYears();
  if (headerYear1Group) headerYear1Group.textContent = String(y1);
  if (headerYear2Group) headerYear2Group.textContent = String(y2);
  if (headerProfitYear1) headerProfitYear1.textContent = 'Прогнозная ЧП, млрд ₽';
  if (headerProfitYear2) headerProfitYear2.textContent = 'Прогнозная ЧП, млрд ₽';
  if (headerPriceYear1) headerPriceYear1.textContent = 'Прогнозная цена, ₽';
  if (headerPriceYear2) headerPriceYear2.textContent = 'Прогнозная цена, ₽';
  if (headerDividendsYear1) headerDividendsYear1.textContent = 'Остаток дивидендов к выплате, ₽/акцию';
  if (headerDividendsYear2) headerDividendsYear2.textContent = 'Остаток дивидендов к выплате, ₽/акцию';
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

function mapDividendsByYear(row, index) {
  const key = yearKeyByIndex(index);
  const map = row.dividend_year_map || {};
  return map[key] ?? null;
}

function renderTableSelector() {
  if (!tableSelect) return;
  tableSelect.innerHTML = '';
  appState.tables.forEach((table) => {
    const option = document.createElement('option');
    option.value = String(table.id);
    option.textContent = displayAnalystName(table.table_number, table.analyst_name);
    if (table.id === appState.activeTableId) option.selected = true;
    tableSelect.appendChild(option);
  });
  const current = activeTable();
  const canEdit = canEditData();
  if (analystNameInput && current) analystNameInput.value = current.analyst_name;
  if (deleteTableBtn) {
    deleteTableBtn.disabled = !canEdit || !current || current.table_number === 1;
    deleteTableBtn.title = !canEdit
      ? 'Редактирование доступно только из локальной сети'
      : current?.table_number === 1
        ? 'Таблица №1 защищена от удаления'
        : '';
  }
  if (makePrimaryTableBtn) {
    makePrimaryTableBtn.disabled = !canEdit || !current || current.table_number === 1;
    makePrimaryTableBtn.title = !canEdit
      ? 'Редактирование доступно только из локальной сети'
      : current?.table_number === 1
        ? 'Эта таблица уже основная'
        : '';
  }
  if (addRowBtn) {
    const isPrimary = current?.table_number === 1;
    addRowBtn.style.display = canEdit && isPrimary ? '' : 'none';
    addRowBtn.disabled = !canEdit || !isPrimary;
    addRowBtn.title = !canEdit ? 'Редактирование доступно только из локальной сети' : isPrimary ? '' : 'Кнопка доступна только в таблице №1';
  }
  applyWriteAccessUi();
  applyYearHeaders();
  updateSortIndicators();
}

function isEditingInput() {
  const activeElement = document.activeElement;
  return Boolean(activeElement && activeElement.tagName === 'INPUT' && tbody.contains(activeElement));
}

function upsideClass(value, { isNearTerm = false } = {}) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 'upside-flat';
  if (num > 30 && isNearTerm) return 'upside-up-strong';
  if (num > 0) return 'upside-up';
  if (num < 0) return 'upside-down';
  return 'upside-flat';
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const hasFormDataBody = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (!hasFormDataBody && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(path, {
    headers,
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

function updateAuthUi() {
  const user = authState.user;
  if (authUserLabel) {
    authUserLabel.textContent = user?.is_admin
      ? 'Локальная сеть · редактирование'
      : 'Гость · только чтение';
  }
  applyWriteAccessUi();
}

function applyWriteAccessUi() {
  const canEdit = canEditData();
  [
    analystNameInput,
    saveAnalystBtn,
    addTableBtn,
    makePrimaryTableBtn,
    deleteTableBtn,
    shiftYearBackBtn,
    shiftYearBtn,
    refreshPricesBtn,
    addRowBtn,
    exportDataBtn,
    importDataBtn,
  ]
    .forEach((element) => {
      if (!element) return;
      element.hidden = !canEdit;
      element.disabled = !canEdit;
    });
}

async function restoreSession() {
  try {
    authState.user = await api('/api/auth/me');
  } catch (_err) {
    authState.user = { username: 'guest', is_admin: false };
  }
  updateAuthUi();
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

function clearInlineComparisonRows({ invalidatePending = true } = {}) {
  if (comparisonHoverHideTimer) {
    clearTimeout(comparisonHoverHideTimer);
    comparisonHoverHideTimer = null;
  }
  if (invalidatePending) {
    comparisonRequestSeq += 1;
  }
  tbody.querySelectorAll('tr.comparison-inline-row').forEach((row) => row.remove());
  tbody.querySelectorAll('tr.ticker-compare-highlight').forEach((row) => row.classList.remove('ticker-compare-highlight'));
  tbody.querySelectorAll('tr.comparison-anchor-row').forEach((row) => row.classList.remove('comparison-anchor-row'));
  tbody.querySelectorAll('.comparison-anchor-label').forEach((label) => label.remove());
  tbody.querySelectorAll('.row-delete-btn.hidden').forEach((btn) => {
    btn.classList.remove('hidden');
    btn.style.display = '';
  });
  activeComparisonRowId = null;
}

function getComparisonYear(item, year) {
  return (item.years || []).find((entry) => entry.year === year) || null;
}

function createInlineComparisonRow(item) {
  const [activeYear1, activeYear2] = activeYears();
  const y1 = getComparisonYear(item, activeYear1);
  const y2 = getComparisonYear(item, activeYear2);
  const priceDecimals = detectDecimals(item.current_price);
  const tr = document.createElement('tr');
  tr.className = 'comparison-inline-row ticker-compare-highlight';
  tr.innerHTML = `
    <td><input class="ticker-input" value="${escapeHtml(item.ticker ?? '')}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(item.current_price, priceDecimals)}</span></td>
    <td><input value="${item.shares_billion ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(item.market_cap_billion_rub)}</span></td>
    <td><input value="${item.pe_avg_5y ?? ''}" disabled /></td>
    <td><input value="${y1?.forecast_profit_billion_rub ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(y1?.forecast_price, priceDecimals)}</span></td>
    <td><input value="${y1?.dividends_per_share ?? ''}" disabled /></td>
    <td class="readonly-cell ${upsideClass(y1?.upside_percent, { isNearTerm: true })}">${formatPercent(y1?.upside_percent)}</td>
    <td><input value="${y2?.forecast_profit_billion_rub ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(y2?.forecast_price, priceDecimals)}</span></td>
    <td><input value="${y2?.dividends_per_share ?? ''}" disabled /></td>
    <td class="readonly-cell ${upsideClass(y2?.upside_percent)}">${formatPercent(y2?.upside_percent)}</td>
    <td class="readonly-cell"><span>${formatDate(item.price_updated_at)}</span></td>
    <td><span class="comparison-source">${escapeHtml(displayAnalystName(item.table_number, item.analyst_name))}</span></td>
  `;
  applyTickerInputSizing(tr.querySelector('.ticker-input'));
  return tr;
}

function median(values) {
  const numbers = values
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map(Number)
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  if (!numbers.length) return null;
  const middle = Math.floor(numbers.length / 2);
  return numbers.length % 2 ? numbers[middle] : (numbers[middle - 1] + numbers[middle]) / 2;
}

function medianComparisonYear(items, year, field) {
  return median(
    items
      .map((item) => getComparisonYear(item, year)?.[field])
      .filter((value) => value !== null && value !== undefined),
  );
}

function createConsensusComparisonRow(items, ticker) {
  const [year1, year2] = activeYears();
  const priceDecimals = detectDecimals(median(items.map((item) => item.current_price)));
  const tr = document.createElement('tr');
  tr.className = 'comparison-inline-row consensus-row';
  tr.innerHTML = `
    <td><input class="ticker-input" value="${escapeHtml(ticker)}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(median(items.map((item) => item.current_price)), priceDecimals)}</span></td>
    <td><input value="${median(items.map((item) => item.shares_billion)) ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(median(items.map((item) => item.market_cap_billion_rub)))}</span></td>
    <td><input value="${median(items.map((item) => item.pe_avg_5y)) ?? ''}" disabled /></td>
    <td><input value="${medianComparisonYear(items, year1, 'forecast_profit_billion_rub') ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(medianComparisonYear(items, year1, 'forecast_price'), priceDecimals)}</span></td>
    <td><input value="${medianComparisonYear(items, year1, 'dividends_per_share') ?? ''}" disabled /></td>
    <td class="readonly-cell ${upsideClass(medianComparisonYear(items, year1, 'upside_percent'), { isNearTerm: true })}">${formatPercent(medianComparisonYear(items, year1, 'upside_percent'))}</td>
    <td><input value="${medianComparisonYear(items, year2, 'forecast_profit_billion_rub') ?? ''}" disabled /></td>
    <td class="readonly-cell"><span>${formatCurrency(medianComparisonYear(items, year2, 'forecast_price'), priceDecimals)}</span></td>
    <td><input value="${medianComparisonYear(items, year2, 'dividends_per_share') ?? ''}" disabled /></td>
    <td class="readonly-cell ${upsideClass(medianComparisonYear(items, year2, 'upside_percent'))}">${formatPercent(medianComparisonYear(items, year2, 'upside_percent'))}</td>
    <td class="readonly-cell">—</td>
    <td><span class="comparison-source">Медиана (${items.length})</span></td>
  `;
  applyTickerInputSizing(tr.querySelector('.ticker-input'));
  return tr;
}

function scheduleInlineComparisonHide(anchorTr, tickerInput, delayMs = 120) {
  if (comparisonHoverHideTimer) {
    clearTimeout(comparisonHoverHideTimer);
  }
  comparisonHoverHideTimer = setTimeout(() => {
    const isAnchorHovered = anchorTr?.matches(':hover');
    const isTickerHovered = tickerInput?.matches(':hover');
    const isComparisonHovered = Boolean(tbody.querySelector('tr.comparison-inline-row:hover'));
    if (isAnchorHovered || isTickerHovered || isComparisonHovered) {
      return;
    }
    clearInlineComparisonRows();
  }, delayMs);
}

async function showInlineComparisonRows(anchorTr, ticker, rowId) {
  const requestSeq = comparisonRequestSeq + 1;
  comparisonRequestSeq = requestSeq;
  if (comparisonHoverHideTimer) {
    clearTimeout(comparisonHoverHideTimer);
    comparisonHoverHideTimer = null;
  }
  if (activeComparisonRowId === rowId && anchorTr.nextElementSibling?.classList.contains('comparison-inline-row')) {
    return;
  }
  const normalizedTicker = normalizeTickerInput(ticker).trim();
  clearInlineComparisonRows({ invalidatePending: false });
  if (!normalizedTicker) return;

  let items = comparisonCache.get(normalizedTicker);
  if (!items) {
    try {
      items = await api(`/api/ticker-comparison?ticker=${encodeURIComponent(normalizedTicker)}`);
      if (requestSeq !== comparisonRequestSeq) {
        return;
      }
      comparisonCache.set(normalizedTicker, items);
    } catch (_err) {
      return;
    }
  }

  if (requestSeq !== comparisonRequestSeq) {
    return;
  }

  const otherTables = (items || []).filter((item) => item.table_id !== appState.activeTableId);
  if (!otherTables.length) return;

  const current = activeTable();
  const currentTableName = current
    ? displayAnalystName(current.table_number, current.analyst_name)
    : 'Текущая таблица';
  const actionCell = anchorTr.lastElementChild;
  const deleteBtn = actionCell?.querySelector('.row-delete-btn');
  if (deleteBtn) {
    deleteBtn.classList.add('hidden');
    deleteBtn.style.display = 'none';
  }
  actionCell?.querySelector('.comparison-anchor-label')?.remove();
  if (actionCell) {
    const label = document.createElement('span');
    label.className = 'comparison-source comparison-anchor-label';
    label.textContent = currentTableName;
    actionCell.prepend(label);
  }

  anchorTr.classList.add('ticker-compare-highlight');
  anchorTr.classList.add('comparison-anchor-row');
  activeComparisonRowId = rowId;
  let insertAfter = anchorTr;
  otherTables.forEach((item) => {
    const row = createInlineComparisonRow(item);
    row.addEventListener('mouseenter', () => {
      if (comparisonHoverHideTimer) {
        clearTimeout(comparisonHoverHideTimer);
        comparisonHoverHideTimer = null;
      }
    });
    row.addEventListener('mouseleave', () => scheduleInlineComparisonHide(anchorTr, null, 250));
    insertAfter.insertAdjacentElement('afterend', row);
    insertAfter = row;
  });
  if ((items || []).length >= 2) {
    const consensusRow = createConsensusComparisonRow(items, normalizedTicker);
    insertAfter.insertAdjacentElement('afterend', consensusRow);
  }
}

function rowToPayload(row) {
  const profitMap = row.net_profit_year_map || {};
  const dividendMap = row.dividend_year_map || {};
  return {
    table_id: row.table_id ?? appState.activeTableId,
    ticker: row.ticker || '',
    shares_billion: parseInputNumber(row.shares_billion),
    pe_avg_5y: parseInputNumber(row.pe_avg_5y),
    forecast_profit_year1_billion_rub: parseInputNumber(profitMap[yearKeyByIndex(0)]),
    forecast_profit_year2_billion_rub: parseInputNumber(profitMap[yearKeyByIndex(1)]),
    net_profit_year_map: profitMap,
    dividends_year1: parseInputNumber(dividendMap[yearKeyByIndex(0)]),
    dividends_year2: parseInputNumber(dividendMap[yearKeyByIndex(1)]),
    dividend_year_map: dividendMap,
    net_profit_source_comment: row.net_profit_source_comment || null,
  };
}

function setRowSaveStatus(tr, text, isError = false) {
  const status = tr?.querySelector('[data-cell="row_save_status"]');
  if (!status) return;
  status.textContent = text;
  status.classList.toggle('save-error', isError);
}

function updateCalculatedCells(tr, row) {
  const priceDecimals = detectDecimals(row.current_price);
  const setCellText = (cellName, value) => {
    const cell = tr.querySelector(`[data-cell="${cellName}"]`);
    if (cell) cell.textContent = value;
  };
  const setUpsideCell = (cellName, value, options = {}) => {
    const cell = tr.querySelector(`[data-cell="${cellName}"]`);
    if (!cell) return;
    cell.textContent = formatPercent(value);
    cell.classList.remove('upside-up', 'upside-up-strong', 'upside-down', 'upside-flat');
    cell.classList.add(upsideClass(value, options));
  };

  setCellText('current_price', formatCurrency(row.current_price, priceDecimals));
  setCellText('market_cap', formatCurrency(row.market_cap_billion_rub));
  setCellText('forecast_price_year1', formatCurrency(row.forecast_price_year1, priceDecimals));
  setCellText('forecast_price_year2', formatCurrency(row.forecast_price_year2, priceDecimals));
  setUpsideCell('upside_year1', row.upside_percent_year1, { isNearTerm: true });
  setUpsideCell('upside_year2', row.upside_percent_year2);
  setCellText('price_updated_at', formatPriceUpdated(row.price_updated_at));
}

async function saveRowChanges(row, tr, { force = false } = {}) {
  if (!force && !dirtyRows.has(row.id)) return;
  const existingSave = rowSaveInFlight.get(row.id);
  if (existingSave) {
    await existingSave;
    if (dirtyRows.has(row.id)) {
      return saveRowChanges(row, tr, { force });
    }
    return;
  }

  const draft = rowDrafts.get(row.id) || row;
  const draftVersion = rowDraftVersions.get(row.id) || 0;
  setRowSaveStatus(tr, 'Сохраняется…');

  const operation = api(`/api/rows/${row.id}`, {
    method: 'PUT',
    body: JSON.stringify(rowToPayload(draft)),
  });
  rowSaveInFlight.set(row.id, operation);

  try {
    const savedRow = await operation;
    Object.assign(row, savedRow);
    if ((rowDraftVersions.get(row.id) || 0) === draftVersion) {
      rowDrafts.set(row.id, { ...savedRow });
      dirtyRows.delete(row.id);
      setRowSaveStatus(tr, 'Сохранено');
    } else {
      setRowSaveStatus(tr, 'Есть новые изменения');
    }
    updateCalculatedCells(tr, row);
    setGlobalStatus('Изменения сохранены');
  } finally {
    if (rowSaveInFlight.get(row.id) === operation) {
      rowSaveInFlight.delete(row.id);
    }
  }
}

async function waitForPendingSaves() {
  if (rowSaveInFlight.size) {
    await Promise.allSettled([...rowSaveInFlight.values()]);
  }
  if (dirtyRows.size) {
    throw new Error('Есть несохранённые изменения. Дождитесь завершения автосохранения.');
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
  const [year1, year2] = activeYears();
  const sortableHeaders = [
    { element: sortTicker, key: 'ticker', label: 'Тикер' },
    { element: sortMarketCap, key: 'market_cap_billion_rub', label: 'Капитализация, млрд ₽' },
    { element: sortUpsideYear1, key: 'upside_percent_year1', label: `Доходность (${year1}), %` },
    { element: sortUpsideYear2, key: 'upside_percent_year2', label: `Доходность (${year2}), %` },
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
  const isPrimaryTable = isPrimaryActiveTable();
  const canEdit = canEditData();
  tbody.innerHTML = '';

  sortedRows.forEach((row) => {
    if (!dirtyRows.has(row.id) && !rowSaveInFlight.has(row.id)) {
      rowDrafts.set(row.id, { ...row });
    }
    const priceDecimals = detectDecimals(row.current_price);
    const sharedFieldsEditable = row.shared_fields_editable !== false;
    const lockSharedFields = !canEdit || !isPrimaryTable || !sharedFieldsEditable;
    const lockAllFields = !canEdit;
    const tr = document.createElement('tr');

    tr.innerHTML = `
      <td class="sticky-col-1"><input class="ticker-input" data-field="ticker" value="${escapeHtml(row.ticker ?? '')}" ${lockSharedFields ? 'readonly' : ''} /></td>
      <td class="readonly-cell sticky-col-2"><span data-cell="current_price">${formatCurrency(row.current_price, priceDecimals)}</span></td>
      <td><input data-field="shares_billion" value="${row.shares_billion ?? ''}" ${lockSharedFields ? 'readonly' : ''} /></td>
      <td class="readonly-cell"><span data-cell="market_cap">${formatCurrency(row.market_cap_billion_rub)}</span></td>
      <td><input data-field="pe_avg_5y" value="${row.pe_avg_5y ?? ''}" ${lockSharedFields ? 'readonly' : ''} /></td>
      <td><input data-field="forecast_profit_year1_billion_rub" value="${mapProfitByYear(row, 0) ?? ''}" ${lockAllFields ? 'readonly' : ''} /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year1">${formatCurrency(row.forecast_price_year1, priceDecimals)}</span></td>
      <td><input data-field="dividends_year1" value="${mapDividendsByYear(row, 0) ?? ''}" ${lockAllFields ? 'readonly' : ''} /></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year1, { isNearTerm: true })}" data-cell="upside_year1" title="Доходность от текущей цены с учётом всех оставшихся дивидендов до выбранного года">${formatPercent(row.upside_percent_year1)}</td>
      <td><input data-field="forecast_profit_year2_billion_rub" value="${mapProfitByYear(row, 1) ?? ''}" ${lockAllFields ? 'readonly' : ''} /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year2">${formatCurrency(row.forecast_price_year2, priceDecimals)}</span></td>
      <td><input data-field="dividends_year2" value="${mapDividendsByYear(row, 1) ?? ''}" ${lockAllFields ? 'readonly' : ''} /></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year2)}" data-cell="upside_year2" title="Доходность от текущей цены с учётом всех оставшихся дивидендов до выбранного года">${formatPercent(row.upside_percent_year2)}</td>
      <td class="readonly-cell"><span data-cell="price_updated_at">${formatPriceUpdated(row.price_updated_at)}</span></td>
      <td>
        <button data-action="delete" class="btn-danger row-delete-btn" ${canEdit && isPrimaryTable ? '' : 'disabled title="Удалять строки можно только из таблицы №1 из локальной сети"'}>Удалить</button>
        ${canEdit ? '<button data-action="comment" class="btn-note">Заметка</button>' : ''}
        <div class="row-save-status" data-cell="row_save_status"></div>
        ${row.net_profit_source_comment ? `<div class="source-note" data-cell="source_note">${escapeHtml(row.net_profit_source_comment)}</div>` : '<div class="source-note" data-cell="source_note"></div>'}
        ${row.status_message ? `<div class="status-error">${escapeHtml(row.status_message)}</div>` : ''}
      </td>
    `;

    tr.querySelectorAll('input').forEach((input) => {
      input.addEventListener('input', async () => {
        const normalizedValue = normalizeInputByField(input.dataset.field, input.value);
        if (input.value !== normalizedValue) {
          input.value = normalizedValue;
        }
        if (input.dataset.field === 'ticker') {
          applyTickerInputSizing(input);
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
          };
          const yearIndex = yearIndexMap[input.dataset.field];
          if (yearIndex !== undefined) {
            map[yearKeyByIndex(yearIndex)] = parseInputNumber(normalizedValue);
            updated.net_profit_year_map = map;
          }
        }
        if (input.dataset.field.startsWith('dividends_year')) {
          const map = { ...(updated.dividend_year_map || {}) };
          const yearIndexMap = {
            dividends_year1: 0,
            dividends_year2: 1,
          };
          const yearIndex = yearIndexMap[input.dataset.field];
          if (yearIndex !== undefined) {
            map[yearKeyByIndex(yearIndex)] = parseInputNumber(normalizedValue);
            updated.dividend_year_map = map;
          }
        }
        rowDrafts.set(row.id, updated);
        dirtyRows.add(row.id);
        rowDraftVersions.set(row.id, (rowDraftVersions.get(row.id) || 0) + 1);
        setRowSaveStatus(tr, 'Не сохранено');

        if (saveTimers.has(row.id)) {
          clearTimeout(saveTimers.get(row.id));
        }
        saveTimers.set(row.id, setTimeout(async () => {
          try {
            await saveRowChanges(row, tr);
          } catch (err) {
            setRowSaveStatus(tr, 'Ошибка сохранения', true);
            setGlobalStatus(err.message);
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
          setRowSaveStatus(tr, 'Ошибка сохранения', true);
          setGlobalStatus(err.message);
        }
      });
    });

    const tickerInput = tr.querySelector('input[data-field="ticker"]');
    applyTickerInputSizing(tickerInput);
    tickerInput?.addEventListener('mouseenter', () => {
      const draft = rowDrafts.get(row.id) || row;
      showInlineComparisonRows(tr, draft.ticker, row.id);
    });
    tickerInput?.addEventListener('mouseleave', () => {
      scheduleInlineComparisonHide(tr, tickerInput, 120);
    });
    tickerInput?.addEventListener('blur', clearInlineComparisonRows);

    tr.querySelector('[data-action="delete"]').addEventListener('click', async () => {
      if (!canEditData()) {
        alert('Удаление доступно только из локальной сети.');
        return;
      }
      if (!isPrimaryActiveTable()) {
        alert('Удалять строки можно только из таблицы №1.');
        return;
      }
      try {
        await api(`/api/rows/${row.id}`, { method: 'DELETE' });
        await loadRows();
      } catch (err) {
        alert(err.message);
      }
    });

    tr.querySelector('[data-action="comment"]')?.addEventListener('click', async () => {
      const draft = rowDrafts.get(row.id) || row;
      const nextValue = prompt(
        'Источник / комментарий к прогнозу:',
        draft.net_profit_source_comment || '',
      );
      if (nextValue === null) return;
      const updated = {
        ...draft,
        net_profit_source_comment: nextValue.trim() || null,
      };
      rowDrafts.set(row.id, updated);
      dirtyRows.add(row.id);
      rowDraftVersions.set(row.id, (rowDraftVersions.get(row.id) || 0) + 1);
      const note = tr.querySelector('[data-cell="source_note"]');
      if (note) note.textContent = updated.net_profit_source_comment || '';
      try {
        await saveRowChanges(row, tr);
      } catch (err) {
        setRowSaveStatus(tr, 'Ошибка сохранения', true);
        setGlobalStatus(err.message);
      }
    });

    tbody.appendChild(tr);
  });
}

document.addEventListener('click', clearInlineComparisonRows, true);
window.addEventListener('blur', clearInlineComparisonRows);

tableSelect?.addEventListener('change', async () => {
  try {
    await waitForPendingSaves();
    appState.activeTableId = Number(tableSelect.value);
    renderTableSelector();
    await loadRows();
  } catch (err) {
    renderTableSelector();
    setGlobalStatus(err.message);
  }
});

saveAnalystBtn?.addEventListener('click', async () => {
  if (!canEditData()) {
    alert('Редактирование доступно только из локальной сети.');
    return;
  }
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
  if (!canEditData()) {
    alert('Редактирование доступно только из локальной сети.');
    return;
  }
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
  if (!canEditData()) {
    alert('Редактирование доступно только из локальной сети.');
    return;
  }
  const current = activeTable();
  if (!current || current.table_number === 1) return;
  await api(`/api/tables/${current.id}/make-primary`, { method: 'POST' });
  await loadTables();
  appState.activeTableId = current.id;
  renderTableSelector();
  await loadRows();
});

deleteTableBtn?.addEventListener('click', async () => {
  if (!canEditData()) {
    alert('Редактирование доступно только из локальной сети.');
    return;
  }
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
  if (!canEditData()) return;
  const current = activeTable();
  if (!current) return;
  await waitForPendingSaves();
  await api(`/api/tables/${current.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ forecast_start_year: current.forecast_start_year + 1 }),
  });
  await loadTables();
  await loadRows();
});

shiftYearBackBtn?.addEventListener('click', async () => {
  if (!canEditData()) return;
  const current = activeTable();
  if (!current) return;
  await waitForPendingSaves();
  await api(`/api/tables/${current.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ forecast_start_year: current.forecast_start_year - 1 }),
  });
  await loadTables();
  await loadRows();
});

refreshPricesBtn?.addEventListener('click', async () => {
  if (!canEditData() || !appState.activeTableId) return;
  try {
    await waitForPendingSaves();
    setGlobalStatus('Обновляем котировки MOEX…');
    const rows = await api(`/api/rows/refresh?table_id=${appState.activeTableId}`, {
      method: 'POST',
    });
    renderRows(rows);
    setGlobalStatus(`Котировки обновлены: ${new Date().toLocaleTimeString('ru-RU')}`);
  } catch (err) {
    setGlobalStatus(err.message);
  }
});

addRowBtn.addEventListener('click', async () => {
  if (!canEditData()) {
    alert('Редактирование доступно только из локальной сети.');
    return;
  }
  if (!isPrimaryActiveTable()) {
    alert('Добавлять строки можно только в таблице №1.');
    return;
  }
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
        dividends_year1: null,
        dividends_year2: null,
      }),
    });
    await loadRows();
  } catch (err) {
    alert(err.message);
  }
});

exportDataBtn?.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/data/export');
    if (!res.ok) {
      throw new Error(`Ошибка API: ${res.status}`);
    }
    const blob = await res.blob();
    const suggestedName =
      res.headers.get('Content-Disposition')?.match(/filename=\"?([^\";]+)\"?/)?.[1] || 'moex-data.json';

    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = suggestedName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
    alert(`Файл выгрузки готов: ${suggestedName}`);
  } catch (err) {
    alert(err.message);
  }
});

importDataBtn?.addEventListener('click', async () => {
  if (!canEditData()) {
    alert('Импорт доступен только из локальной сети.');
    return;
  }
  importDataFileInput?.click();
});

importDataFileInput?.addEventListener('change', async () => {
  const selectedFile = importDataFileInput.files?.[0];
  if (!selectedFile) return;

  const approved = confirm(`Загрузить данные из файла «${selectedFile.name}»?\n\nТекущие данные в БД будут заменены.`);
  if (!approved) {
    importDataFileInput.value = '';
    return;
  }

  try {
    const formData = new FormData();
    formData.append('file', selectedFile);
    const result = await api('/api/data/import', {
      method: 'POST',
      body: formData,
    });
    await loadTables();
    appState.activeTableId = appState.tables[0]?.id ?? null;
    renderTableSelector();
    await loadRows();
    alert(`Загрузка завершена.\nТаблиц: ${result.tables_count}, строк: ${result.rows_count}`);
  } catch (err) {
    alert(err.message);
  } finally {
    importDataFileInput.value = '';
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
    await restoreSession();
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
