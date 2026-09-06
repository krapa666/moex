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
  let syncButton = null;
  let syncStatus = null;
  let backtestStatus = null;
  let backtestEmpty = null;
  let backtestTableWrap = null;
  let backtestBody = null;

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

  function formatDelta(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    const number = Number(value);
    if (Math.abs(number) < 0.05) return '0 п.п.';
    const sign = number > 0 ? '+' : '';
    return `${sign}${formatNumber(number, 1)} п.п.`;
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

  function ensureBacktestSection() {
    if (backtestBody) return;

    const section = document.createElement('div');
    section.className = 'actual-facts consensus-backtest';
    section.dataset.consensusBacktest = '';

    const heading = document.createElement('div');
    heading.className = 'source-accuracy-controls';

    const titleWrap = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = 'Backtest консенсуса чистой прибыли';
    const description = document.createElement('p');
    description.textContent = 'Один и тот же исторический набор сравнивает медиану, среднее и консервативный accuracy-weighted вариант. Положительная Δ означает улучшение sMAPE относительно медианы; боевой consensus не меняется.';
    titleWrap.append(title, description);

    backtestStatus = document.createElement('span');
    backtestStatus.className = 'analytics-status';
    backtestStatus.dataset.consensusBacktestStatus = '';
    backtestStatus.setAttribute('role', 'status');
    backtestStatus.setAttribute('aria-live', 'polite');
    backtestStatus.textContent = 'Расчёт…';
    heading.append(titleWrap, backtestStatus);

    backtestEmpty = document.createElement('div');
    backtestEmpty.className = 'source-accuracy-empty';
    backtestEmpty.dataset.consensusBacktestEmpty = '';
    backtestEmpty.hidden = true;

    backtestTableWrap = document.createElement('div');
    backtestTableWrap.className = 'source-accuracy-table-wrap';
    backtestTableWrap.dataset.consensusBacktestTableWrap = '';
    backtestTableWrap.hidden = true;

    const table = document.createElement('table');
    table.className = 'source-accuracy-table';
    table.innerHTML = `
      <thead>
        <tr>
          <th>Метод</th>
          <th>Набл.</th>
          <th>Бумаг</th>
          <th>Лет</th>
          <th>Md sMAPE</th>
          <th>Δ Md к медиане</th>
          <th>Mean sMAPE</th>
          <th>MAE, млрд ₽</th>
          <th>Bias, млрд ₽</th>
          <th>Знак верен</th>
        </tr>
      </thead>
    `;
    backtestBody = document.createElement('tbody');
    backtestBody.dataset.consensusBacktestBody = '';
    table.append(backtestBody);
    backtestTableWrap.append(table);

    section.append(heading, backtestEmpty, backtestTableWrap);
    tableWrap.insertAdjacentElement('afterend', section);
  }

  function renderBacktest(result) {
    ensureBacktestSection();
    backtestBody.replaceChildren();
    const methods = Array.isArray(result?.methods) ? result.methods : [];
    if (!methods.length || !Number(result?.observations || 0)) {
      backtestEmpty.hidden = false;
      backtestTableWrap.hidden = true;
      backtestEmpty.textContent = 'Пока нет годов, где на одной и той же отсечке доступны минимум два прогноза ЧП и канонический факт.';
      backtestStatus.textContent = 'Недостаточно истории';
      return;
    }

    backtestEmpty.hidden = true;
    backtestTableWrap.hidden = false;
    for (const row of methods) {
      const tr = document.createElement('tr');
      if (row.method === 'weighted') tr.classList.add('accuracy-source');
      tr.append(
        createCell(row.label || row.method || '—', 'accuracy-source'),
        createCell(String(row.samples ?? '—')),
        createCell(String(row.tickers ?? '—')),
        createCell(String(row.years ?? '—')),
        createCell(formatPercent(row.median_smape_percent)),
        createCell(formatDelta(row.median_smape_delta_vs_median_pp)),
        createCell(formatPercent(row.mean_smape_percent)),
        createCell(formatNumber(row.mean_absolute_error_billion_rub, 2)),
        createCell(formatNumber(row.mean_bias_billion_rub, 2)),
        createCell(formatPercent(row.sign_accuracy_percent)),
      );
      backtestBody.append(tr);
    }

    backtestStatus.textContent = `${result.observations} наблюдений · ${result.tickers} бумаг · ${result.years} лет`;
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

  async function loadBacktest() {
    ensureBacktestSection();
    backtestStatus.textContent = 'Расчёт…';
    const snapshot = snapshotSelect.value || 'pre_year';
    try {
      const result = await fetchJson(
        `/api/analytics/consensus-backtest?snapshot=${encodeURIComponent(snapshot)}`,
      );
      renderBacktest(result || {});
    } catch (error) {
      backtestEmpty.hidden = false;
      backtestTableWrap.hidden = true;
      backtestEmpty.textContent = error.message;
      backtestStatus.textContent = 'Ошибка';
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

  function ensureSyncControls() {
    if (syncButton) return;
    const controls = document.createElement('div');
    controls.className = 'source-accuracy-controls';
    controls.dataset.actualSyncControls = '';

    syncButton = document.createElement('button');
    syncButton.type = 'button';
    syncButton.className = 'btn';
    syncButton.dataset.actualSyncButton = '';
    syncButton.textContent = 'Синхронизировать MOEX CCI';

    syncStatus = document.createElement('span');
    syncStatus.className = 'actual-result-form-status';
    syncStatus.dataset.actualSyncStatus = '';
    syncStatus.setAttribute('role', 'status');
    syncStatus.setAttribute('aria-live', 'polite');

    controls.append(syncButton, syncStatus);
    adminBlock.insertBefore(controls, form);
    syncButton.addEventListener('click', syncActuals);
  }

  async function loadSyncStatus() {
    ensureSyncControls();
    syncButton.disabled = true;
    syncStatus.textContent = 'Проверка MOEX CCI…';
    try {
      const source = await fetchJson('/api/analytics/actual-net-profits/sync-status');
      if (!source.enabled) {
        syncStatus.textContent = 'MOEX CCI: автосинхронизация отключена';
        return;
      }
      if (!source.configured) {
        syncStatus.textContent = 'MOEX CCI: нужны учётные данные в .env';
        return;
      }
      syncButton.disabled = false;
      syncStatus.textContent = `MOEX CCI: готово · ${source.years_back} лет · каждые ${formatNumber(source.interval_hours, 1)} ч`;
    } catch (error) {
      syncStatus.textContent = error.message;
    }
  }

  async function syncActuals() {
    syncButton.disabled = true;
    syncStatus.textContent = 'Синхронизация MOEX CCI…';
    try {
      const result = await fetchJson('/api/analytics/actual-net-profits/sync', { method: 'POST' });
      const changed = Number(result.records_created || 0) + Number(result.records_updated || 0);
      syncStatus.textContent = `MOEX CCI: обновлено ${changed} · без изменений ${result.records_unchanged || 0} · защищено ${result.records_protected || 0}`;
      await Promise.all([loadFacts(), loadAccuracy(), loadBacktest()]);
    } catch (error) {
      syncStatus.textContent = error.message;
    } finally {
      await loadSyncStatus();
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
      formStatus.textContent = `${ticker} ${fiscalYear}: факт сохранён вручную`;
      form.querySelector('[name="net_profit_billion_rub"]').value = '';
      await Promise.all([loadFacts(), loadAccuracy(), loadBacktest()]);
    } catch (error) {
      formStatus.textContent = error.message;
    }
  }

  async function reloadSnapshotPanels() {
    await Promise.all([loadAccuracy(), loadBacktest()]);
  }

  async function init() {
    const access = window.MoexAnalyticsAccess;
    const accessState = access ? await access.load() : { isAdmin: false };
    adminBlock.hidden = !accessState.isAdmin;

    const yearInput = form.querySelector('[name="fiscal_year"]');
    if (yearInput && !yearInput.value) yearInput.value = String(new Date().getFullYear() - 1);

    ensureBacktestSection();
    snapshotSelect.addEventListener('change', reloadSnapshotPanels);
    form.addEventListener('submit', saveFact);
    const initialLoads = [loadFacts(), loadAccuracy(), loadBacktest()];
    if (accessState.isAdmin) initialLoads.push(loadSyncStatus());
    await Promise.all(initialLoads);
  }

  init().catch((error) => {
    status.textContent = 'Ошибка';
    empty.hidden = false;
    empty.textContent = error.message;
  });
})();
