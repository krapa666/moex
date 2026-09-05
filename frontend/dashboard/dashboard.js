(() => {
  const kpi = (name) => document.querySelector(`[data-dashboard-kpi="${name}"]`);

  const percentFormatter = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
  const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  });

  async function api(path) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
    return response.json();
  }

  function finiteNumbers(values) {
    return values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  }

  function median(values) {
    const numbers = finiteNumbers(values);
    if (!numbers.length) return null;
    const middle = Math.floor(numbers.length / 2);
    return numbers.length % 2
      ? numbers[middle]
      : (numbers[middle - 1] + numbers[middle]) / 2;
  }

  function setKpi(name, value, fallback = '—') {
    const element = kpi(name);
    if (element) element.textContent = value ?? fallback;
  }

  async function loadValuationKpis() {
    try {
      const tables = await api('/api/tables');
      const primaryTable = tables.find((table) => Number(table.table_number) === 1) || tables[0];
      if (!primaryTable) {
        setKpi('securities', '0');
        setKpi('median-upside', '—');
        return;
      }

      const rows = await api(`/api/rows?table_id=${encodeURIComponent(primaryTable.id)}`);
      setKpi('securities', String(rows.length));

      const medianUpside = median(rows.map((row) => row.upside_percent_year1));
      setKpi(
        'median-upside',
        medianUpside == null ? '—' : `${percentFormatter.format(medianUpside)} %`,
      );
    } catch (_error) {
      setKpi('securities', '—');
      setKpi('median-upside', '—');
    }
  }

  async function loadVolumeKpis() {
    const [overviewResult, runResult] = await Promise.allSettled([
      api('/api/volume/overview'),
      api('/api/volume/runs/latest'),
    ]);

    if (overviewResult.status === 'fulfilled') {
      const signals = overviewResult.value.filter(
        (row) => row.latest?.signal_status === 'signal',
      ).length;
      setKpi('volume-signals', String(signals));
    } else {
      setKpi('volume-signals', '—');
    }

    if (runResult.status === 'fulfilled' && runResult.value) {
      const rawDate = runResult.value.finished_at || runResult.value.started_at;
      const date = rawDate ? new Date(rawDate) : null;
      setKpi(
        'last-volume-run',
        date && !Number.isNaN(date.valueOf()) ? dateTimeFormatter.format(date) : '—',
      );
    } else {
      setKpi('last-volume-run', '—');
    }
  }

  Promise.allSettled([loadValuationKpis(), loadVolumeKpis()]);
})();
