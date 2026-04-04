const tbody = document.getElementById('rows-table-body');
const addRowBtn = document.getElementById('add-row-btn');
const globalStatus = document.getElementById('global-status');
const sortButtons = document.querySelectorAll('.th-sort');
const sortTicker = document.getElementById('sort-ticker');
const sortMarketCap = document.getElementById('sort-market-cap');
const sortUpsideYear1 = document.getElementById('sort-upside-year1');
const sortUpsideYear2 = document.getElementById('sort-upside-year2');
const sortUpsideYear3 = document.getElementById('sort-upside-year3');

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'medium',
});
const saveTimers = new Map();
const rowDrafts = new Map();
const dirtyRows = new Set();
const sortState = { key: null, direction: 'asc' };
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

async function loadRows() {
  setGlobalStatus('Загрузка данных...');
  const maxAttempts = 5;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const rows = await api('/api/rows');
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

function rowToPayload(row) {
  return {
    ticker: row.ticker || '',
    shares_billion: parseInputNumber(row.shares_billion),
    pe_avg_5y: parseInputNumber(row.pe_avg_5y),
    forecast_profit_year1_billion_rub: parseInputNumber(row.forecast_profit_year1_billion_rub),
    forecast_profit_year2_billion_rub: parseInputNumber(row.forecast_profit_year2_billion_rub),
    forecast_profit_year3_billion_rub: parseInputNumber(row.forecast_profit_year3_billion_rub),
    net_profit_source_comment: row.net_profit_source_comment || null,
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
  setUpsideCell('upside_year1', row.upside_percent_year1);
  setUpsideCell('upside_year2', row.upside_percent_year2);
  setUpsideCell('upside_year3', row.upside_percent_year3);
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
  const sortableHeaders = [
    { element: sortTicker, key: 'ticker', label: 'Тикер' },
    { element: sortMarketCap, key: 'market_cap_billion_rub', label: 'Капитализация, млрд ₽' },
    { element: sortUpsideYear1, key: 'upside_percent_year1', label: 'Upside (2026), %' },
    { element: sortUpsideYear2, key: 'upside_percent_year2', label: 'Upside (2027), %' },
    { element: sortUpsideYear3, key: 'upside_percent_year3', label: 'Upside (2028), %' },
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
    const tr = document.createElement('tr');

    tr.innerHTML = `
      <td><input data-field="ticker" value="${row.ticker ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="current_price">${formatCurrency(row.current_price, priceDecimals)}</span></td>
      <td><input data-field="shares_billion" value="${row.shares_billion ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="market_cap">${formatCurrency(row.market_cap_billion_rub)}</span></td>
      <td><input data-field="pe_avg_5y" value="${row.pe_avg_5y ?? ''}" /></td>
      <td><input data-field="forecast_profit_year1_billion_rub" value="${row.forecast_profit_year1_billion_rub ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year1">${formatCurrency(row.forecast_price_year1, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year1)}" data-cell="upside_year1">${formatPercent(row.upside_percent_year1)}</td>
      <td><input data-field="forecast_profit_year2_billion_rub" value="${row.forecast_profit_year2_billion_rub ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year2">${formatCurrency(row.forecast_price_year2, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year2)}" data-cell="upside_year2">${formatPercent(row.upside_percent_year2)}</td>
      <td><input data-field="forecast_profit_year3_billion_rub" value="${row.forecast_profit_year3_billion_rub ?? ''}" /></td>
      <td class="readonly-cell"><span data-cell="forecast_price_year3">${formatCurrency(row.forecast_price_year3, priceDecimals)}</span></td>
      <td class="readonly-cell ${upsideClass(row.upside_percent_year3)}" data-cell="upside_year3">${formatPercent(row.upside_percent_year3)}</td>
      <td><input data-field="net_profit_source_comment" value="${row.net_profit_source_comment ?? ''}" /></td>
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

addRowBtn.addEventListener('click', async () => {
  try {
    await api('/api/rows', {
      method: 'POST',
      body: JSON.stringify({
        ticker: '',
        shares_billion: null,
        pe_avg_5y: null,
        forecast_profit_year1_billion_rub: null,
        forecast_profit_year2_billion_rub: null,
        forecast_profit_year3_billion_rub: null,
        net_profit_source_comment: null,
      }),
    });
    await loadRows();
  } catch (err) {
    alert(err.message);
  }
});

setInterval(async () => {
  try {
    await api('/api/rows/refresh', { method: 'POST' });
    if (!isEditingInput()) {
      await loadRows();
    } else {
      setGlobalStatus('Фоновое обновление выполнено (применится после выхода из поля)');
    }
  } catch (err) {
    console.error('Не удалось обновить цены:', err);
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

updateSortIndicators();

loadRows().catch((err) => {
  console.error(err);
  setGlobalStatus('Ошибка загрузки');
  alert(`Не удалось загрузить данные. Проверьте, что backend поднят и доступен: ${err.message}`);
});
