(() => {
  const panel = document.getElementById('source-health-panel');
  if (!panel) return;

  const list = panel.querySelector('[data-source-health-list]');
  const summary = panel.querySelector('[data-source-health-summary]');
  const overall = panel.querySelector('[data-source-health-overall]');
  const windowSelect = panel.querySelector('[data-source-health-window]');
  const refreshButton = document.getElementById('dashboard-refresh-btn');
  let requestSerial = 0;

  const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  });
  const numberFormatter = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });

  const statusLabels = {
    healthy: 'HEALTHY',
    degraded: 'DEGRADED',
    stale: 'STALE',
    failed: 'FAILED',
  };

  const reasonLabels = {
    configuration_error: 'ошибка конфигурации',
    first_run_in_progress: 'первый запуск ещё выполняется',
    no_completed_runs: 'нет завершённых запусков',
    latest_run_failed: 'последний запуск завершился ошибкой',
    latest_run_stale: 'последний запуск устарел',
    latest_run_delayed: 'очередной запуск задерживается',
    latest_run_partial: 'последний запуск частичный',
    coverage_drop: 'покрытие заметно ниже собственной истории',
  };

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function statusLabel(status) {
    return statusLabels[status] || String(status || 'UNKNOWN').toUpperCase();
  }

  function formatAge(hours) {
    if (hours === null || hours === undefined || !Number.isFinite(Number(hours))) return '—';
    const value = Number(hours);
    if (value < 1) return `${Math.max(Math.round(value * 60), 0)} мин`;
    return `${numberFormatter.format(value)} ч`;
  }

  function formatCoverage(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    return `${numberFormatter.format(Number(value))} %`;
  }

  function formatCoverageDelta(value, baselineRuns) {
    if (!baselineRuns || value === null || value === undefined || !Number.isFinite(Number(value))) {
      return 'baseline набирается';
    }
    const numeric = Number(value);
    const sign = numeric > 0 ? '+' : '';
    return `${sign}${numberFormatter.format(numeric)} п.п. к baseline`;
  }

  function formatLastRun(item) {
    if (!item.last_completed_at) return 'Нет завершённых запусков';
    const date = new Date(item.last_completed_at);
    if (Number.isNaN(date.valueOf())) return 'Время запуска неизвестно';
    return `${dateTimeFormatter.format(date)} · ${formatAge(item.latest_age_hours)} назад`;
  }

  function formatReason(item) {
    if (!item.reasons?.length) return 'Без operational отклонений';
    return item.reasons.map((reason) => reasonLabels[reason] || reason).join(' · ');
  }

  function renderSummary(data) {
    if (overall) {
      overall.dataset.status = data.status || 'stale';
      overall.textContent = statusLabel(data.status);
    }
    if (!summary) return;
    summary.innerHTML = `
      <span>Источников: <strong data-source-health-count="configured">${Number(data.configured_sources || 0)}</strong></span>
      <span>Healthy: <strong data-source-health-count="healthy">${Number(data.healthy_sources || 0)}</strong></span>
      <span>Degraded: <strong data-source-health-count="degraded">${Number(data.degraded_sources || 0)}</strong></span>
      <span>Stale: <strong data-source-health-count="stale">${Number(data.stale_sources || 0)}</strong></span>
      <span>Failed: <strong data-source-health-count="failed">${Number(data.failed_sources || 0)}</strong></span>
    `;
  }

  function renderItems(items) {
    if (!list) return;
    if (!items?.length) {
      list.innerHTML = '<div class="source-health-empty">Активные автоматические источники не найдены.</div>';
      return;
    }

    list.innerHTML = items.map((item) => {
      const runCounts = `${Number(item.success_runs || 0)} OK · ${Number(item.partial_runs || 0)} partial · ${Number(item.failed_runs || 0)} failed`;
      const errorText = item.latest_error_kind
        ? `Ошибки: ${escapeHtml(item.latest_error_kind)}${item.latest_error_count ? ` ×${Number(item.latest_error_count)}` : ''}`
        : 'Ошибок в последнем запуске нет';
      return `
        <article class="source-health-row" data-source-health-source="${escapeHtml(item.source_id)}" data-status="${escapeHtml(item.status)}">
          <div class="source-health-row-main">
            <span class="source-health-badge" data-status="${escapeHtml(item.status)}">${escapeHtml(statusLabel(item.status))}</span>
            <div class="source-health-source">
              <strong>${escapeHtml(item.display_name)}</strong>
              <small>${escapeHtml(formatLastRun(item))}${item.run_in_progress ? ' · сейчас идёт новый запуск' : ''}</small>
            </div>
          </div>
          <div class="source-health-row-metrics">
            <span class="source-health-metric">
              <small>Покрытие</small>
              <strong>${escapeHtml(formatCoverage(item.coverage_percent))}</strong>
              <small>${escapeHtml(formatCoverageDelta(item.coverage_change_pp, item.coverage_baseline_runs))}</small>
            </span>
            <span class="source-health-metric">
              <small>Запуски за окно</small>
              <strong>${escapeHtml(runCounts)}</strong>
              <small>серия OK: ${Number(item.consecutive_successes || 0)} · failures: ${Number(item.consecutive_failures || 0)}</small>
            </span>
            <span class="source-health-metric">
              <small>Последняя диагностика</small>
              <strong>${escapeHtml(errorText)}</strong>
              <small>cadence ${numberFormatter.format(Number(item.expected_interval_hours || 0))} ч</small>
            </span>
            <span class="source-health-reason">${escapeHtml(formatReason(item))}</span>
          </div>
        </article>
      `;
    }).join('');
  }

  function renderError() {
    if (overall) {
      overall.dataset.status = 'failed';
      overall.textContent = 'ERROR';
    }
    if (summary) summary.innerHTML = '';
    if (list) {
      list.innerHTML = '<div class="source-health-error">Не удалось загрузить состояние прогнозных источников.</div>';
    }
  }

  async function loadSourceHealth() {
    const serial = ++requestSerial;
    const days = Number(windowSelect?.value || 30);
    try {
      const response = await fetch(`/api/dashboard/source-health?days=${encodeURIComponent(days)}`, {
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) throw new Error(`source health ${response.status}`);
      const data = await response.json();
      if (serial !== requestSerial) return;
      renderSummary(data);
      renderItems(data.items || []);
    } catch (_error) {
      if (serial !== requestSerial) return;
      renderError();
    }
  }

  windowSelect?.addEventListener('change', loadSourceHealth);
  refreshButton?.addEventListener('click', loadSourceHealth);
  loadSourceHealth();
})();
