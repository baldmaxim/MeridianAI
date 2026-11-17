# Брендинг MERIDIAN

## Цвета бренда: один источник

`tokens.json` — единственный источник цветов для сайта (`meridian-web/frontend`) и
приложения для ПК (`meridian-desktop`). Для каждой роли задана пара `dark`/`light`.

Как поменять цвет:

1. Правка значения в `branding/tokens.json`.
2. `node branding/generate-tokens.mjs` (или `npm run tokens:generate` в `meridian-web/frontend`) —
   обновит `brand-tokens.css` в обоих проектах. Генератор проверяет контраст текста ≥ 4.5:1.
3. Коммит `tokens.json` и обоих `src/styles/brand-tokens.css`. Файлы `brand-tokens.css` руками не правим.

`node branding/generate-tokens.mjs --check` (в CI: `npm run tokens:check`) падает, если
сгенерированные файлы разошлись с `tokens.json` или если bg в `public/theme-init.js` /
`index.html` (theme-color) не совпадает с `bg` бренда.
