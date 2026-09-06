(() => {
  let panel = null;
  let currentDays = 30;

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

  function statusLabel(value) {
    return {
      not_configured: 'НЕ НАСТРОЕНО',
      warming_up: 'НАБИРАЕТ ИСТОРИЮ',
      healthy: 'HEALTHY',
      degraded: 'DEGRADED',
      stale: 'STALE',
    }[value] || String(value || '—').toUpperCase();
  }

  function reasonLabel(value) {
    return {
      no_evidence: 'ещё нет evidence snapshot',
      too_few_snapshots: 'нужно минимум две точки',
      latest_snapshot_delayed: 'последняя точка задержана',
      latest_snapshot_stale: 'последняя точка устарела',
      capture_gaps_detected: 'обнаружены пропуски capture',
    }[value] || String(value || '');
  }

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  function ensurePanel() {
    if (panel?.isConnected) return panel;
    const impact = document.querySelector('[data-production-impact]');
    if (!impact) return null;
    panel = document.createElement('section');
    panel.className = 'canary-evidence-health';
    panel.dataset.canaryEvidenceHealth = '';
    const evidence = impact.querySelector('[data-canary-evidence-overview]');
    if (evidence) evidence.insertAdjacentElement('afterend', panel);
    else impact.append(panel);
    return panel;
  }

  function render(result) {
    const target = ensurePanel();
    if (!target) return;
    const items = Array.isArray(result?.items) ? result.items : [];
    const rows = items.length
      ? items.map((item) => `
        <tr data-canary-health-ticker="${escapeHtml(item.ticker)}" data-status="${escapeHtml(item.status)}">
          <td>${escapeHtml(item.ticker)}</td>
          <td><span class="canary-health-badge" data-status="${escapeHtml(item.status)}">${escapeHtml(statusLabel(item.status))}</span></td>
          <td>${escapeHtml(formatHours(item.latest_age_hours))}</td>
          <td>${escapeHtml(formatPercent(item.continuity_percent))}</td>
          <td>${escapeHtml(String(item.missed_cycles_estimate ?? 0))}</td>
          <td>${escapeHtml(formatHours(item.longest_gap_hours))}</td>
          <td>${escapeHtml((item.reasons || []).map(reasonLabel).join(', ') || '—')}</td>
        </tr>
      `).join('')
      : '<tr><td colspan="7">Configured canary tickers отсутствуют.</td></tr>';

    target.innerHTML = `
      <div class="canary-health-heading">
        <div>
          <span class="analytics-panel-kicker">Evidence quality</span>
          <h3>Capture health</h3>
          <p>Проверяет свежесть и непрерывность evidence-потока. Хороший weighted uptime не считается надёжным evidence при пропусках scheduler.</p>
        </div>
        <div class="canary-health-heading-actions">
          <span class="canary-health-badge canary-health-overall" data-status="${escapeHtml(result.status)}">${escapeHtml(statusLabel(result.status))}</span>
          <label>
            <span>Окно</span>
            <select data-canary-health-days>
              ${[1, 7, 30, 90].map((days) => `<option value="${days}" ${days === currentDays ? 'selected' : ''}>${days} дн.</option>`).join('')}
            </select>
          </label>
        </div>
      </div>
      <div class="canary-health-kpis">
        <article><span>Expected cadence</span><strong>${escapeHtml(formatHours(result.expected_interval_hours))}</strong></article>
        <article><span>Latest capture age</span><strong>${escapeHtml(formatHours(result.latest_capture_age_hours))}</strong></article>
        <article><span>Median continuity</span><strong>${escapeHtml(formatPercent(result.median_continuity_percent))}</strong></article>
        <article><span>Missed cycles est.</span><strong>${escapeHtml(String(result.missed_cycles_estimate ?? 0))}</strong></article>
        <article><span>Gap violations</span><strong>${escapeHtml(String(result.gap_violations ?? 0))}</strong></article>
        <article><span>Longest gap</span><strong>${escapeHtml(formatHours(result.longest_gap_hours))}</strong></article>
      </div>
      <p class="canary-health-policy">Fresh ≤ 1,5× cadence · stale &gt; 2,5× · вероятный пропуск цикла при gap ≥ 1,75× cadence.</p>
      <div class="canary-health-table-wrap">
        <table class="canary-health-table">
          <thead><tr><th>Тикер</th><th>Health</th><th>Age</th><th>Continuity</th><th>Missed</th><th>Max gap</th><th>Причины</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;

    target.querySelector('[data-canary-health-days]')?.addEventListener('change', async (event) => {
      currentDays = Number(event.target.value) || 30;
      await load();
    });
  }

  async function load() {
    const target = ensurePanel();
    if (!target) return;
    target.innerHTML = '<p class="canary-health-empty">Проверка capture health…</p>';
    try {
      const result = await fetchJson(`/api/analytics/consensus-canary/evidence/health?days=${currentDays}`);
      render(result);
    } catch (_error) {
      target.innerHTML = '<p class="canary-health-empty">Capture health недоступен.</p>';
    }
  }

  const observer = new MutationObserver(() => {
    if (!panel?.isConnected && document.querySelector('[data-production-impact]')) load();
  });
  observer.observe(document.body, { childList: true, subtree: true });
  load();
})();
