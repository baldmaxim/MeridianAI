// Задача 5: буфер аудио на время обрыва WS. PCM16-чанки (тот же формат, что шлёт
// useAudioRecorder) пишутся в IndexedDB по meetingId и переживают перезагрузку вкладки.
// При восстановлении сети чанки собираются в WAV и отправляются офлайн-дозаписью
// (kind=gap_fill) на дораспознавание, результат вливается в транскрипт встречи.

const DB_NAME = 'meridian_offline_audio';
const STORE = 'chunks';
const SAMPLE_RATE = 16000;
const CHANNELS = 1;
// Кап ~30 минут PCM16 mono 16k (= 30*60*16000*2 ≈ 57.6 МБ). Хвост сверх капа отбрасываем.
const MAX_BYTES = 30 * 60 * SAMPLE_RATE * 2;

let _db: IDBDatabase | null = null;

function openDB(): Promise<IDBDatabase> {
  if (_db) return Promise.resolve(_db);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const os = db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        os.createIndex('meeting', 'meetingId', { unique: false });
      }
    };
    req.onsuccess = () => { _db = req.result; resolve(_db); };
    req.onerror = () => reject(req.error);
  });
}

function store(db: IDBDatabase, mode: IDBTransactionMode): IDBObjectStore {
  return db.transaction(STORE, mode).objectStore(STORE);
}

export interface OfflineBufferStats { bytes: number; chunks: number; }

class OfflineAudioBuffer {
  // Грубый учёт размера на вкладку (после reload сбрасывается — кап применяется заново).
  private bytesByMeeting = new Map<number, number>();

  async append(meetingId: number, pcm: ArrayBuffer): Promise<void> {
    const cur = this.bytesByMeeting.get(meetingId) ?? 0;
    if (cur + pcm.byteLength > MAX_BYTES) return; // кап достигнут — молча отбрасываем
    try {
      const db = await openDB();
      await new Promise<void>((resolve, reject) => {
        const req = store(db, 'readwrite').add({ meetingId, ts: Date.now(), data: pcm });
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error);
      });
      this.bytesByMeeting.set(meetingId, cur + pcm.byteLength);
    } catch {
      /* IndexedDB недоступен — деградируем молча (без падения записи) */
    }
  }

  async stats(meetingId: number): Promise<OfflineBufferStats> {
    try {
      const db = await openDB();
      return await new Promise((resolve, reject) => {
        const idx = store(db, 'readonly').index('meeting');
        const req = idx.openCursor(IDBKeyRange.only(meetingId));
        let bytes = 0, chunks = 0;
        req.onsuccess = () => {
          const cur = req.result;
          if (cur) { bytes += (cur.value.data as ArrayBuffer).byteLength; chunks++; cur.continue(); }
          else resolve({ bytes, chunks });
        };
        req.onerror = () => reject(req.error);
      });
    } catch {
      return { bytes: 0, chunks: 0 };
    }
  }

  /** Собрать накопленный PCM в WAV-Blob и очистить буфер встречи. null если пусто. */
  async drainToWav(meetingId: number): Promise<Blob | null> {
    let parts: ArrayBuffer[];
    try {
      const db = await openDB();
      parts = await new Promise((resolve, reject) => {
        const idx = store(db, 'readonly').index('meeting');
        const req = idx.openCursor(IDBKeyRange.only(meetingId));
        const acc: ArrayBuffer[] = [];
        req.onsuccess = () => {
          const cur = req.result;
          if (cur) { acc.push(cur.value.data as ArrayBuffer); cur.continue(); }
          else resolve(acc);
        };
        req.onerror = () => reject(req.error);
      });
    } catch {
      return null;
    }
    if (!parts.length) return null;
    const wav = pcmChunksToWav(parts, SAMPLE_RATE, CHANNELS);
    await this.clear(meetingId);
    return wav;
  }

  async clear(meetingId: number): Promise<void> {
    try {
      const db = await openDB();
      await new Promise<void>((resolve, reject) => {
        const idx = store(db, 'readwrite').index('meeting');
        const req = idx.openCursor(IDBKeyRange.only(meetingId));
        req.onsuccess = () => {
          const cur = req.result;
          if (cur) { cur.delete(); cur.continue(); }
          else resolve();
        };
        req.onerror = () => reject(req.error);
      });
    } catch {
      /* ignore */
    }
    this.bytesByMeeting.delete(meetingId);
  }
}

export const offlineAudioBuffer = new OfflineAudioBuffer();

/** Склеить PCM16-чанки в один WAV-Blob (контейнер, без перекодирования). */
function pcmChunksToWav(chunks: ArrayBuffer[], sampleRate: number, channels: number): Blob {
  let dataLen = 0;
  for (const c of chunks) dataLen += c.byteLength;
  const header = new ArrayBuffer(44);
  const view = new DataView(header);
  const writeStr = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };
  const byteRate = sampleRate * channels * 2;
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + dataLen, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);          // PCM
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, 'data');
  view.setUint32(40, dataLen, true);
  return new Blob([header, ...chunks], { type: 'audio/wav' });
}
