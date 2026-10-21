/**
 * Хелперы для CSS-переменных темы (styles/theme.ts отдаёт строки вида 'var(--x)').
 * Строковая склейка `${color}40` и канвас/библиотеки с 'var(...)' не работают —
 * для них используем эти функции.
 */

/** Достаёт имя переменной из 'var(--x)' / 'var(--x, fallback)' или возвращает как есть ('--x'). */
const toVarName = (nameOrVar: string): string => {
  const m = /^var\(\s*(--[\w-]+)/.exec(nameOrVar.trim());
  return m ? m[1] : nameOrVar.trim();
};

/**
 * Текущее вычисленное значение переменной темы ('--accent' или 'var(--accent)').
 * Нужно там, где CSS-переменные не понимаются: canvas (fillStyle/strokeStyle), сторонние библиотеки.
 * Значение зависит от активной темы на момент вызова — при смене темы перерисуйте.
 */
export const getCssVar = (nameOrVar: string, fallback = ''): string => {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(toVarName(nameOrVar)).trim();
  return value || fallback;
};

/**
 * Цвет с прозрачностью для CSS: работает и с 'var(--x)', и с hex.
 * Замена конструкциям `${color}40` / `color + '25'`.
 * @param percent доля исходного цвета, 0..100
 */
export const withAlpha = (color: string, percent: number): string =>
  `color-mix(in srgb, ${color} ${percent}%, transparent)`;
