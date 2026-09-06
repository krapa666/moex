(() => {
  let statePromise = null;
  let isAdmin = false;
  let tables = [];
  let tableNumbers = new Map();

  async function fetchJson(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  function displayAnalystName(tableNumber, analystName) {
    const number = Number(tableNumber);
    if (isAdmin) return String(analystName || `Аналитик ${number || ''}`).trim();
    return Number.isFinite(number) && number > 0 ? `Аналитик ${number}` : 'Аналитик';
  }

  function tableNumberForId(tableId) {
    return tableNumbers.get(String(tableId)) ?? null;
  }

  function maskRevision(revision) {
    if (!revision || typeof revision !== 'object') return revision;
    const tableNumber = tableNumberForId(revision.table_id) ?? Number(revision.table_id);
    return {
      ...revision,
      analyst_name: displayAnalystName(tableNumber, revision.analyst_name),
    };
  }

  async function load() {
    if (statePromise) return statePromise;
    statePromise = (async () => {
      const [authResult, tablesResult] = await Promise.allSettled([
        fetchJson('/api/auth/me'),
        fetchJson('/api/tables'),
      ]);

      isAdmin = authResult.status === 'fulfilled' && Boolean(authResult.value?.is_admin);
      tables = tablesResult.status === 'fulfilled' && Array.isArray(tablesResult.value)
        ? tablesResult.value
        : [];
      tableNumbers = new Map(
        tables.map((table) => [String(table.id), Number(table.table_number)]),
      );

      return {
        isAdmin,
        tables,
      };
    })();
    return statePromise;
  }

  window.MoexAnalyticsAccess = {
    load,
    displayAnalystName,
    tableNumberForId,
    maskRevision,
    maskRevisions(revisions) {
      return Array.isArray(revisions) ? revisions.map(maskRevision) : [];
    },
  };

  const impactStyle = document.createElement('link');
  impactStyle.rel = 'stylesheet';
  impactStyle.href = '/analytics/production-impact.css';
  document.head.append(impactStyle);

  const impactScript = document.createElement('script');
  impactScript.src = '/analytics/production-impact.js';
  document.body.append(impactScript);
})();
