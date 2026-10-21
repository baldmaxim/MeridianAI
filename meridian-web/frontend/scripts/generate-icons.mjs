// Генерирует растровые иконки из единственного исходника public/meridian-favicon.svg.
// Запуск: npm run icons:generate
// Результат (коммитится): public/favicon.svg, public/icons/{favicon-32,apple-touch-icon*,icon-192,icon-512,icon-maskable-512}.png
import sharp from 'sharp';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const publicDir = join(__dirname, '..', 'public');
const iconsDir = join(publicDir, 'icons');

// Должно совпадать с background_color в манифесте (vite.pwa.config.ts) и --bg тёмной темы.
const BG = { r: 8, g: 10, b: 15, alpha: 1 }; // #080A0F
const AMBER = { r: 245, g: 166, b: 35, alpha: 1 }; // #F5A623 — заливка исходника

const source = await readFile(join(publicDir, 'meridian-favicon.svg'), 'utf8');
// Для PWA/iOS нужен «квадрат без скруглений»: ОС сама скругляет/маскирует иконку.
const flatSvg = Buffer.from(source.replace(/\srx="[\d.]+"/, ''));
const roundedSvg = Buffer.from(source);

// density = size * 72 / viewBox(32), с запасом ×2 — чёткие тонкие линии
const render = (svg, size) =>
  sharp(svg, { density: Math.ceil((size * 72) / 32) * 2 })
    .resize(size, size, { fit: 'contain', background: BG })
    .flatten({ background: BG });

const save = async (img, name) => {
  await img.png({ compressionLevel: 9 }).toFile(join(iconsDir, name));
  console.log(`ok ${name}`);
};

await mkdir(iconsDir, { recursive: true });

// SVG-фавикон для вкладки — копия исходника
await writeFile(join(publicDir, 'favicon.svg'), source);
console.log('ok favicon.svg');

// Вкладка браузера: скруглённый, с прозрачными углами
await sharp(roundedSvg, { density: 576 })
  .resize(32, 32)
  .png({ compressionLevel: 9 })
  .toFile(join(iconsDir, 'favicon-32.png'));
console.log('ok favicon-32.png');

// iOS «На экран Домой» + Android/PWA: полноразмерная заливка, непрозрачный фон
const flat = [
  ['apple-touch-icon.png', 180],
  ['apple-touch-icon-120.png', 120],
  ['apple-touch-icon-152.png', 152],
  ['apple-touch-icon-167.png', 167],
  ['icon-192.png', 192],
  ['icon-512.png', 512],
];
for (const [name, size] of flat) await save(render(flatSvg, size), name);

// Maskable: знак занимает ~80% (поля ~10% по краям — безопасная зона маски Android),
// поля залиты тем же янтарём, что и иконка, чтобы маска любой формы выглядела цельной.
const MASK_SIZE = 512;
const inner = Math.round(MASK_SIZE * 0.8);
const innerPng = await render(flatSvg, inner).png().toBuffer();
// composite() добавляет альфа-канал, а flatten() в sharp выполняется до composite — снимаем альфу вторым проходом
const composed = await sharp({ create: { width: MASK_SIZE, height: MASK_SIZE, channels: 3, background: AMBER } })
  .composite([{ input: innerPng, gravity: 'center' }])
  .png()
  .toBuffer();
await save(sharp(composed).flatten({ background: AMBER }), 'icon-maskable-512.png');
