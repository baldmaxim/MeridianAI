import { useState, useEffect } from 'react';
import { theme } from '../../styles/theme';
import { useMeetingStore } from '../../store/meetingStore';

/**
 * Задача 2b: индикатор активной записи в шапке встречи (рядом с заказчик/объект/дата).
 * Показывает, КАКОЙ аккаунт ведёт запись и СКОЛЬКО по времени — даже если пишет
 * другое устройство/пользователь в этой встрече. Время считается от server-времени
 * старта записи с поправкой на device-clock offset, поэтому корректно у наблюдателя.
 */
export function RecordingIndicator() {
  const recording = useMeetingStore((s) => s.recording);
  const isListening = useMeetingStore((s) => s.isListening);
  const recordingStartedAtMs = useMeetingStore((s) => s.recordingStartedAtMs);
  const activeAudioUserLabel = useMeetingStore((s) => s.activeAudioUserLabel);
  const activeAudioSource = useMeetingStore((s) => s.activeAudioSource);
  const connectionId = useMeetingStore((s) => s.connectionId);
  const deviceOffsetMs = useMeetingStore((s) => s.deviceSync?.offsetMs ?? 0);

  const active = recording || isListening;
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);

  if (!active) return null;

  const seconds = recordingStartedAtMs != null
    ? Math.max(0, Math.floor((nowMs + deviceOffsetMs - recordingStartedAtMs) / 1000))
    : 0;
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');

  const byOther = recording && !!activeAudioSource && activeAudioSource !== connectionId;
  const who = byOther ? (activeAudioUserLabel || 'другое устройство') : 'вы';

  return (
    <span style={styles.wrap} title={`Идёт запись: ${who} · ${mm}:${ss}`}>
      <span style={styles.dot} />
      <span style={styles.who}>{who}</span>
      <span style={styles.time}>{mm}:{ss}</span>
    </span>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
    padding: '4px 10px', borderRadius: 999,
    border: `1px solid ${theme.accent.red}`, background: 'rgba(255,75,110,0.10)',
  },
  dot: { width: 8, height: 8, borderRadius: '50%', background: theme.accent.red },
  who: {
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary,
    maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  time: {
    fontFamily: theme.font.mono, fontSize: 12, fontWeight: 700,
    color: theme.accent.red, fontVariantNumeric: 'tabular-nums',
  },
};
