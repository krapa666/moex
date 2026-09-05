(() => {
  const restoreTimers = new WeakMap();

  async function writeClipboard(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand('copy');
    textarea.remove();
    if (!copied) throw new Error('Clipboard copy failed');
  }

  function restoreButton(button, label) {
    button.textContent = label;
    button.disabled = false;
    delete button.dataset.copyState;
    restoreTimers.delete(button);
  }

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy-current-url]');
    if (!button || button.disabled) return;

    const label = button.dataset.copyLabel || button.textContent.trim() || 'Копировать ссылку';
    const previousTimer = restoreTimers.get(button);
    if (previousTimer) clearTimeout(previousTimer);

    button.disabled = true;
    try {
      await writeClipboard(window.location.href);
      button.textContent = 'Ссылка скопирована';
      button.dataset.copyState = 'success';
    } catch (_error) {
      button.textContent = 'Не удалось скопировать';
      button.dataset.copyState = 'error';
    } finally {
      button.disabled = false;
      const timer = setTimeout(() => restoreButton(button, label), 1800);
      restoreTimers.set(button, timer);
    }
  });
})();
