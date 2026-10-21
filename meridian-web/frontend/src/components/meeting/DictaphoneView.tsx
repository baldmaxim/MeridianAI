import { useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './DictaphoneView.module.css';
import tone from './Tone.module.css';

interface Props {
  level: number;
  isListening: boolean;
  isConnected: boolean;
  onStart: () => void;
  onStop: () => void;
  // Слот под большой кнопкой (калибровка сторон «держу — говорим мы»)
  extra?: ReactNode;
}

/**
 * Простой режим встречи — чистое окно диктофона.
 * Использует ТУ ЖЕ сессию, что и MeetingPage (desktop WS), без своего подключения.
 */
export function DictaphoneView({ level, isListening, isConnected, onStart, onStop, extra }: Props) {
  const meetingName = useMeetingStore((s) => s.meetingName);
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);
  const messages = useMeetingStore((s) => s.messages);
  const lastError = useMeetingStore((s) => s.lastError);
  // Задача 2b: запись может идти на другом устройстве/аккаунте — таймер и «кто пишет»
  const recording = useMeetingStore((s) => s.recording);
  const recordingStartedAtMs = useMeetingStore((s) => s.recordingStartedAtMs);
  const activeAudioUserLabel = useMeetingStore((s) => s.activeAudioUserLabel);
  const activeAudioSource = useMeetingStore((s) => s.activeAudioSource);
  const connectionId = useMeetingStore((s) => s.connectionId);
  const deviceOffsetMs = useMeetingStore((s) => s.deviceSync?.offsetMs ?? 0);

  // Активна ли запись где-либо; ведёт ли её НЕ это устройство
  const recordingActive = isListening || recording;
  const recordedByOther = recording && !!activeAudioSource && activeAudioSource !== connectionId;

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!recordingActive) return;
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, [recordingActive]);

  // Время записи: от server-времени старта (видно и наблюдателю); 0 пока запись не идёт
  const seconds = recordingActive && recordingStartedAtMs != null
    ? Math.max(0, Math.floor((nowMs + deviceOffsetMs - recordingStartedAtMs) / 1000))
    : 0;

  let status = 'Подключение…';
  let statusText: string = tone.muted;
  let statusDot: string = tone.bgMuted;
  if (currentMeetingId == null) { status = 'Готов к записи'; statusText = tone.secondary; statusDot = tone.bgSecondary; }
  else if (!isConnected) { status = 'Нет соединения'; statusText = tone.red; statusDot = tone.bgRed; }
  else if (recordingActive) { status = 'Идёт запись'; statusText = tone.green; statusDot = tone.bgGreen; }
  else { status = 'Подключено'; statusText = tone.green; statusDot = tone.bgGreen; }

  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  const lastLines = messages.slice(-5);
  const title = meetingName || (currentMeetingId != null ? `Встреча #${currentMeetingId}` : 'Диктофон');

  return (
    <div className={styles.body}>
      <div className={styles.title}>{title}</div>

      <div className={`${styles.status} ${statusText}`}>
        <span className={`${styles.statusDot} ${statusDot}`} />
        {status}
      </div>

      {/* Задача 2b: запись ведёт другое устройство/аккаунт */}
      {recordedByOther && (
        <div className={styles.recBy}>
          Запись ведёт: {activeAudioUserLabel || 'другое устройство'}
        </div>
      )}

      {/* Уровень звука */}
      <div className={styles.levelTrack}>
        <div className={styles.levelFill} style={{ transform: `scaleX(${Math.min(1, Math.max(0, level))})` }} />
      </div>

      {/* Таймер */}
      <div className={styles.timer}>{mm}:{ss}</div>

      {/* Большая кнопка */}
      {recordedByOther ? (
        <div className={styles.otherRec}>Идёт запись с другого устройства</div>
      ) : isListening ? (
        <button className={styles.btnStop} onClick={onStop}>■ Остановить запись</button>
      ) : (
        // Старт — bootstrap встречи (создаёт и подключается). НЕ гейтим по isConnected,
        // иначе дедлок: нет соединения → кнопка заблокирована → встреча не создаётся.
        <button
          className={styles.btnStart}
          onClick={onStart}
        >
          ● Начать запись
        </button>
      )}

      {extra}

      {lastError && <div className={styles.err}>{lastError}</div>}

      {/* Последние строки транскрипции */}
      {lastLines.length > 0 && (
        <div className={styles.transcript}>
          <div className={styles.transcriptLabel}>ТРАНСКРИПЦИЯ</div>
          {lastLines.map((l) => (
            <div key={l.id} className={styles.line}>
              <span className={styles.speaker}>{l.speaker}:</span> {l.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
