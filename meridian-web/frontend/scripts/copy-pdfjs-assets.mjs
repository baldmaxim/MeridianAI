// Копирует ассеты pdf.js (cmaps, standard_fonts, wasm) из node_modules в public/pdfjs/.
// Нужны на своём origin: CSP прода не пускает чужие хосты. Запускается в predev/prebuild.
import { cp, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = path.join(root, 'node_modules', 'pdfjs-dist');
const dst = path.join(root, 'public', 'pdfjs');

await rm(dst, { recursive: true, force: true });
await mkdir(dst, { recursive: true });
for (const dir of ['cmaps', 'standard_fonts', 'wasm']) {
  await cp(path.join(src, dir), path.join(dst, dir), { recursive: true });
}
console.log('pdfjs assets -> public/pdfjs');
