(() => {
  const overviewBody = document.getElementById('volume-overview-body');
  const detailSection = document.getElementById('detail-section');
  const backButton = document.getElementById('detail-back-btn');
  if (!overviewBody || !detailSection || !backButton) return;

  let lastTrigger = null;
  let restoreFocusPending = false;

  function restoreFocusIfReady() {
    if (!restoreFocusPending || !detailSection.hidden) return;
    restoreFocusPending = false;
    if (lastTrigger?.isConnected) lastTrigger.focus();
  }

  overviewBody.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-ticker]');
    if (trigger) lastTrigger = trigger;
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || detailSection.hidden) return;
    event.preventDefault();
    restoreFocusPending = true;
    backButton.click();
    restoreFocusIfReady();
  });

  const observer = new MutationObserver(restoreFocusIfReady);
  observer.observe(detailSection, { attributes: true, attributeFilter: ['hidden'] });
})();
