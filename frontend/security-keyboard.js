(() => {
  const tbody = document.getElementById('rows-table-body');
  const overlay = document.getElementById('security-detail-overlay');
  const drawer = overlay?.querySelector('.security-detail-drawer');
  if (!tbody || !overlay || !drawer) return;

  const focusableSelector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  let lastTrigger = null;
  let wasOpen = !overlay.hidden;

  function focusableElements() {
    return [...drawer.querySelectorAll(focusableSelector)].filter((element) => {
      if (element.hidden || element.getAttribute('aria-hidden') === 'true') return false;
      const style = window.getComputedStyle(element);
      return style.display !== 'none' && style.visibility !== 'hidden';
    });
  }

  function restoreTriggerFocus() {
    if (!lastTrigger?.isConnected) return;
    queueMicrotask(() => {
      if (overlay.hidden && lastTrigger?.isConnected) lastTrigger.focus();
    });
  }

  tbody.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-action="details"]');
    if (trigger) lastTrigger = trigger;
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab' || overlay.hidden) return;

    const focusable = focusableElements();
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && (active === first || !drawer.contains(active))) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && (active === last || !drawer.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  });

  const observer = new MutationObserver(() => {
    const isOpen = !overlay.hidden;
    if (wasOpen && !isOpen) restoreTriggerFocus();
    wasOpen = isOpen;
  });
  observer.observe(overlay, { attributes: true, attributeFilter: ['hidden'] });
})();
