(() => {
  const accuracyPanel = document.querySelector('[data-source-accuracy]');
  if (!accuracyPanel) return;

  let section = null;
  let status = null;
  let summary = null;
  let body = null;
  let empty = null;

  function ensureSection() {
    if (section) return;
    section = document.createElement('div');
    section.className = 'actual-facts consensus-readiness';
    section.dataset.consensusReadiness = '';

    const heading = document.createElement('div');
    heading.className = 'source-accuracy-controls';
    const titleWrap = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = 'Readiness к production weighting';
    const description = document.createElement('p');
    description.textContent = 'Явные policy-критерии продвижения weighted consensus. Даже READY не включает его автоматически: переключение production остаётся отдельным релизным решением.';
    titleWrap.append(title, description);

    status = document.createElement('span');
    status.className = 'analytics-status';
    status.dataset.consensusReadinessStatus = '';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.textContent = 'Расчёт…';
    heading.append(titleWrap, status);

    empty = document.createElement('div');
    empty.className = 'source-accuracy-empty';
    empty.dataset.consensusReadinessEmpty = '';
    empty.hidden = true;

    summary = document.createElement('p');
    summary.dataset.consensusReadinessSummary = '';

    const wrap = document.createElement('div');
    wrap.className = 'source-accuracy-table-wrap';
    const table = document.createElement('table');
    table.className = 'source-accuracy-table';
    table.innerHTML = `
      <thead>
        <tr><th>Критерий</th><th>Факт</th><th>Требование</th><th>Статус</th></tr>
      </thead>
    `;
    body = document.createElement('tbody');
    body.dataset.consensusReadinessBody = '';
    table.append(body);
    wrap.append(table);

    section.append(heading, empty, summary, wrap);
    accuracyPanel.append(section);
  }

  function render(result) {
    ensureSection();
    if (result?.error) {
      empty.hidden = false;
      summary.hidden = true;
      body.parentElement.parentElement.hidden = true;
      empty.textContent = String(result.error);
      status.textContent = 'Ошибка';
      return;
    }

    const gates = Array.isArray(result?.gates) ? result.gates : [];
    if (!gates.length) {
      empty.hidden = false;
      summary.hidden = true;
      body.parentElement.parentElement.hidden = true;
      empty.textContent = 'Readiness пока невозможно оценить.';
      status.textContent = 'Нет данных';
      return;
    }

    empty.hidden = true;
    summary.hidden = false;
    body.parentElement.parentElement.hidden = false;
    body.replaceChildren();

    for (const gate of gates) {
      const tr = document.createElement('tr');
      if (!gate.passed) tr.classList.add('accuracy-row-unranked');
      const cells = [
        gate.label || gate.key || '—',
        gate.actual || '—',
        gate.requirement || '—',
        gate.passed ? 'PASS' : 'WAIT',
      ];
      for (const value of cells) {
        const td = document.createElement('td');
        td.textContent = String(value);
        tr.append(td);
      }
      body.append(tr);
    }

    summary.textContent = result.ready
      ? 'Все текущие policy-gates выполнены. Это означает только готовность к отдельному решению о promotion; production consensus всё ещё медианный.'
      : `Выполнено ${result.gates_passed}/${result.gates_total} критериев. Weighted consensus остаётся shadow-only.`;
    status.textContent = result.ready
      ? `READY · ${result.gates_passed}/${result.gates_total}`
      : `SHADOW · ${result.gates_passed}/${result.gates_total}`;
  }

  ensureSection();
  window.addEventListener('moex-consensus-readiness', (event) => render(event.detail || {}));
})();
