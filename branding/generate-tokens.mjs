#!/usr/bin/env node
// Генерирует brand-tokens.css для сайта и приложения для ПК из branding/tokens.json.
// Запуск: node branding/generate-tokens.mjs [--check]
// --check ничего не пишет: код 1 и список файлов, если они расходятся с tokens.json.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const TOKENS = resolve(HERE, 'tokens.json');
const TARGETS = [
  resolve(ROOT, 'meridian-web/frontend/src/styles/brand-tokens.css'),
  resolve(ROOT, 'meridian-desktop/src/styles/brand-tokens.css'),
];
// Захардкоженные копии bg, которые обязаны совпадать с брендом (только проверка).
const BG_COPIES = [
  { file: 'meridian-web/frontend/public/theme-init.js', re: /dark:\s*'(#[0-9a-fA-F]{6})'\s*,\s*light:\s*'(#[0-9a-fA-F]{6})'/, themes: ['dark', 'light'] },
  { file: 'meridian-web/frontend/index.html', re: /name="theme-color"\s+content="(#[0-9a-fA-F]{6})"/, themes: ['dark'] },
];
// Роли текста/статусов: контраст ≥ 4.5:1 на bg и card своей темы.
const CONTRAST_ROLES = ['text', 'text-secondary', 'text-muted', 'accent-dim', 'danger', 'success', 'info'];
const MIN_CONTRAST = 4.5;

const tokens = JSON.parse(readFileSync(TOKENS, 'utf8'));
const THEMES = ['dark', 'light'];

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const errors = [];
for (const [role, pair] of Object.entries(tokens)) {
  for (const theme of THEMES) {
    if (typeof pair[theme] !== 'string') errors.push(`tokens.json: нет ${role}.${theme}`);
  }
}
if (!errors.length) {
  for (const theme of THEMES) {
    for (const role of CONTRAST_ROLES) {
      for (const base of ['bg', 'card']) {
        const ratio = contrast(tokens[role][theme], tokens[base][theme]);
        if (ratio < MIN_CONTRAST) {
          errors.push(`контраст ${theme}/${role} на ${base}: ${ratio.toFixed(2)} < ${MIN_CONTRAST}`);
        }
      }
    }
  }
}

const build = () => {
  const lines = [
    '/* Сгенерировано branding/generate-tokens.mjs из branding/tokens.json — не править руками. */',
    '',
    ':root {',
  ];
  for (const theme of THEMES) {
    for (const [role, pair] of Object.entries(tokens)) {
      lines.push(`  --brand-${theme}-${role}: ${pair[theme]};`);
    }
    if (theme !== THEMES[THEMES.length - 1]) lines.push('');
  }
  lines.push('}', '');
  return lines.join('\n');
};

const checkBgCopies = () => {
  const out = [];
  for (const { file, re, themes } of BG_COPIES) {
    const path = resolve(ROOT, file);
    if (!existsSync(path)) { out.push(`${file}: файл не найден`); continue; }
    const m = readFileSync(path, 'utf8').match(re);
    if (!m) { out.push(`${file}: не удалось найти цвет темы`); continue; }
    themes.forEach((theme, i) => {
      if (m[i + 1].toLowerCase() !== tokens.bg[theme].toLowerCase()) {
        out.push(`${file}: ${theme} ${m[i + 1]} != bg бренда ${tokens.bg[theme]}`);
      }
    });
  }
  return out;
};

const check = process.argv.includes('--check');
const css = build();
const rel = (p) => relative(ROOT, p);

if (check) {
  const stale = TARGETS.filter((p) => !existsSync(p) || readFileSync(p, 'utf8') !== css).map(rel);
  const bad = [...errors, ...stale.map((f) => `${f}: расходится с tokens.json (запусти generate-tokens)`), ...checkBgCopies()];
  if (bad.length) {
    console.error('tokens:check — ошибки:\n' + bad.map((b) => `  - ${b}`).join('\n'));
    process.exit(1);
  }
  console.log('tokens:check — ок');
} else {
  if (errors.length) {
    console.error('tokens.json — ошибки:\n' + errors.map((b) => `  - ${b}`).join('\n'));
    process.exit(1);
  }
  for (const p of TARGETS) {
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, css);
    console.log(`записан ${rel(p)}`);
  }
}
