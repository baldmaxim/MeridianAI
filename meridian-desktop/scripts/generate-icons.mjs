// Генерация иконок из одного SVG: src-tauri/icons/meridian.svg.
// 1) трей-иконки и ресурсы в src-tauri/resources (64x64, sharp);
// 2) иконки приложения (ico/icns/png/Square*/android/ios) через `tauri icon`.
// Запуск: bun run icons:generate
import sharp from 'sharp';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const iconsDir = join(root, 'src-tauri', 'icons');
const resDir = join(root, 'src-tauri', 'resources');
const SIZE = 64;

const AMBER = '#F5A623';
const LIGHT = '#FFFFFF'; // для тёмной темы ОС (tray_*.png)
const DARK = '#1A1A1A'; // для светлой темы ОС (tray_*_dark.png)
const RED = '#FF4B6E';
const BLUE = '#5B9CF6';

// Монохромный компас на прозрачном фоне; dot — индикатор состояния в правом нижнем углу.
const compass = (color, dot) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <g stroke="${color}" stroke-width="5" stroke-linecap="round">
    <circle cx="32" cy="32" r="19"/>
    <line x1="32" y1="3" x2="32" y2="13"/><line x1="32" y1="51" x2="32" y2="61"/>
    <line x1="3" y1="32" x2="13" y2="32"/><line x1="51" y1="32" x2="61" y2="32"/>
  </g>
  <circle cx="32" cy="32" r="5" fill="${color}"/>
  ${dot ? `<circle cx="51" cy="51" r="12" fill="${dot}"/>` : ''}
</svg>`;

const targets = [
  ['tray_idle.png', compass(LIGHT)],
  ['tray_idle_dark.png', compass(DARK)],
  ['tray_recording.png', compass(LIGHT, RED)],
  ['tray_recording_dark.png', compass(DARK, RED)],
  ['tray_transcribing.png', compass(LIGHT, BLUE)],
  ['tray_transcribing_dark.png', compass(DARK, BLUE)],
  // Цветная тема (Linux)
  ['meridian.png', compass(AMBER)],
  ['recording.png', compass(AMBER, RED)],
  ['transcribing.png', compass(AMBER, BLUE)],
];

for (const [name, svg] of targets) {
  await sharp(Buffer.from(svg), { density: 576 })
    .resize(SIZE, SIZE)
    .png({ compressionLevel: 9 })
    .toFile(join(resDir, name));
  console.log(`ok ${name} (${SIZE}x${SIZE})`);
}

// logo.png (1024) — крупный логотип без привязки к платформам
await sharp(join(iconsDir, 'meridian.svg'), { density: 2304 })
  .resize(1024, 1024)
  .png({ compressionLevel: 9 })
  .toFile(join(iconsDir, 'logo.png'));
console.log('ok logo.png (1024x1024)');

execFileSync(
  join(root, 'node_modules', '.bin', 'tauri'),
  ['icon', join(iconsDir, 'meridian.svg')],
  { cwd: root, stdio: 'inherit' },
);
