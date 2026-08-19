/** Минимальный ZIP-упаковщик (без сжатия) — чтобы отдавать все материалы одной загрузкой.
 *
 * Браузер блокирует пачку автоматических скачиваний, а File System Access API требует
 * отдельных разрешений. Один архив снимает обе проблемы. Аудио уже сжато (opus),
 * текст мелкий — компрессия не нужна, поэтому метод STORE.
 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i++) c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Время модификации в формате MS-DOS (два 16-битных слова). */
function dosDateTime(d: Date): { time: number; date: number } {
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | Math.floor(d.getSeconds() / 2),
    date: ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
  };
}

/** Копия байтов в самостоятельный ArrayBuffer (Blob не принимает Uint8Array<ArrayBufferLike>). */
function toBuffer(view: Uint8Array): ArrayBuffer {
  const out = new ArrayBuffer(view.byteLength);
  new Uint8Array(out).set(view);
  return out;
}

export interface ZipEntry {
  name: string;
  blob: Blob;
}

/** Собрать ZIP (STORE) из готовых blob'ов. Имена — UTF-8 (флаг bit 11). */
export async function createZip(entries: ZipEntry[]): Promise<Blob> {
  const encoder = new TextEncoder();
  const { time, date } = dosDateTime(new Date());
  const chunks: ArrayBuffer[] = [];
  const central: ArrayBuffer[] = [];
  let offset = 0;

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const data = new Uint8Array(await entry.blob.arrayBuffer());
    const crc = crc32(data);

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); // сигнатура локального заголовка
    local.setUint16(4, 20, true); // минимальная версия
    local.setUint16(6, 0x0800, true); // имена в UTF-8
    local.setUint16(8, 0, true); // метод: store
    local.setUint16(10, time, true);
    local.setUint16(12, date, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, nameBytes.length, true);
    local.setUint16(28, 0, true); // extra field
    chunks.push(local.buffer, toBuffer(nameBytes), toBuffer(data));

    const dir = new Uint8Array(46 + nameBytes.length);
    const dv = new DataView(dir.buffer);
    dv.setUint32(0, 0x02014b50, true);
    dv.setUint16(4, 20, true);
    dv.setUint16(6, 20, true);
    dv.setUint16(8, 0x0800, true);
    dv.setUint16(10, 0, true);
    dv.setUint16(12, time, true);
    dv.setUint16(14, date, true);
    dv.setUint32(16, crc, true);
    dv.setUint32(20, data.length, true);
    dv.setUint32(24, data.length, true);
    dv.setUint16(28, nameBytes.length, true);
    dv.setUint32(42, offset, true); // смещение локального заголовка
    dir.set(nameBytes, 46);
    central.push(dir.buffer);

    offset += 30 + nameBytes.length + data.length;
  }

  const centralSize = central.reduce((sum, c) => sum + c.byteLength, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);

  return new Blob([...chunks, ...central, end.buffer], { type: 'application/zip' });
}
