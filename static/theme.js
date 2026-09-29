(() => {
  const key = 'study-agent-theme';
  const systemTheme = () => window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  let savedTheme;
  try { savedTheme = localStorage.getItem(key); } catch (_) { /* Storage may be unavailable. */ }

  const applyTheme = theme => {
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const isDark = theme === 'dark';
    button.setAttribute('aria-pressed', String(isDark));
    button.setAttribute('aria-label', isDark ? '밝은 모드로 전환' : '어두운 모드로 전환');
    button.querySelector('.theme-icon').textContent = isDark ? '☀' : '☾';
    button.querySelector('.theme-label').textContent = isDark ? '밝은 모드' : '어두운 모드';
  };

  applyTheme(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : systemTheme());
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(document.documentElement.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click', () => {
      const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      applyTheme(nextTheme);
      try { localStorage.setItem(key, nextTheme); } catch (_) { /* Keep the in-page setting. */ }
    });
  });
})();
