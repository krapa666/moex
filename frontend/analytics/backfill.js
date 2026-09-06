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

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { Accept: 'application/json' } });
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
    const blob = new Blob([`\uFEFF${header}\n`], { type: 'text/csv;charset=utf-8' });
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
      <button class="btn" type="button" data-actual-backfill-template>Пустой CSV-шаблон</button>
    </div>
    <div class="actual-worklist" data-actual-worklist>
      <div>
        <strong>Worklist текущего primary universe</strong>
        <p>Формирует отсутствующие пары «тикер × завершённый год». Это операционный список для заполнения фактов, а не историческая accuracy-метрика.</p>
      </div>
      <label>
        <span>Глубина</span>
        <select data-actual-worklist-years>
          <option value="3">3 года</option>
          <option value="5" selected>5 лет</option>
          <option value="7">7 лет</option>
          <option value="10">10 лет</option>
        </select>
      </label>
      <button class="btn" type="button" data-actual-worklist-download disabled>Скачать worklist CSV</button>
      <span class="actual-result-form-status" data-actual-worklist-status role="status" aria-live="polite">Расчёт…</span>
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
  const worklistYears = section.querySelector('[data-actual-worklist-years]');
  const worklistButton = section.querySelector('[data-actual-worklist-download]');
  const worklistStatus = section.querySelector('[data-actual-worklist-status]');
  let previewedFile = null;
  let worklistResult = null;

  function resetPreview() {
    previewedFile = null;
    applyButton.disabled = true;
    summary.hidden = true;
    tableWrap.hidden = true;
    tableBody.replaceChildren();
    status.textContent = '';
  }

  async function loadWorklist() {
    worklistButton.disabled = true;
    worklistStatus.textContent = 'Расчёт…';
    worklistResult = null;
    const years = Number(worklistYears.value || 5);
    try {
      const result = await fetchJson(
        `/api/analytics/actual-net-profits/backfill/worklist?years=${encodeURIComponent(years)}`,
      );
      worklistResult = result;
      const coverage = Number(result.coverage_percent || 0).toLocaleString('ru-RU', {
        maximumFractionDigits: 1,
      });
      worklistStatus.textContent = `${result.primary_tickers || 0} тикеров · ${result.existing_pairs || 0}/${result.expected_pairs || 0} фактов (${coverage}%) · не хватает ${result.missing_pairs || 0}`;
      worklistButton.disabled = Number(result.missing_pairs || 0) === 0;
    } catch (error) {
      worklistStatus.textContent = error.message;
    }
  }

  async function downloadWorklist() {
    if (!worklistResult || Number(worklistResult.missing_pairs || 0) === 0) return;
    const years = Number(worklistYears.value || 5);
    worklistButton.disabled = true;
    worklistStatus.textContent = 'Формирую CSV…';
    try {
      const response = await fetch(
        `/api/analytics/actual-net-profits/backfill/worklist.csv?years=${encodeURIComponent(years)}`,
      );
      if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const filenameMatch = disposition.match(/filename="([^"]+)"/i);
      const filename = filenameMatch?.[1] || 'actual-results-worklist.csv';
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      worklistStatus.textContent = `Worklist скачан · ${worklistResult.missing_pairs} строк для заполнения`;
    } catch (error) {
      worklistStatus.textContent = error.message;
    } finally {
      worklistButton.disabled = Number(worklistResult?.missing_pairs || 0) === 0;
    }
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
  worklistYears.addEventListener('change', loadWorklist);
  worklistButton.addEventListener('click', downloadWorklist);

  window.MoexAnalyticsAccess.load().then(async (state) => {
    section.hidden = !state.isAdmin;
    if (state.isAdmin) await loadWorklist();
  }).catch(() => {
    section.hidden = true;
  });
})();
