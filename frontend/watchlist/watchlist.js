(() => {
  const body = document.getElementById('watchlist-body');
  const tableWrap = document.querySelector('[data-watchlist-table]');
  const empty = document.querySelector('[data-watchlist-empty]');
  const status = document.getElementById('watchlist-status');
  if (!body || !tableWrap || !empty || !status) return;

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

  function showEmpty(title, message, state = 'empty') {
    tableWrap.hidden = true;
    body.innerHTML = '';
    empty.hidden = false;
    empty.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
    status.textContent = state === 'error' ? 'Ошибка загрузки' : 'Нет бумаг';
    status.dataset.state = state;
  }

  function render(rows, volumeRows, primaryTable) {
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
      const signalStatus = latest?.signal_status;

      return `
        <tr data-watchlist-ticker="${escapeHtml(ticker)}">
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

    empty.hidden = true;
    tableWrap.hidden = false;
    status.textContent = `Бумаги: ${rows.length} · объёмы: ${matchedVolumes}`;
    status.dataset.state = matchedVolumes === rows.length ? 'complete' : 'partial';
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

      const volumeRows = volumesResult.status === 'fulfilled' ? volumesResult.value : [];
      render(rowsResult.value, volumeRows, primaryTable);
      if (volumesResult.status !== 'fulfilled') {
        status.textContent = `Бумаги: ${rowsResult.value.length} · объёмы недоступны`;
        status.dataset.state = 'partial';
      }
    } catch (_error) {
      showEmpty('Не удалось загрузить Watchlist', 'Проверьте доступность API и повторите загрузку страницы.', 'error');
    }
  }

  load();
})();
