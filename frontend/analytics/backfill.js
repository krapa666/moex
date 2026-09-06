(() => {
  const adminBlock = document.querySelector('[data-actual-admin]');
  if (!adminBlock || !window.MoexAnalyticsAccess) return;

  function createCell(value, className = '') {
    const cell = document.createElement('td');
    cell.textContent = value ?? '—';
    if (className) cell.className = className;
    return cell;
  }

  function actionLabel(action) {
    return {
      create: 'CREATE',
      unchanged: 'UNCHANGED',
      protected: 'PROTECTED',
      invalid: 'INVALID',
    }[action] || String(action || '—').toUpperCase();
  }

  async function postCsv(path, file) {
    const formData = new FormData();
    formData.append('file', file, file.name);
    const response = await fetch(path, { method: 'POST', body: formData });
    if (!response.ok) {
      let detail = `Ошибка API: ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) detail = String(payload.detail);
      } catch (_error) {
        // Keep the HTTP fallback.
      }
      throw new Error(detail);
    }
    return response.json();
  }

  function downloadTemplate() {
    const header = [
      'ticker',
      'fiscal_year',
      'net_profit_billion_rub',
      'source_name',
      'source_url',
      'reported_at',
      'source_comment',
    ].join(';');
    const sample = [
      'SBER',
      '2025',
      '1580.3',
      'МСФО · отчёт эмитента',
      'https://example.com/report',
      '2026-02-27',
      'ЧП, относимая к акционерам материнской компании',
    ].join(';');
    const blob = new Blob([`\uFEFF${header}\n${sample}\n`], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'actual-results-backfill-template.csv';
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function renderResult(result) {
    summary.hidden = false;
    summary.textContent = [
      `строк ${result.rows_total || 0}`,
      `создать ${result.create_rows || 0}`,
      `без изменений ${result.unchanged_rows || 0}`,
      `защищено ${result.protected_rows || 0}`,
      `ошибок ${result.invalid_rows || 0}`,
    ].join(' · ');

    tableBody.replaceChildren();
    const items = Array.isArray(result.items) ? result.items.slice(0, 100) : [];
    tableWrap.hidden = !items.length;
    for (const item of items) {
      const tr = document.createElement('tr');
      tr.dataset.backfillAction = item.action || '';
      tr.append(
        createCell(String(item.row_number ?? '—')),
        createCell(item.ticker || '—', 'actual-backfill-key'),
        createCell(item.fiscal_year == null ? '—' : String(item.fiscal_year)),
        createCell(actionLabel(item.action), 'actual-backfill-action'),
        createCell(item.message || '—'),
      );
      tableBody.append(tr);
    }

    if ((result.items || []).length > items.length) {
      status.textContent += ` · показаны первые ${items.length}`;
    }
  }

  const section = document.createElement('div');
  section.className = 'actual-backfill';
  section.dataset.actualBackfill = '';
  section.innerHTML = `
    <div class="actual-backfill-heading">
      <div>
        <h4>Исторический backfill фактической ЧП</h4>
        <p>CSV импортируется только из локального доступа. Сначала preview; существующие канонические факты никогда не перезаписываются bulk-import’ом.</p>
      </div>
      <button class="btn" type="button" data-actual-backfill-template>CSV-шаблон</button>
    </div>
    <form class="actual-backfill-form" data-actual-backfill-form>
      <label>
        <span>CSV UTF-8</span>
        <input type="file" name="file" accept=".csv,text/csv" required />
      </label>
      <button class="btn" type="submit" data-actual-backfill-preview>Проверить</button>
      <button class="btn btn-primary" type="button" data-actual-backfill-apply disabled>Импортировать</button>
    </form>
    <p class="actual-backfill-note">Обязательные поля: ticker, fiscal_year, net_profit_billion_rub, source_name, source_url, reported_at. Допустимы разделители <code>;</code>, <code>,</code> и tab. Год должен быть завершённым.</p>
    <span class="actual-result-form-status" data-actual-backfill-status role="status" aria-live="polite"></span>
    <div class="actual-backfill-summary" data-actual-backfill-summary hidden></div>
    <div class="actual-backfill-table-wrap" data-actual-backfill-table-wrap hidden>
      <table class="actual-backfill-table">
        <thead><tr><th>Строка</th><th>Тикер</th><th>Год</th><th>Действие</th><th>Комментарий</th></tr></thead>
        <tbody data-actual-backfill-body></tbody>
      </table>
    </div>
  `;

  const manualForm = adminBlock.querySelector('[data-actual-form]');
  adminBlock.insertBefore(section, manualForm);

  const form = section.querySelector('[data-actual-backfill-form]');
  const fileInput = form.querySelector('input[type="file"]');
  const previewButton = section.querySelector('[data-actual-backfill-preview]');
  const applyButton = section.querySelector('[data-actual-backfill-apply]');
  const templateButton = section.querySelector('[data-actual-backfill-template]');
  const status = section.querySelector('[data-actual-backfill-status]');
  const summary = section.querySelector('[data-actual-backfill-summary]');
  const tableWrap = section.querySelector('[data-actual-backfill-table-wrap]');
  const tableBody = section.querySelector('[data-actual-backfill-body]');
  let previewedFile = null;

  function resetPreview() {
    previewedFile = null;
    applyButton.disabled = true;
    summary.hidden = true;
    tableWrap.hidden = true;
    tableBody.replaceChildren();
    status.textContent = '';
  }

  async function preview(event) {
    event.preventDefault();
    const file = fileInput.files?.[0];
    if (!file) {
      status.textContent = 'Выберите CSV-файл.';
      return;
    }

    previewButton.disabled = true;
    applyButton.disabled = true;
    status.textContent = 'Проверка CSV…';
    try {
      const result = await postCsv('/api/analytics/actual-net-profits/backfill/preview', file);
      renderResult(result);
      previewedFile = file;
      const canApply = Number(result.invalid_rows || 0) === 0 && Number(result.create_rows || 0) > 0;
      applyButton.disabled = !canApply;
      status.textContent = canApply
        ? `Preview готов · к импорту ${result.create_rows}`
        : Number(result.invalid_rows || 0) > 0
          ? 'Импорт заблокирован: исправьте INVALID строки.'
          : 'Новых фактов для импорта нет.';
    } catch (error) {
      resetPreview();
      status.textContent = error.message;
    } finally {
      previewButton.disabled = false;
    }
  }

  async function applyBackfill() {
    const file = fileInput.files?.[0];
    if (!file || file !== previewedFile) {
      resetPreview();
      status.textContent = 'Файл изменился. Выполните preview заново.';
      return;
    }

    previewButton.disabled = true;
    applyButton.disabled = true;
    status.textContent = 'Импорт…';
    try {
      const result = await postCsv('/api/analytics/actual-net-profits/backfill', file);
      renderResult(result);
      if (!result.applied) {
        status.textContent = 'Импорт не выполнен: CSV содержит ошибки.';
        return;
      }
      status.textContent = `Импорт завершён · создано ${result.created_rows || 0}. Обновляю Analytics…`;
      window.setTimeout(() => window.location.reload(), 250);
    } catch (error) {
      status.textContent = error.message;
      applyButton.disabled = false;
    } finally {
      previewButton.disabled = false;
    }
  }

  fileInput.addEventListener('change', resetPreview);
  form.addEventListener('submit', preview);
  applyButton.addEventListener('click', applyBackfill);
  templateButton.addEventListener('click', downloadTemplate);

  window.MoexAnalyticsAccess.load().then((state) => {
    section.hidden = !state.isAdmin;
  }).catch(() => {
    section.hidden = true;
  });
})();
