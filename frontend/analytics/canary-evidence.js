(() => {
  const tickerInput = document.getElementById('analytics-ticker');
  const form = document.getElementById('analytics-history-form');
  if (!tickerInput || !form) return;

  let overviewPanel = null;
  let tickerPanel = null;
  let currentDays = 30;
  let tickerRequestSeq = 0;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function formatNumber(value, digits = 1) {
    if (!finite(value)) return '—';
    return Number(value).toLocaleString('ru-RU', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function formatHours(value) {
    if (!finite(value)) return '—';
    const hours = Number(value);
    if (hours >= 48) return `${formatNumber(hours / 24, 1)} дн.`;
    return `${formatNumber(hours, 1)} ч`;
  }

  function formatPercent(value) {
    return finite(value) ? `${formatNumber(value, 1)} %` : '—';
  }

  function formatPrice(value) {
    return finite(value)
      ? `${Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽`
      : '—';
  }

  function modeLabel(item) {
    if (item.current_configured_mode === 'weighted_canary' && item.current_effective_mode === 'median') {
      return 'MEDIAN FALLBACK';
    }
    if (item.current_effective_mode === 'weighted') return 'WEIGHTED CANARY';
    return 'MEDIAN';
  }

  function modeKey(item) {
    if (item.current_configured_mode === 'weighted_canary' && item.current_effective_mode === 'median') {
      return 'fallback';
    }
    if (item.current_effective_mode === 'weighted') return 'weighted';
    return 'median';
  }

  function fallbackLabel(value) {
    return {
      shadow_unavailable: 'shadow недоступен',
      insufficient_weight_history: 'мало history для весов',
      live_divergence_unknown: 'divergence неизвестен',
      live_divergence_watch: 'live divergence WATCH',
      live_weight_concentration_unknown: 'концентрация неизвестна',
      live_weight_concentration_watch: 'концентрация WATCH',
      drift_insufficient: 'drift history недостаточна',
      drift_watch: 'drift WATCH',
      drift_alert: 'drift ALERT',
      unknown: 'неизвестно',
    }[value] || String(value || '—');
  }

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  function ensureOverviewPanel() {
    if (overviewPanel?.isConnected) return overviewPanel;
    const impact = document.querySelector('[data-production-impact]');
    if (!impact) return null;
    overviewPanel = document.createElement('section');
    overviewPanel.className = 'canary-evidence-overview';
    overviewPanel.dataset.canaryEvidenceOverview = '';
    overviewPanel.innerHTML = '<p class="canary-evidence-empty">Загрузка canary evidence…</p>';
    impact.append(overviewPanel);
    return overviewPanel;
  }

  function renderOverview(result) {
    const panel = ensureOverviewPanel();
    if (!panel) return;
    const items = Array.isArray(result?.items) ? result.items : [];
    const rows = items.length
      ? items.map((item) => `
        <tr data-canary-evidence-ticker="${escapeHtml(item.ticker)}" data-mode="${escapeHtml(modeKey(item))}">
          <td><a href="/analytics/?ticker=${encodeURIComponent(item.ticker)}">${escapeHtml(item.ticker)}</a></td>
          <td><span class="canary-evidence-mode" data-mode="${escapeHtml(modeKey(item))}">${escapeHtml(modeLabel(item))}</span></td>
          <td>${escapeHtml(formatPercent(item.weighted_uptime_percent))}</td>
          <td>${escapeHtml(formatHours(item.configured_weighted_hours))}</td>
          <td>${escapeHtml(formatHours(item.fallback_hours))}</td>
          <td>${escapeHtml(String(item.fallback_incidents ?? 0))}</td>
          <td>${escapeHtml(String(item.recoveries ?? 0))}</td>
          <td>${escapeHtml(formatHours(item.longest_weighted_run_hours))}</td>
          <td>${escapeHtml(
            Object.entries(item.fallback_reason_counts || {})
              .map(([reason, count]) => `${fallbackLabel(reason)} ×${count}`)
              .join(', ') || '—',
          )}</td>
        </tr>
      `).join('')
      : '<tr><td colspan="9">Canary evidence ещё не накоплена.</td></tr>';

    panel.innerHTML = `
      <div class="canary-evidence-heading">
        <div>
          <span class="analytics-panel-kicker">Forward canary evidence</span>
          <h3>Canary observability</h3>
          <p>Фактически применённый режим между snapshot. Uptime считается по реальному времени между точками, а не по числу строк.</p>
        </div>
        <label>
          <span>Окно</span>
          <select data-canary-evidence-days>
            ${[1, 7, 30, 90].map((days) => `<option value="${days}" ${days === currentDays ? 'selected' : ''}>${days} дн.</option>`).join('')}
          </select>
        </label>
      </div>
      <div class="canary-evidence-kpis">
        <article><span>Weighted uptime</span><strong>${escapeHtml(formatPercent(result.weighted_uptime_percent))}</strong></article>
        <article><span>Weighted сейчас</span><strong>${escapeHtml(String(result.current_weighted_tickers ?? 0))}</strong></article>
        <article><span>Fallback сейчас</span><strong>${escapeHtml(String(result.current_fallback_tickers ?? 0))}</strong></article>
        <article><span>Fallback incidents</span><strong>${escapeHtml(String(result.fallback_incidents ?? 0))}</strong></article>
        <article><span>Recoveries</span><strong>${escapeHtml(String(result.recoveries ?? 0))}</strong></article>
        <article><span>Median history span</span><strong>${escapeHtml(formatHours(result.median_history_span_hours))}</strong></article>
      </div>
      <div class="canary-evidence-table-wrap">
        <table class="canary-evidence-table">
          <thead><tr><th>Тикер</th><th>Режим</th><th>Uptime W</th><th>Canary time</th><th>Fallback time</th><th>Fallback</th><th>Recovery</th><th>Longest W</th><th>Причины</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p class="canary-evidence-footnote">Длительность последней точки не экстраполируется в будущее. Смена target year не создаёт ложный recovery.</p>
    `;
    panel.querySelector('[data-canary-evidence-days]')?.addEventListener('change', async (event) => {
      currentDays = Number(event.target.value) || 30;
      await loadOverview();
      await loadTicker(tickerInput.value);
    });
  }

  async function loadOverview() {
    const panel = ensureOverviewPanel();
    if (!panel) return;
    try {
      const result = await fetchJson(`/api/analytics/consensus-canary/evidence?days=${currentDays}`);
      renderOverview(result);
    } catch (_error) {
      panel.innerHTML = '<p class="canary-evidence-empty">Canary evidence недоступна.</p>';
    }
  }

  function ensureTickerPanel() {
    if (tickerPanel?.isConnected) return tickerPanel;
    const active = document.querySelector('[data-canary-active]');
    if (!active) return null;
    tickerPanel = document.createElement('section');
    tickerPanel.className = 'analytics-panel canary-evidence-ticker';
    tickerPanel.dataset.canaryEvidenceTickerPanel = '';
    tickerPanel.hidden = true;
    active.insertAdjacentElement('afterend', tickerPanel);
    return tickerPanel;
  }

  function renderTicker(report, history) {
    const panel = ensureTickerPanel();
    if (!panel) return;
    panel.hidden = false;
    if (!report?.snapshots) {
      panel.innerHTML = `
        <header class="analytics-panel-heading"><div><span class="analytics-panel-kicker">Canary timeline</span><h2>Canary evidence · ${escapeHtml(report?.ticker || '')}</h2></div></header>
        <p class="canary-evidence-empty">По тикеру ещё нет forward canary snapshots.</p>
      `;
      return;
    }

    const timeline = (Array.isArray(history) ? [...history].reverse().slice(0, 24) : []).map((point) => {
      const fallback = point.configured_mode === 'weighted_canary' && point.effective_mode !== 'weighted';
      const mode = point.effective_mode === 'weighted' ? 'weighted' : fallback ? 'fallback' : 'median';
      const label = point.effective_mode === 'weighted' ? 'WEIGHTED' : fallback ? 'FALLBACK' : 'MEDIAN';
      return `
        <div class="canary-evidence-point" data-mode="${mode}">
          <time>${escapeHtml(new Date(point.captured_at).toLocaleString('ru-RU'))}</time>
          <strong>${escapeHtml(label)}</strong>
          <span>active ${escapeHtml(formatPrice(point.active_target_price))}</span>
          <span>median ${escapeHtml(formatPrice(point.median_target_price))}</span>
          <span>weighted ${escapeHtml(formatPrice(point.weighted_target_price))}</span>
          ${point.fallback_reason ? `<small>${escapeHtml(fallbackLabel(point.fallback_reason))}</small>` : ''}
        </div>
      `;
    }).join('');

    panel.innerHTML = `
      <header class="analytics-panel-heading canary-evidence-ticker-heading">
        <div>
          <span class="analytics-panel-kicker">Canary timeline</span>
          <h2>Canary evidence · ${escapeHtml(report.ticker)}</h2>
          <p>Forward-only история фактически применённого consensus. Исторические данные до v0.23.0 не реконструируются.</p>
        </div>
        <span class="canary-evidence-mode" data-mode="${escapeHtml(modeKey(report))}">${escapeHtml(modeLabel(report))}</span>
      </header>
      <div class="canary-evidence-kpis">
        <article><span>Weighted uptime</span><strong>${escapeHtml(formatPercent(report.weighted_uptime_percent))}</strong></article>
        <article><span>Canary time</span><strong>${escapeHtml(formatHours(report.configured_weighted_hours))}</strong></article>
        <article><span>Fallback time</span><strong>${escapeHtml(formatHours(report.fallback_hours))}</strong></article>
        <article><span>Fallback incidents</span><strong>${escapeHtml(String(report.fallback_incidents ?? 0))}</strong></article>
        <article><span>Recoveries</span><strong>${escapeHtml(String(report.recoveries ?? 0))}</strong></article>
        <article><span>Longest weighted run</span><strong>${escapeHtml(formatHours(report.longest_weighted_run_hours))}</strong></article>
      </div>
      <div class="canary-evidence-timeline">${timeline || '<p>Snapshot history пуста.</p>'}</div>
    `;
  }

  async function loadTicker(rawTicker) {
    const ticker = String(rawTicker || '').trim().toLocaleUpperCase('ru');
    const panel = ensureTickerPanel();
    if (!ticker) {
      if (panel) panel.hidden = true;
      return;
    }
    const seq = ++tickerRequestSeq;
    try {
      const [report, history] = await Promise.all([
        fetchJson(`/api/analytics/consensus-canary/evidence/ticker?ticker=${encodeURIComponent(ticker)}&days=${currentDays}`),
        fetchJson(`/api/analytics/consensus-canary/evidence/history?ticker=${encodeURIComponent(ticker)}&days=${currentDays}&limit=500`),
      ]);
      if (seq !== tickerRequestSeq) return;
      renderTicker(report, history);
    } catch (_error) {
      if (seq !== tickerRequestSeq) return;
      const target = ensureTickerPanel();
      if (target) {
        target.hidden = false;
        target.innerHTML = '<p class="canary-evidence-empty">Canary timeline недоступен.</p>';
      }
    }
  }

  const observer = new MutationObserver(() => {
    if (!overviewPanel?.isConnected && document.querySelector('[data-production-impact]')) loadOverview();
    if (!tickerPanel?.isConnected && document.querySelector('[data-canary-active]')) loadTicker(tickerInput.value);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  form.addEventListener('submit', () => setTimeout(() => loadTicker(tickerInput.value), 0));
  window.addEventListener('popstate', () => {
    const ticker = new URLSearchParams(window.location.search).get('ticker') || '';
    loadTicker(ticker);
  });

  loadOverview();
  const initialTicker = new URLSearchParams(window.location.search).get('ticker') || tickerInput.value;
  if (initialTicker) loadTicker(initialTicker);
})();
