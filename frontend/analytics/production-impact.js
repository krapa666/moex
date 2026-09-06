(() => {
  const anchor = document.querySelector('[data-source-accuracy]');
  if (!anchor) return;

  const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });

  let requestSeq = 0;

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function formatNumber(value, digits = 1) {
    if (!finite(value)) return '—';
    return Number(value).toLocaleString('ru-RU', { maximumFractionDigits: digits });
  }

  function formatPrice(value) {
    return finite(value) ? `${numberFormatter.format(Number(value))} ₽` : '—';
  }

  function formatPercent(value) {
    return finite(value) ? `${percentFormatter.format(Number(value))} %` : '—';
  }

  function formatSignedPercent(value) {
    if (!finite(value)) return '—';
    const number = Number(value);
    return `${number > 0 ? '+' : ''}${percentFormatter.format(number)} %`;
  }

  function formatSignedPoints(value) {
    if (!finite(value)) return '—';
    const number = Number(value);
    return `${number > 0 ? '+' : ''}${percentFormatter.format(number)} п.п.`;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  const section = document.createElement('section');
  section.className = 'analytics-panel production-impact-panel';
  section.dataset.productionImpact = '';
  section.setAttribute('aria-labelledby', 'production-impact-title');
  section.innerHTML = `
    <header class="analytics-panel-heading production-impact-heading">
      <div>
        <span class="analytics-panel-kicker">Promotion decision</span>
        <h2 id="production-impact-title">Production impact simulator</h2>
        <p>Параллельный расчёт median consensus vs shadow weighted по всему universe. Это preview будущего promotion: текущие Оценки и Watchlist не изменяются.</p>
      </div>
      <div class="production-impact-controls">
        <label>Top-N
          <select data-production-impact-top-n>
            <option value="10">Top-10</option>
            <option value="20">Top-20</option>
          </select>
        </label>
        <label>Forward window
          <select data-production-impact-days>
            <option value="30">30 дней</option>
            <option value="90">90 дней</option>
            <option value="180">180 дней</option>
          </select>
        </label>
        <span class="production-impact-status" data-production-impact-status role="status" aria-live="polite">Расчёт…</span>
      </div>
    </header>
    <div class="production-impact-empty" data-production-impact-empty hidden></div>
    <div data-production-impact-content hidden>
      <div class="production-impact-summary" data-production-impact-summary></div>
      <p class="production-impact-note" data-production-impact-note></p>
      <div class="production-impact-gates" data-production-impact-gates></div>
      <div class="production-impact-table-wrap">
        <table class="production-impact-table">
          <thead>
            <tr>
              <th>Тикер</th>
              <th>Median target</th>
              <th>Weighted target</th>
              <th>Δ target</th>
              <th>Median return</th>
              <th>Weighted return</th>
              <th>Δ return</th>
              <th>Rank M/W</th>
              <th>Δ rank</th>
              <th>Score M/W</th>
              <th>Top-N</th>
            </tr>
          </thead>
          <tbody data-production-impact-body></tbody>
        </table>
      </div>
    </div>
  `;
  anchor.insertAdjacentElement('afterend', section);

  const topNSelect = section.querySelector('[data-production-impact-top-n]');
  const daysSelect = section.querySelector('[data-production-impact-days]');
  const status = section.querySelector('[data-production-impact-status]');
  const empty = section.querySelector('[data-production-impact-empty]');
  const content = section.querySelector('[data-production-impact-content]');
  const summary = section.querySelector('[data-production-impact-summary]');
  const note = section.querySelector('[data-production-impact-note]');
  const gates = section.querySelector('[data-production-impact-gates]');
  const body = section.querySelector('[data-production-impact-body]');

  function promotionMode(value) {
    if (value === 'READY_FOR_MANUAL_PROMOTION') return 'ready';
    if (value === 'OBSERVE') return 'observe';
    return 'not-ready';
  }

  function promotionLabel(value) {
    return {
      READY_FOR_MANUAL_PROMOTION: 'READY FOR MANUAL PROMOTION',
      OBSERVE: 'OBSERVE',
      NOT_READY: 'NOT READY',
    }[value] || String(value || 'NOT READY');
  }

  function changeDirection(value) {
    if (!finite(value) || Math.abs(Number(value)) < 0.0001) return '';
    return Number(value) > 0 ? 'positive' : 'negative';
  }

  function renderSummary(impact) {
    const cards = [
      ['Покрытие', formatPercent(impact.comparable_coverage_percent)],
      ['Spearman rank', formatNumber(impact.rank_correlation_spearman, 3)],
      [`Top-${impact.top_n} overlap`, formatPercent(impact.top_n_overlap_percent)],
      ['Смена знака', formatPercent(impact.return_sign_flip_percent)],
      ['Средний |Δ rank|', formatNumber(impact.mean_abs_rank_change, 1)],
      ['Средний |Δ score|', finite(impact.mean_abs_watchlist_score_delta) ? `${formatNumber(impact.mean_abs_watchlist_score_delta, 1)} pt` : '—'],
    ];
    summary.innerHTML = cards.map(([label, value]) => `
      <article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>
    `).join('');
  }

  function renderGates(promotion) {
    gates.innerHTML = (promotion.gates || []).map((gate) => `
      <div class="production-impact-gate" data-passed="${gate.passed}">
        <b>${gate.passed ? 'PASS' : 'WAIT'}</b>
        <span>${escapeHtml(gate.label)}</span>
        <small>${escapeHtml(gate.actual)} · ${escapeHtml(gate.requirement)}</small>
      </div>
    `).join('');
  }

  function topChange(item) {
    if (item.in_weighted_top_n && !item.in_median_top_n) {
      return '<span class="production-impact-top-change" data-kind="entered">входит</span>';
    }
    if (item.in_median_top_n && !item.in_weighted_top_n) {
      return '<span class="production-impact-top-change" data-kind="exited">выходит</span>';
    }
    if (item.in_median_top_n && item.in_weighted_top_n) {
      return '<span class="production-impact-top-change">остаётся</span>';
    }
    return '—';
  }

  function renderItems(items) {
    body.innerHTML = (items || []).map((item) => {
      const targetDirection = changeDirection(item.target_delta_percent);
      const returnDirection = changeDirection(item.expected_return_delta_pp);
      const rankDirection = finite(item.rank_delta) && Number(item.rank_delta) < 0
        ? 'positive'
        : finite(item.rank_delta) && Number(item.rank_delta) > 0 ? 'negative' : '';
      const rankLabel = finite(item.median_rank) && finite(item.weighted_rank)
        ? `${item.median_rank} / ${item.weighted_rank}`
        : '—';
      const scoreLabel = finite(item.median_watchlist_score) && finite(item.weighted_watchlist_score)
        ? `${item.median_watchlist_score} / ${item.weighted_watchlist_score}`
        : '—';
      return `
        <tr data-production-impact-ticker="${escapeHtml(item.ticker)}">
          <td><a href="/analytics/?ticker=${encodeURIComponent(item.ticker)}">${escapeHtml(item.ticker)}</a></td>
          <td>${escapeHtml(formatPrice(item.median_target_price))}</td>
          <td>${escapeHtml(formatPrice(item.weighted_target_price))}</td>
          <td><span class="production-impact-change" data-direction="${targetDirection}">${escapeHtml(formatSignedPercent(item.target_delta_percent))}</span></td>
          <td>${escapeHtml(formatSignedPercent(item.median_expected_return_percent))}</td>
          <td>${escapeHtml(formatSignedPercent(item.weighted_expected_return_percent))}</td>
          <td><span class="production-impact-change" data-direction="${returnDirection}">${escapeHtml(formatSignedPoints(item.expected_return_delta_pp))}</span></td>
          <td>${escapeHtml(rankLabel)}</td>
          <td><span class="production-impact-change" data-direction="${rankDirection}">${finite(item.rank_delta) ? escapeHtml(String(Number(item.rank_delta) > 0 ? `+${item.rank_delta}` : item.rank_delta)) : '—'}</span></td>
          <td>${escapeHtml(scoreLabel)}</td>
          <td>${topChange(item)}</td>
        </tr>
      `;
    }).join('');
  }

  function render(result) {
    const impact = result?.impact;
    const promotion = result?.promotion;
    if (!impact || !promotion || !Number(impact.comparable_tickers || 0)) {
      empty.hidden = false;
      content.hidden = true;
      empty.textContent = 'Недостаточно сопоставимых текущих прогнозов для production impact simulator.';
      status.textContent = 'Недостаточно данных';
      status.dataset.mode = 'not-ready';
      return;
    }

    empty.hidden = true;
    content.hidden = false;
    status.dataset.mode = promotionMode(promotion.status);
    status.textContent = `${promotionLabel(promotion.status)} · ${promotion.gates_passed}/${promotion.gates_total}`;
    renderSummary(impact);
    renderGates(promotion);
    renderItems(impact.items);
    const entered = (impact.top_n_entered || []).join(', ') || 'нет';
    const exited = (impact.top_n_exited || []).join(', ') || 'нет';
    note.textContent = `Top-${impact.top_n}: входят ${entered}; выходят ${exited}. Score M/W — гипотетическая sensitivity по формуле Watchlist 60/25/15, а не текущий Watchlist: production-страница по-прежнему использует основную таблицу №1. Weighted меняет только price-target слой; дивидендный вклад сохраняется.`;
  }

  async function load() {
    const seq = ++requestSeq;
    status.textContent = 'Расчёт…';
    delete status.dataset.mode;
    empty.hidden = true;
    try {
      const topN = Number(topNSelect.value || 10);
      const days = Number(daysSelect.value || 30);
      const result = await fetchJson(`/api/analytics/production-impact?top_n=${topN}&history_days=${days}`);
      if (seq !== requestSeq) return;
      render(result);
    } catch (_error) {
      if (seq !== requestSeq) return;
      empty.hidden = false;
      content.hidden = true;
      empty.textContent = 'Не удалось загрузить production impact simulator.';
      status.textContent = 'Ошибка загрузки';
      status.dataset.mode = 'not-ready';
    }
  }

  topNSelect.addEventListener('change', load);
  daysSelect.addEventListener('change', load);
  load();
})();
