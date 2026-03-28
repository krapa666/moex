const tickerInput = document.getElementById('tickerInput');
const priceOutput = document.getElementById('priceOutput');
const statusEl = document.getElementById('status');

let timeoutId = null;

async function fetchPrice(ticker) {
  if (!ticker) {
    priceOutput.value = '';
    statusEl.textContent = '';
    return;
  }

  statusEl.textContent = 'Загрузка...';

  try {
    const response = await fetch(`/api/quote/${encodeURIComponent(ticker)}`);
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || 'Ошибка запроса');
    }

    priceOutput.value = `${payload.price} ${payload.currency}`;
    statusEl.textContent = `Биржа: ${payload.board}`;
  } catch (err) {
    priceOutput.value = '';
    statusEl.textContent = err.message;
  }
}

tickerInput.addEventListener('input', () => {
  const ticker = tickerInput.value.trim().toUpperCase();

  clearTimeout(timeoutId);
  timeoutId = setTimeout(() => {
    fetchPrice(ticker);
  }, 450);
});
