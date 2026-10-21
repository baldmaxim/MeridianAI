// Скачивает модель CAM++ (эмбеддинг диктора) в src-tauri/resources/models.
// Без зависимостей: node >= 18. Если файл уже есть и sha256 совпал — ничего не делает.
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const URL_ =
  'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx';
const SHA256 = 'aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2';
const FILE_NAME = 'campplus-sv-zh-en-16k.onnx';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dir = join(root, 'src-tauri', 'resources', 'models');
const target = join(dir, FILE_NAME);

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');

if (existsSync(target) && sha256(readFileSync(target)) === SHA256) {
  console.log(`voice model: ${FILE_NAME} уже на месте, sha256 совпал`);
  process.exit(0);
}

console.log(`voice model: скачиваю ${URL_}`);
const res = await fetch(URL_, { redirect: 'follow' });
if (!res.ok) {
  console.error(`voice model: HTTP ${res.status} ${res.statusText}`);
  process.exit(1);
}
const buf = Buffer.from(await res.arrayBuffer());
const actual = sha256(buf);
if (actual !== SHA256) {
  console.error(`voice model: sha256 не совпал (ожидался ${SHA256}, получен ${actual})`);
  process.exit(1);
}

mkdirSync(dir, { recursive: true });
const tmp = `${target}.part`;
writeFileSync(tmp, buf);
renameSync(tmp, target);
console.log(`voice model: сохранено ${target} (${buf.length} байт)`);
