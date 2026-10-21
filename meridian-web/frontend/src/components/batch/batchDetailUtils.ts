/** Имя файла для File System Access API: без символов, запрещённых в ФС. */
export const safeFileName = (name: string): string => name.replace(/[/:*?"<>|]/g, '_').slice(0, 150);

export const mimeExt = (mime: string | null): string => {
  switch (mime) {
    case 'audio/mpeg': return '.mp3';
    case 'audio/wav': case 'audio/x-wav': return '.wav';
    case 'audio/mp4': case 'audio/x-m4a': case 'audio/m4a': return '.m4a';
    case 'audio/flac': return '.flac';
    case 'audio/webm': return '.webm';
    default: return '.ogg';
  }
};

/** Время реплики: мм:сс или ч:мм:сс. */
export const fmtTime = (sec: number): string => {
  const t = Math.max(0, Math.floor(sec));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};
