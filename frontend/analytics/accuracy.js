(() => {
  const panel = document.querySelector('[data-source-accuracy]');
  if (!panel) return;

  const snapshotSelect = panel.querySelector('[data-accuracy-snapshot]');
  const status = panel.querySelector('[data-accuracy-status]');
  const empty = panel.querySelector('[data-accuracy-empty]');
  const tableWrap = panel.querySelector('[data-accuracy-table-wrap]');
  const tableBody = panel.querySelector('[data-accuracy-table-body]');
  const factsBody = panel.querySelector('[data-actual-facts-body]');
  const factsEmpty = panel.querySelector('[data-actual-facts-empty]');
  const adminBlock = panel.querySelector('[data-actual-admin]');
  const form = panel.querySelector('[data-actual-form]');
  const formStatus = panel.querySelector('[data-actual-form-status]');
  const minSamples = 5;

  function formatNumber(value, digits = 1) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    return Number(value).toLocaleString('ru-RU', {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    });
  }

  function formatPercent(value) {
    const formatted = formatNumber(value, 1);
    return formatted === '—' ? formatted : `${formatted}%`;
  }

  function createCell(text, className = '') {
    const td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      let detail = `Ошибка API: ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) detail = String(payload.detail);
      } catch (_error) {
        // Keep the HTTP status fallback.
      }
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function displaySource(row) {
    const access = window.MoexAnalyticsAccess;
    if (!access) return row.analyst_name || 'Источник';
    const tableNumber = access.tableNumberForId(row.table_id);
    return access.displayAnalystName(tableNumber, row.analyst_name);
  }

  function renderAccuracy(rows) {
    tableBody.replaceChildren();
    if (!rows.length) {
      empty.hidden = false;
      tableWrap.hidden = true;
      empty.textContent = 'Пока нет сопоставимых пар «прогноз → факт» для выбранного среза.';
      return;
    }

    empty.hidden = true;
    tableWrap.hidden = false;
    for (const row of rows) {
      const tr = document.createElement('tr');
      if (!row.eligible) tr.classList.add('accuracy-row-unranked');
      tr.append(
        createCell(row.rank ? String(row.rank) : '—', 'accuracy-rank'),
        createCell(displaySource(row), 'accuracy-source'),
        createCell(String(row.samples)),
        createCell(String(row.tickers)),
        createCell(formatPercent(row.median_smape_percent)),
        createCell(formatPercent(row.mean_smape_percent)),
        createCell(formatPercent(row.sign_accuracy_percent)),
        createCell(formatNumber(row.mean_absolute_error_billion_rub, 2)),
        createCell(formatNumber(row.mean_bias_billion_rub, 2)),
        createCell(row.eligible ? 'в рейтинге' : `< ${minSamples} наблюдений`, 'accuracy-state'),
      );
      tableBody.append(tr);
    }
  }

  function renderFacts(rows) {
    factsBody.replaceChildren();
    factsEmpty.hidden = Boolean(rows.length);
    for (const row of rows) {
      const tr = document.createElement('tr');
      tr.append(
        createCell(row.ticker),
        createCell(String(row.fiscal_year)),
        createCell(formatNumber(row.net_profit_billion_rub, 3)),
        createCell(row.source_name || '—'),
      );
      factsBody.append(tr);
    }
  }

  async function loadAccuracy() {
    status.textContent = 'Расчёт…';
    const snapshot = snapshotSelect.value || 'pre_year';
    try {
      const rows = await fetchJson(
        `/api/analytics/source-accuracy?snapshot=${encodeURIComponent(snapshot)}&min_samples=${minSamples}`,
      );
      renderAccuracy(Array.isArray(rows) ? rows : []);
      const ranked = rows.filter((row) => row.eligible).length;
      status.textContent = rows.length
        ? `${ranked} в рейтинге · минимум ${minSamples} наблюдений`
        : 'Недостаточно истории';
    } catch (error) {
      empty.hidden = false;
      tableWrap.hidden = true;
      empty.textContent = error.message;
      status.textContent = 'Ошибка';
    }
  }

  async function loadFacts() {
    try {
      const rows = await fetchJson('/api/analytics/actual-net-profits?limit=20');
      renderFacts(Array.isArray(rows) ? rows : []);
    } catch (error) {
      factsEmpty.hidden = false;
      factsEmpty.textContent = error.message;
    }
  }

  async function saveFact(event) {
    event.preventDefault();
    const data = new FormData(form);
    const ticker = String(data.get('ticker') || '').trim().toUpperCase();
    const fiscalYear = Number(data.get('fiscal_year'));
    const netProfit = Number(String(data.get('net_profit_billion_rub') || '').replace(',', '.'));
    const sourceName = String(data.get('source_name') || '').trim();
    const sourceUrl = String(data.get('source_url') || '').trim();

    if (!ticker || !Number.isInteger(fiscalYear) || !Number.isFinite(netProfit) || !sourceName) {
      formStatus.textContent = 'Заполните тикер, год, факт ЧП и источник.';
      return;
    }

    formStatus.textContent = 'Сохранение…';
    try {
      await fetchJson(`/api/analytics/actual-net-profits/${encodeURIComponent(ticker)}/${fiscalYear}`, {
        method: 'PUT',
        body: JSON.stringify({
          net_profit_billion_rub: netProfit,
          source_name: sourceName,
          source_url: sourceUrl || null,
        }),
      });
      formStatus.textContent = `${ticker} ${fiscalYear}: факт сохранён`;
      form.querySelector('[name="net_profit_billion_rub"]').value = '';
      await Promise.all([loadFacts(), loadAccuracy()]);
    } catch (error) {
      formStatus.textContent = error.message;
    }
  }

  async function init() {
    const access = window.MoexAnalyticsAccess;
    const accessState = access ? await access.load() : { isAdmin: false };
    adminBlock.hidden = !accessState.isAdmin;

    const yearInput = form.querySelector('[name="fiscal_year"]');
    if (yearInput && !yearInput.value) yearInput.value = String(new Date().getFullYear() - 1);

    snapshotSelect.addEventListener('change', loadAccuracy);
    form.addEventListener('submit', saveFact);
    await Promise.all([loadFacts(), loadAccuracy()]);
  }

  init().catch((error) => {
    status.textContent = 'Ошибка';
    empty.hidden = false;
    empty.textContent = error.message;
  });
})();
