/* Ранняя установка темы без «мигания»: выполняется синхронно в <head> до CSS.
   Внешний файл (не inline) — CSP запрещает inline-скрипты.
   Логика синхронна с src/hooks/useTheme.ts (ключ localStorage, цвета theme-color). */
(function () {
  var KEY = 'meridian-theme';
  var COLORS = { dark: '#0D1018', light: '#FFFFFF' }; // = --bg-secondary (фон шапки) в index.css; CSS сюда ещё не загружен — литералы
  var mode = 'system';
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === 'light' || saved === 'dark' || saved === 'system') mode = saved;
  } catch (e) { /* localStorage недоступен (приватный режим) — остаёмся на системной */ }

  var theme = mode;
  if (mode === 'system') {
    theme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.documentElement.setAttribute('data-theme', theme);
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', COLORS[theme]);
})();
