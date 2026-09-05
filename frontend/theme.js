(() => {
  const STORAGE_KEY = 'moex-theme';
  const root = document.documentElement;
  const media = window.matchMedia('(prefers-color-scheme: dark)');

  function storedTheme() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value === 'light' || value === 'dark' ? value : null;
    } catch (_err) {
      return null;
    }
  }

  function applyTheme(theme, { persist = false } = {}) {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;

    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, theme);
      } catch (_err) {
        // Theme persistence is optional; keep the active theme even if storage is unavailable.
      }
    }

    const button = document.querySelector('[data-theme-toggle]');
    if (button) {
      const dark = theme === 'dark';
      button.textContent = dark ? '☀' : '☾';
      button.title = dark ? 'Включить светлую тему' : 'Включить тёмную тему';
      button.setAttribute('aria-label', button.title);
      button.setAttribute('aria-pressed', String(dark));
    }
  }

  const initialTheme = storedTheme() || (media.matches ? 'dark' : 'light');
  applyTheme(initialTheme);

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(root.dataset.theme || initialTheme);
    document.querySelector('[data-theme-toggle]')?.addEventListener('click', () => {
      applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark', { persist: true });
    });
  });

  media.addEventListener?.('change', (event) => {
    if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light');
  });
})();
