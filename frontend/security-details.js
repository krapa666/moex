(() => {
  const tbody = document.getElementById('rows-table-body');
  const overlay = document.getElementById('security-detail-overlay');
  if (!tbody || !overlay) return;

  const detail = (name) => overlay.querySelector(`[data-detail="${name}"]`);
  const closeTargets = overlay.querySelectorAll('[data-detail-close]');
  const detailInputs = overlay.querySelectorAll('[data-detail-input]');
  const globalStatus = document.getElementById('global-status');
  const requestedTicker = new URLSearchParams(window.location.search).get('ticker')?.trim() || '';
  let deepLinkHandled = !requestedTicker;
  let lastTrigger = null;
  let activeRow = null;

  const inputBindings = {
    shares: {
      selector: 'input[data-field="shares_billion"]',
    },
    dividends1: {
      selector: 'input[data-field="dividends_year1"]',
      yieldCell: '[data-cell="dividend_yield_year1"]',
      yieldDetail: 'dividend_yield1',
    },
    dividends2: {
      selector: 'input[data-field="dividends_year2"]',
      yieldCell: '[data-cell="dividend_yield_year2"]',
      yieldDetail: 'dividend_yield2',
    },
  };

  const text = (row, selector) => row.querySelector(selector)?.textContent?.trim() || '—';
  const value = (row, selector) => row.querySelector(selector)?.value?.trim() || '—';

  function tickerFromUrl() {
    return new URLSearchParams(window.location.search).get('ticker')?.trim() || '';
  }

  function setTickerQuery(ticker, mode = 'replace') {
    if (mode === 'none') return;
    const url = new URL(window.location.href);
    if (ticker && ticker !== '—') {
      url.searchParams.set('ticker', ticker);
    } else {
      url.searchParams.delete('ticker');
    }
    const nextUrl = `${url.pathname}${url.search}${url.hash}`;
    const nextState = {
      ...(window.history.state || {}),
      moexTickerView: mode === 'push' && ticker ? 'forecast' : null,
    };
    if (mode === 'push') {
      window.history.pushState(nextState, '', nextUrl);
    } else {
      window.history.replaceState(nextState, '', nextUrl);
    }
  }

  function setDetail(name, nextValue) {
    const element = detail(name);
    if (!element) return;
    if (element.matches('input')) {
      element.value = nextValue === '—' ? '' : (nextValue || '');
      return;
    }
    element.textContent = nextValue || '—';
  }

  function syncEditableField(name, row) {
    const binding = inputBindings[name];
    const drawerInput = detail(name);
    const sourceInput = binding ? row.querySelector(binding.selector) : null;
    if (!drawerInput || !drawerInput.matches('input')) return;

    drawerInput.value = sourceInput?.value ?? '';
    drawerInput.readOnly = !sourceInput || sourceInput.readOnly || sourceInput.disabled;
    drawerInput.title = drawerInput.readOnly ? 'Поле недоступно для редактирования в текущем режиме' : '';
  }

  function findTickerRow(ticker) {
    const normalizedTicker = String(ticker || '').toLocaleUpperCase('ru');
    if (!normalizedTicker) return null;
    return [...tbody.querySelectorAll(':scope > tr:not(.comparison-inline-row)')]
      .find((row) => value(row, 'input[data-field="ticker"]').toLocaleUpperCase('ru') === normalizedTicker) || null;
  }

  function openDetails(row, trigger, historyMode = 'replace') {
    activeRow = row;
    lastTrigger = trigger;
    const ticker = value(row, 'input[data-field="ticker"]');
    const year1 = document.getElementById('header-year1-group')?.textContent?.trim() || 'Год 1';
    const year2 = document.getElementById('header-year2-group')?.textContent?.trim() || 'Год 2';

    setTickerQuery(ticker, historyMode);
    setDetail('ticker', ticker);
    setDetail('subtitle', `${text(row, '[data-cell="current_price"]')} · обновлено ${text(row, '[data-cell="price_updated_at"]')}`);
    setDetail('current_price', text(row, '[data-cell="current_price"]'));
    syncEditableField('shares', row);
    setDetail('market_cap', text(row, '[data-cell="market_cap"]'));
    setDetail('pe', value(row, 'input[data-field="pe_avg_5y"]'));
    setDetail('updated', text(row, '[data-cell="price_updated_at"]'));

    setDetail('year1', year1);
    setDetail('profit1', value(row, 'input[data-field="forecast_profit_year1_billion_rub"]'));
    setDetail('price1', text(row, '[data-cell="forecast_price_year1"]'));
    syncEditableField('dividends1', row);
    setDetail('dividend_yield1', text(row, '[data-cell="dividend_yield_year1"]'));
    setDetail('upside1', text(row, '[data-cell="upside_year1"]'));

    setDetail('year2', year2);
    setDetail('profit2', value(row, 'input[data-field="forecast_profit_year2_billion_rub"]'));
    setDetail('price2', text(row, '[data-cell="forecast_price_year2"]'));
    syncEditableField('dividends2', row);
    setDetail('dividend_yield2', text(row, '[data-cell="dividend_yield_year2"]'));
    setDetail('upside2', text(row, '[data-cell="upside_year2"]'));

    const source = text(row, '[data-cell="source_note"]');
    setDetail('source', source === '—' ? 'Источник или комментарий не указан.' : source);

    const status = text(row, '.status-error');
    const statusBlock = overlay.querySelector('[data-detail-status-block]');
    if (statusBlock) {
      statusBlock.hidden = status === '—';
      setDetail('status', status);
    }

    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('security-detail-open');
    overlay.querySelector('.security-detail-close')?.focus();
  }

  function closeDetailsVisual({ restoreFocus = true } = {}) {
    if (overlay.hidden) return;
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('security-detail-open');
    activeRow = null;
    if (restoreFocus) lastTrigger?.focus();
    lastTrigger = null;
  }

  function closeDetails() {
    if (overlay.hidden) return;
    if (window.history.state?.moexTickerView === 'forecast') {
      window.history.back();
      return;
    }
    closeDetailsVisual();
    setTickerQuery('', 'replace');
  }

  function openRequestedTicker({ finalizeMissing = false } = {}) {
    if (deepLinkHandled) return;
    const targetRow = findTickerRow(requestedTicker);
    const button = targetRow?.querySelector('[data-action="details"]');
    if (targetRow && button) {
      deepLinkHandled = true;
      openDetails(targetRow, button, 'replace');
      return;
    }
    if (!finalizeMissing) return;

    deepLinkHandled = true;
    setTickerQuery('', 'replace');
    if (globalStatus) {
      globalStatus.textContent = `Тикер ${requestedTicker.toLocaleUpperCase('ru')} не найден в текущей таблице`;
    }
  }

  function syncWithHistory() {
    const ticker = tickerFromUrl();
    if (!ticker) {
      closeDetailsVisual({ restoreFocus: false });
      return;
    }
    const targetRow = findTickerRow(ticker);
    const button = targetRow?.querySelector('[data-action="details"]');
    if (targetRow && button) openDetails(targetRow, button, 'none');
  }

  function attachButtons() {
    tbody.querySelectorAll(':scope > tr:not(.comparison-inline-row)').forEach((row) => {
      if (row.querySelector('[data-action="details"]')) return;
      const actionCell = row.lastElementChild;
      if (!actionCell) return;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn-note btn-detail';
      button.dataset.action = 'details';
      button.textContent = 'Подробнее';
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        openDetails(row, button, 'push');
      });
      actionCell.prepend(button);
    });
    openRequestedTicker();
  }

  detailInputs.forEach((drawerInput) => {
    const name = drawerInput.dataset.detailInput;
    const binding = inputBindings[name];
    if (!binding) return;

    drawerInput.addEventListener('input', () => {
      if (!activeRow || drawerInput.readOnly) return;
      const sourceInput = activeRow.querySelector(binding.selector);
      if (!sourceInput || sourceInput.readOnly || sourceInput.disabled) return;

      sourceInput.value = drawerInput.value;
      sourceInput.dispatchEvent(new Event('input', { bubbles: true }));
      drawerInput.value = sourceInput.value;

      if (binding.yieldCell && binding.yieldDetail) {
        setDetail(binding.yieldDetail, text(activeRow, binding.yieldCell));
      }
    });

    drawerInput.addEventListener('blur', () => {
      if (!activeRow || drawerInput.readOnly) return;
      const sourceInput = activeRow.querySelector(binding.selector);
      if (!sourceInput || sourceInput.readOnly || sourceInput.disabled) return;
      sourceInput.dispatchEvent(new Event('blur'));
    });
  });

  closeTargets.forEach((element) => element.addEventListener('click', closeDetails));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !overlay.hidden) closeDetails();
  });
  window.addEventListener('popstate', syncWithHistory);

  const observer = new MutationObserver(attachButtons);
  observer.observe(tbody, { childList: true });

  const statusObserver = globalStatus && !deepLinkHandled
    ? new MutationObserver(() => {
      if (globalStatus.textContent.startsWith('Обновлено:')) {
        attachButtons();
        openRequestedTicker({ finalizeMissing: true });
      }
    })
    : null;
  statusObserver?.observe(globalStatus, { childList: true, characterData: true, subtree: true });

  attachButtons();
})();
