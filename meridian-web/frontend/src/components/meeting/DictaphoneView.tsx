import { useState, useEffect } from 'react';
import { theme } from '../../styles/theme';
import { useMeetingStore } from '../../store/meetingStore';

interface Props {
  level: number;
  isListening: boolean;
  isConnected: boolean;
  onStart: () => void;
  onStop: () => void;
}

/**
 * Простой режим встречи — чистое окно диктофона.
 * Использует ТУ ЖЕ сессию, что и MeetingPage (desktop WS), без своего подключения.
 */
export function DictaphoneView({ level, isListening, isConnected, onStart, onStop }: Props) {
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
  let statusColor: string = theme.text.muted;
  if (!isConnected) { status = 'Нет соединения'; statusColor = theme.accent.red; }
  else if (recordingActive) { status = 'Идёт запись'; statusColor = theme.accent.green; }
  else { status = 'Подключено'; statusColor = theme.accent.green; }

  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  const lastLines = messages.slice(-5);
  const title = meetingName || (currentMeetingId != null ? `Встреча #${currentMeetingId}` : 'Диктофон');

  return (
    <div style={styles.body}>
      <div style={styles.title}>{title}</div>

      <div style={{ ...styles.status, color: statusColor }}>
        <span style={{ ...styles.statusDot, background: statusColor }} />
        {status}
      </div>

      {/* Задача 2b: запись ведёт другое устройство/аккаунт */}
      {recordedByOther && (
        <div style={styles.recBy}>
          Запись ведёт: {activeAudioUserLabel || 'другое устройство'}
        </div>
      )}

      {/* Уровень звука */}
      <div style={styles.levelTrack}>
        <div style={{ ...styles.levelFill, width: `${Math.round(level * 100)}%` }} />
      </div>

      {/* Таймер */}
      <div style={styles.timer}>{mm}:{ss}</div>

      {/* Большая кнопка */}
      {recordedByOther ? (
        <div style={styles.otherRec}>Идёт запись с другого устройства</div>
      ) : isListening ? (
        <button style={styles.btnStop} onClick={onStop}>■ Остановить запись</button>
      ) : (
        // Старт — bootstrap встречи (создаёт и подключается). НЕ гейтим по isConnected,
        // иначе дедлок: нет соединения → кнопка заблокирована → встреча не создаётся.
        <button
          style={styles.btnStart}
          onClick={onStart}
        >
          ● Начать запись
        </button>
      )}

      {lastError && <div style={styles.err}>{lastError}</div>}

      {/* Последние строки транскрипции */}
      {lastLines.length > 0 && (
        <div style={styles.transcript}>
          <div style={styles.transcriptLabel}>ТРАНСКРИПЦИЯ</div>
          {lastLines.map((l) => (
            <div key={l.id} style={styles.line}>
              <span style={styles.speaker}>{l.speaker}:</span> {l.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  body: { flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: '24px 18px', maxWidth: 480, width: '100%', margin: '0 auto', boxSizing: 'border-box' as const },
  title: { fontFamily: theme.font.heading, fontWeight: 800, fontSize: 20, textAlign: 'center' as const },
  status: { display: 'flex', alignItems: 'center', gap: 8, fontFamily: theme.font.mono, fontSize: 13, marginTop: 4 },
  statusDot: { width: 8, height: 8, borderRadius: '50%' },
  levelTrack: { width: '100%', height: 8, background: theme.bg.tertiary, borderRadius: 6, overflow: 'hidden', border: `1px solid ${theme.border.default}` },
  levelFill: { height: '100%', background: theme.accent.green, transition: 'width 0.08s linear' },
  timer: { fontFamily: theme.font.body, fontSize: 40, fontWeight: 700, letterSpacing: '0.08em', fontVariantNumeric: 'tabular-nums', color: theme.text.primary },
  btnStart: { width: '100%', maxWidth: 320, padding: '20px', background: theme.accent.amber, border: 'none', borderRadius: 16, color: '#080A0F', fontSize: 18, fontWeight: 700, cursor: 'pointer', fontFamily: theme.font.body },
  btnStop: { width: '100%', maxWidth: 320, padding: '20px', background: theme.accent.red, border: 'none', borderRadius: 16, color: '#fff', fontSize: 18, fontWeight: 700, cursor: 'pointer', fontFamily: theme.font.body },
  btnDisabled: { width: '100%', maxWidth: 320, padding: '20px', background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 16, color: theme.text.muted, fontSize: 16, fontWeight: 600, cursor: 'not-allowed', fontFamily: theme.font.body },
  recBy: { fontFamily: theme.font.mono, fontSize: 12, color: theme.accent.amber },
  otherRec: { width: '100%', maxWidth: 320, padding: '18px', textAlign: 'center' as const, background: theme.bg.elevated, border: `1px solid ${theme.accent.green}`, borderRadius: 16, color: theme.accent.green, fontSize: 15, fontWeight: 600, fontFamily: theme.font.body },
  err: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 12, textAlign: 'center' as const },
  transcript: { width: '100%', background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 },
  transcriptLabel: { fontFamily: theme.font.mono, fontSize: 10, letterSpacing: '0.12em', color: theme.accent.amber },
  line: { fontSize: 13, color: theme.text.secondary, lineHeight: 1.5 },
  speaker: { color: theme.accent.amber, fontFamily: theme.font.mono, fontSize: 11 },
};
