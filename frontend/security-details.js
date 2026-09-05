(() => {
  const tbody = document.getElementById('rows-table-body');
  const overlay = document.getElementById('security-detail-overlay');
  if (!tbody || !overlay) return;

  const detail = (name) => overlay.querySelector(`[data-detail="${name}"]`);
  const closeTargets = overlay.querySelectorAll('[data-detail-close]');
  let lastTrigger = null;

  const text = (row, selector) => row.querySelector(selector)?.textContent?.trim() || '—';
  const value = (row, selector) => row.querySelector(selector)?.value?.trim() || '—';

  function setDetail(name, nextValue) {
    const element = detail(name);
    if (element) element.textContent = nextValue || '—';
  }

  function openDetails(row, trigger) {
    lastTrigger = trigger;
    const ticker = value(row, 'input[data-field="ticker"]');
    const year1 = document.getElementById('header-year1-group')?.textContent?.trim() || 'Год 1';
    const year2 = document.getElementById('header-year2-group')?.textContent?.trim() || 'Год 2';

    setDetail('ticker', ticker);
    setDetail('subtitle', `${text(row, '[data-cell="current_price"]')} · обновлено ${text(row, '[data-cell="price_updated_at"]')}`);
    setDetail('current_price', text(row, '[data-cell="current_price"]'));
    setDetail('shares', value(row, 'input[data-field="shares_billion"]'));
    setDetail('market_cap', text(row, '[data-cell="market_cap"]'));
    setDetail('pe', value(row, 'input[data-field="pe_avg_5y"]'));
    setDetail('updated', text(row, '[data-cell="price_updated_at"]'));

    setDetail('year1', year1);
    setDetail('profit1', value(row, 'input[data-field="forecast_profit_year1_billion_rub"]'));
    setDetail('price1', text(row, '[data-cell="forecast_price_year1"]'));
    setDetail('dividends1', value(row, 'input[data-field="dividends_year1"]'));
    setDetail('dividend_yield1', text(row, '[data-cell="dividend_yield_year1"]'));
    setDetail('upside1', text(row, '[data-cell="upside_year1"]'));

    setDetail('year2', year2);
    setDetail('profit2', value(row, 'input[data-field="forecast_profit_year2_billion_rub"]'));
    setDetail('price2', text(row, '[data-cell="forecast_price_year2"]'));
    setDetail('dividends2', value(row, 'input[data-field="dividends_year2"]'));
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

  function closeDetails() {
    if (overlay.hidden) return;
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('security-detail-open');
    lastTrigger?.focus();
    lastTrigger = null;
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
        openDetails(row, button);
      });
      actionCell.prepend(button);
    });
  }

  closeTargets.forEach((element) => element.addEventListener('click', closeDetails));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !overlay.hidden) closeDetails();
  });

  const observer = new MutationObserver(attachButtons);
  observer.observe(tbody, { childList: true });
  attachButtons();
})();
