import { useState, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './RecordingIndicator.module.css';

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
    <span className={styles.wrap} title={`Идёт запись: ${who} · ${mm}:${ss}`}>
      <span className={styles.dot} />
      <span className={styles.who}>{who}</span>
      <span className={styles.time}>{mm}:{ss}</span>
    </span>
  );
}
