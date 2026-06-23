import { useEffect, useState } from 'react';
import { theme } from '../../styles/theme';
import { useMeetingStore } from '../../store/meetingStore';
import { offlineAudioBuffer } from '../../lib/offlineAudioBuffer';

/**
 * Задача 1/5: видимая индикация обрыва связи. Пока нет соединения и идёт запись —
 * звук не теряется, а буферизуется локально; показываем накопленный объём в секундах.
 * При восстановлении сети буфер уходит на дораспознавание (см. MeetingPage flush).
 */
export function OfflineBanner() {
  const isConnected = useMeetingStore((s) => s.isConnected);
  const isListening = useMeetingStore((s) => s.isListening);
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const [bufferedSec, setBufferedSec] = useState(0);

  useEffect(() => {
    // Баннер скрыт при isConnected, поэтому stale-значение не видно — синхронный сброс не нужен.
    if (isConnected || meetingId == null) return;
    let alive = true;
    const tick = async () => {
      const { bytes } = await offlineAudioBuffer.stats(meetingId);
      if (alive) setBufferedSec(Math.floor(bytes / (16000 * 2))); // PCM16 mono 16k = 32000 б/с
    };
    void tick();
    const iv = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(iv); };
  }, [isConnected, meetingId]);

  // Нет встречи (черновик ещё не создан) — соединению неоткуда взяться, баннер не нужен.
  if (isConnected || meetingId == null) return null;

  const mm = String(Math.floor(bufferedSec / 60)).padStart(2, '0');
  const ss = String(bufferedSec % 60).padStart(2, '0');

  return (
    <div style={styles.bar}>
      <span style={styles.dot} />
      <span style={styles.txt}>
        Нет соединения.{' '}
        {isListening
          ? `Запись идёт — звук буферизуется (${mm}:${ss}) и будет дораспознан при восстановлении сети.`
          : 'Переподключение…'}
      </span>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '8px 14px', background: 'rgba(255,75,110,0.12)',
    borderBottom: `1px solid ${theme.accent.red}`,
  },
  dot: { width: 8, height: 8, borderRadius: '50%', background: theme.accent.red, flexShrink: 0 },
  txt: { fontFamily: theme.font.mono, fontSize: 12, color: theme.text.primary, lineHeight: 1.4 },
};
