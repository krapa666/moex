(() => {
  const access = window.MoexAnalyticsAccess;
  const consensusPanel = document.querySelector('[data-analytics-consensus]');
  const form = document.getElementById('analytics-history-form');
  const tickerInput = document.getElementById('analytics-ticker');
  if (!access || !consensusPanel || !form || !tickerInput) return;

  let activeRequestSeq = 0;
  let canaryState = null;
  let controlsReady = false;

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

  function formatPrice(value) {
    if (!finite(value)) return '—';
    return `${Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽`;
  }

  function formatPercent(value) {
    if (!finite(value)) return '—';
    const number = Number(value);
    return `${number > 0 ? '+' : ''}${number.toLocaleString('ru-RU', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })} %`;
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let detail = `Ошибка API: ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) detail = String(payload.detail);
      } catch (_error) {
        // Keep HTTP fallback.
      }
      throw new Error(detail);
    }
    return response.json();
  }

  const activePanel = document.createElement('section');
  activePanel.className = 'analytics-panel canary-active-panel';
  activePanel.dataset.canaryActive = '';
  activePanel.hidden = true;
  activePanel.innerHTML = `
    <header class="analytics-panel-heading canary-active-heading">
      <div>
        <span class="analytics-panel-kicker">Runtime consensus</span>
        <h2>Active consensus</h2>
        <p>Фактически используемый consensus для выбранного тикера. Median остаётся fail-safe baseline.</p>
      </div>
      <span class="canary-mode-badge" data-canary-active-mode>—</span>
    </header>
    <div class="canary-active-body" data-canary-active-body></div>
  `;
  consensusPanel.insertAdjacentElement('afterend', activePanel);
  const activeMode = activePanel.querySelector('[data-canary-active-mode]');
  const activeBody = activePanel.querySelector('[data-canary-active-body]');

  function fallbackLabel(value) {
    return {
      shadow_unavailable: 'shadow weighted недоступен',
      insufficient_weight_history: 'недостаточно реальной истории весов',
      live_divergence_unknown: 'live divergence не определён',
      live_divergence_watch: 'live divergence достиг WATCH',
      live_weight_concentration_unknown: 'концентрация весов не определена',
      live_weight_concentration_watch: 'концентрация весов достигла WATCH',
      drift_insufficient: 'forward history недостаточна',
      drift_watch: 'forward drift = WATCH',
      drift_alert: 'forward drift = ALERT',
    }[value] || String(value || '');
  }

  function renderActive(result) {
    activePanel.hidden = false;
    if (!result?.active_available) {
      activeMode.dataset.mode = 'median';
      activeMode.textContent = 'MEDIAN';
      activeBody.innerHTML = '<p class="canary-active-empty">Нет сопоставимой текущей consensus-цели.</p>';
      return;
    }

    const weightedEffective = result.effective_mode === 'weighted';
    const configured = result.configured_mode === 'weighted_canary';
    activeMode.dataset.mode = weightedEffective ? 'weighted' : configured ? 'fallback' : 'median';
    activeMode.textContent = weightedEffective
      ? 'WEIGHTED CANARY'
      : configured ? 'MEDIAN FALLBACK' : 'MEDIAN';

    const safety = result.safety_status
      ? String(result.safety_status).toUpperCase()
      : configured ? 'LIVE GUARD' : '—';
    const fallback = result.fallback_reason
      ? `<p class="canary-fallback"><strong>Fallback:</strong> ${escapeHtml(fallbackLabel(result.fallback_reason))}</p>`
      : '';
    const allowlist = result.canary_enabled
      ? (result.in_allowlist ? 'тикер в canary allowlist' : 'тикер вне canary allowlist')
      : 'canary глобально выключен';

    activeBody.innerHTML = `
      <div class="canary-active-kpis">
        <article><span>Активная цель</span><strong>${escapeHtml(formatPrice(result.active_target_price))}</strong></article>
        <article><span>Median baseline</span><strong>${escapeHtml(formatPrice(result.median_target_price))}</strong></article>
        <article><span>Weighted candidate</span><strong>${escapeHtml(formatPrice(result.weighted_target_price))}</strong></article>
        <article><span>Активная доходность</span><strong>${escapeHtml(formatPercent(result.active_expected_return_percent))}</strong></article>
        <article><span>Источников</span><strong>${escapeHtml(String(result.sources ?? '—'))}</strong></article>
        <article><span>Safety state</span><strong>${escapeHtml(safety)}</strong></article>
      </div>
      <p class="canary-active-note">${escapeHtml(allowlist)}. Weighted меняет только price-target слой; dividend layer остаётся baseline.</p>
      ${fallback}
    `;
  }

  async function loadActive(rawTicker) {
    const ticker = String(rawTicker || '').trim().toLocaleUpperCase('ru');
    if (!ticker) {
      activePanel.hidden = true;
      return;
    }
    const seq = ++activeRequestSeq;
    activePanel.hidden = false;
    activeMode.textContent = 'Загрузка…';
    delete activeMode.dataset.mode;
    activeBody.innerHTML = '';
    try {
      const result = await fetchJson(`/api/analytics/active-consensus?ticker=${encodeURIComponent(ticker)}`);
      if (seq !== activeRequestSeq) return;
      renderActive(result);
    } catch (_error) {
      if (seq !== activeRequestSeq) return;
      activeMode.dataset.mode = 'fallback';
      activeMode.textContent = 'НЕДОСТУПНО';
      activeBody.innerHTML = '<p class="canary-active-empty">Не удалось загрузить active consensus.</p>';
    }
  }

  function normalizeTickers(raw) {
    return [...new Set(String(raw || '')
      .split(/[\s,;]+/)
      .map((value) => value.trim().toLocaleUpperCase('ru'))
      .filter(Boolean))];
  }

  function canaryStatusLabel(state) {
    if (!state?.enabled) return 'DISABLED · production median';
    const tickers = (state.tickers || []).join(', ') || 'без тикеров';
    return `ENABLED · ${tickers}`;
  }

  function markImpactRows() {
    const tickers = new Set(canaryState?.enabled ? canaryState.tickers || [] : []);
    document.querySelectorAll('[data-production-impact-ticker]').forEach((row) => {
      const ticker = String(row.dataset.productionImpactTicker || '').toLocaleUpperCase('ru');
      row.dataset.canaryTicker = String(tickers.has(ticker));
    });
  }

  async function setupControls() {
    if (controlsReady) return;
    const impactPanel = document.querySelector('[data-production-impact]');
    if (!impactPanel) return;
    controlsReady = true;

    const auth = await access.load().catch(() => ({ isAdmin: false }));
    const block = document.createElement('div');
    block.className = 'canary-control-block';
    block.dataset.canaryControls = '';
    impactPanel.append(block);

    async function loadState() {
      canaryState = await fetchJson('/api/analytics/consensus-canary');
      const tickers = (canaryState.tickers || []).join(', ');
      block.innerHTML = `
        <div class="canary-control-heading">
          <div>
            <h3>Controlled canary</h3>
            <p>Median — default. Weighted разрешён максимум для ${escapeHtml(String(canaryState.max_tickers))} выбранных тикеров и автоматически падает обратно в median при нарушении safety guard.</p>
          </div>
          <span class="canary-global-badge" data-enabled="${canaryState.enabled}">${escapeHtml(canaryStatusLabel(canaryState))}</span>
        </div>
        <p class="canary-safety-policy">${escapeHtml(canaryState.safety_policy || '')}</p>
        ${auth.isAdmin ? `
          <div class="canary-admin-controls">
            <label>
              <span>Allowlist тикеров</span>
              <input data-canary-tickers value="${escapeHtml(tickers)}" placeholder="SBER, LKOH" maxlength="128" />
            </label>
            <label>
              <span>Audit note</span>
              <input data-canary-note placeholder="Причина изменения" maxlength="255" />
            </label>
            <div class="canary-admin-actions">
              <button class="btn" type="button" data-canary-save>Сохранить выключенным</button>
              <button class="btn btn-primary" type="button" data-canary-enable>Включить canary</button>
              <button class="btn" type="button" data-canary-rollback ${canaryState.enabled ? '' : 'disabled'}>Rollback → median</button>
            </div>
            <span class="canary-admin-status" data-canary-admin-status role="status" aria-live="polite"></span>
            <div class="canary-audit" data-canary-audit></div>
          </div>
        ` : '<p class="canary-public-note">Изменение режима доступно только из local scope.</p>'}
      `;
      markImpactRows();
      if (auth.isAdmin) bindAdminActions();
    }

    async function renderAudit() {
      const audit = block.querySelector('[data-canary-audit]');
      if (!audit) return;
      try {
        const events = await fetchJson('/api/analytics/consensus-canary/events?limit=10');
        if (!events.length) {
          audit.innerHTML = '<p>Audit trail пока пуст.</p>';
          return;
        }
        audit.innerHTML = `
          <details>
            <summary>Audit trail · последние ${events.length}</summary>
            <div class="canary-audit-list">
              ${events.map((event) => `
                <div>
                  <strong>${escapeHtml(String(event.action || '').toUpperCase())}</strong>
                  <span>${escapeHtml((event.new_tickers || []).join(', ') || 'median only')}</span>
                  <small>${escapeHtml(new Date(event.occurred_at).toLocaleString('ru-RU'))}${event.note ? ` · ${escapeHtml(event.note)}` : ''}</small>
                </div>
              `).join('')}
            </div>
          </details>
        `;
      } catch (_error) {
        audit.innerHTML = '<p>Audit trail недоступен.</p>';
      }
    }

    function bindAdminActions() {
      const tickersInput = block.querySelector('[data-canary-tickers]');
      const noteInput = block.querySelector('[data-canary-note]');
      const status = block.querySelector('[data-canary-admin-status]');
      const save = block.querySelector('[data-canary-save]');
      const enable = block.querySelector('[data-canary-enable]');
      const rollback = block.querySelector('[data-canary-rollback]');

      async function update(enabled) {
        const tickers = normalizeTickers(tickersInput.value);
        status.textContent = enabled ? 'Проверка gates и включение…' : 'Сохранение…';
        try {
          await fetchJson('/api/analytics/consensus-canary', {
            method: 'PUT',
            body: JSON.stringify({ enabled, tickers, note: noteInput.value || null }),
          });
          await loadState();
          await loadActive(tickerInput.value);
        } catch (error) {
          status.textContent = error.message;
        }
      }

      save.addEventListener('click', () => update(false));
      enable.addEventListener('click', () => update(true));
      rollback.addEventListener('click', async () => {
        status.textContent = 'Rollback…';
        try {
          await fetchJson('/api/analytics/consensus-canary/rollback', {
            method: 'POST',
            body: JSON.stringify({ note: noteInput.value || 'manual rollback' }),
          });
          await loadState();
          await loadActive(tickerInput.value);
        } catch (error) {
          status.textContent = error.message;
        }
      });
      renderAudit();
    }

    try {
      await loadState();
    } catch (_error) {
      block.innerHTML = '<p class="canary-active-empty">Canary status недоступен.</p>';
    }
  }

  const observer = new MutationObserver(() => {
    setupControls();
    markImpactRows();
  });
  observer.observe(document.body, { childList: true, subtree: true });
  setupControls();

  form.addEventListener('submit', () => setTimeout(() => loadActive(tickerInput.value), 0));
  window.addEventListener('popstate', () => {
    const ticker = new URLSearchParams(window.location.search).get('ticker') || '';
    loadActive(ticker);
  });

  const initialTicker = new URLSearchParams(window.location.search).get('ticker') || tickerInput.value;
  if (initialTicker) loadActive(initialTicker);
})();
