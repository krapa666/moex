(() => {
  const currentPanel = document.querySelector('[data-analytics-consensus]');
  const form = document.getElementById('analytics-history-form');
  const tickerInput = document.getElementById('analytics-ticker');
  const tableSelect = document.getElementById('analytics-table');
  if (!currentPanel || !form || !tickerInput || !tableSelect) return;

  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  let panel = null;
  let status = null;
  let body = null;
  let empty = null;
  let requestSeq = 0;

  function finite(value) {
    return value !== null && value !== undefined && Number.isFinite(Number(value));
  }

  function formatPrice(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))} ₽` : '—';
  }

  function formatProfit(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))} млрд ₽` : '—';
  }

  function formatSignedPercent(value) {
    if (!finite(value)) return '—';
    const number = Number(value);
    return `${number > 0 ? '+' : ''}${percentFormatter.format(number)} %`;
  }

  function formatWeight(value) {
    return finite(value) ? `${percentFormatter.format(Number(value))}%` : '—';
  }

  function snapshotLabel(value) {
    if (value === 'pre_year') return 'на начало года';
    if (value === 'mid_year') return 'на 1 июля';
    if (value === 'year_end') return 'на конец года';
    return '—';
  }

  function ensurePanel() {
    if (panel) return;
    panel = document.createElement('section');
    panel.className = 'analytics-panel analytics-consensus-panel';
    panel.dataset.shadowConsensus = '';
    panel.hidden = true;

    const heading = document.createElement('header');
    heading.className = 'analytics-panel-heading analytics-consensus-heading';
    const titleWrap = document.createElement('div');
    titleWrap.innerHTML = `
      <span class="analytics-panel-kicker">Shadow model</span>
      <h2>Shadow weighted consensus</h2>
      <p>Текущий weighted-расчёт идёт параллельно с медианой и не используется в production fair value, Watchlist или ranking.</p>
    `;
    status = document.createElement('span');
    status.className = 'analytics-consensus-status';
    status.dataset.shadowConsensusStatus = '';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.textContent = '—';
    heading.append(titleWrap, status);

    empty = document.createElement('div');
    empty.className = 'analytics-consensus-empty';
    empty.dataset.shadowConsensusEmpty = '';
    empty.hidden = true;

    body = document.createElement('div');
    body.className = 'analytics-consensus-body';
    body.dataset.shadowConsensusBody = '';
    body.hidden = true;

    panel.append(heading, empty, body);
    currentPanel.insertAdjacentElement('afterend', panel);
  }

  function reset() {
    requestSeq += 1;
    ensurePanel();
    panel.hidden = true;
    body.hidden = true;
    empty.hidden = true;
    body.replaceChildren();
    status.textContent = '—';
  }

  function render(result) {
    ensurePanel();
    panel.hidden = false;
    if (!result?.shadow_available) {
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = result?.sources === 1
        ? 'Для shadow weighting нужен минимум второй сопоставимый текущий прогноз.'
        : 'Для shadow weighting пока нет минимум двух сопоставимых текущих прогнозов.';
      status.textContent = 'Недостаточно текущих данных';
      return;
    }

    empty.hidden = true;
    body.hidden = false;
    const historyLabel = result.weighting_uses_history
      ? `${result.sources_with_training_history}/${result.sources} источников имеют подтверждённую историю`
      : 'истории для весов пока нет — используются нейтральные равные веса';
    body.innerHTML = `
      <div class="analytics-consensus-kpis" aria-label="Shadow weighted consensus ${result.ticker}">
        <article><span>Production median</span><strong>${formatPrice(result.median_target_price)}</strong></article>
        <article><span>Shadow weighted</span><strong>${formatPrice(result.weighted_target_price)}</strong></article>
        <article><span>Δ к медиане</span><strong>${formatSignedPercent(result.weighted_vs_median_target_delta_percent)}</strong></article>
        <article><span>Рынок</span><strong>${formatPrice(result.current_price)}</strong></article>
        <article><span>Потенциал median</span><strong>${formatSignedPercent(result.median_market_gap_percent)}</strong></article>
        <article><span>Потенциал weighted</span><strong>${formatSignedPercent(result.weighted_market_gap_percent)}</strong></article>
        <article><span>ЧП median</span><strong>${formatProfit(result.median_net_profit_billion_rub)}</strong></article>
        <article><span>ЧП weighted</span><strong>${formatProfit(result.weighted_net_profit_billion_rub)}</strong></article>
        <article><span>Вес min</span><strong>${formatWeight(result.min_source_weight_percent)}</strong></article>
        <article><span>Вес max</span><strong>${formatWeight(result.max_source_weight_percent)}</strong></article>
      </div>
      <div class="analytics-consensus-notes">
        <p class="analytics-consensus-formula">Целевой год: ${result.target_year}. Исторический горизонт для весов: ${snapshotLabel(result.training_snapshot)}.</p>
        <p class="analytics-consensus-formula">Training samples: ${result.training_samples}; ${historyLabel}.</p>
        <p class="analytics-consensus-formula"><strong>Shadow-only:</strong> этот расчёт не заменяет текущую медиану и не влияет на пользовательские инвестиционные показатели.</p>
      </div>
    `;
    status.textContent = `${result.target_year} · источников: ${result.sources}`;
  }

  async function load(rawTicker) {
    const ticker = String(rawTicker || '').trim().toLocaleUpperCase('ru');
    if (!ticker) {
      reset();
      return;
    }
    ensurePanel();
    const seq = requestSeq + 1;
    requestSeq = seq;
    panel.hidden = false;
    body.hidden = true;
    empty.hidden = true;
    status.textContent = `Расчёт ${ticker}…`;
    try {
      const response = await fetch(
        `/api/analytics/shadow-consensus?ticker=${encodeURIComponent(ticker)}`,
        { headers: { 'Content-Type': 'application/json' } },
      );
      if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
      const result = await response.json();
      if (seq !== requestSeq) return;
      render(result || {});
    } catch (_error) {
      if (seq !== requestSeq) return;
      panel.hidden = false;
      body.hidden = true;
      empty.hidden = false;
      empty.textContent = 'Не удалось рассчитать shadow weighted consensus. Production consensus продолжает работать независимо.';
      status.textContent = 'Shadow недоступен';
    }
  }

  form.addEventListener('submit', () => load(tickerInput.value));
  tableSelect.addEventListener('change', () => {
    if (tickerInput.value.trim()) load(tickerInput.value);
  });
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    load(params.get('ticker') || '');
  });

  const initialTicker = new URLSearchParams(window.location.search).get('ticker') || tickerInput.value;
  if (initialTicker) load(initialTicker);
})();
