import { useState, useEffect, useCallback } from 'react';
import { theme } from '../styles/theme';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useMeetingStore } from '../store/meetingStore';
import { getMobileMeeting } from '../api/mobile';
import { navigate } from '../lib/navigation';
import type { MobileMeetingDetail } from '../types';

interface Props {
  meetingId: number;
}

export function RecorderPage({ meetingId }: Props) {
  const { connect, disconnect, sendJSON, sendBinary } = useWebSocket();
  const [level, setLevel] = useState(0);
  const [micOn, setMicOn] = useState(false);
  const [meeting, setMeeting] = useState<MobileMeetingDetail | null>(null);
  const [seconds, setSeconds] = useState(0);

  // store
  const isConnected = useMeetingStore((s) => s.isConnected);
  const connectionId = useMeetingStore((s) => s.connectionId);
  const canSendAudio = useMeetingStore((s) => s.canSendAudio);
  const activeAudioSource = useMeetingStore((s) => s.activeAudioSource);
  const recording = useMeetingStore((s) => s.recording);
  const recordPermissionDenied = useMeetingStore((s) => s.recordPermissionDenied);
  const messages = useMeetingStore((s) => s.messages);
  const lastError = useMeetingStore((s) => s.lastError);

  const isActiveSource = !!activeAudioSource && !!connectionId && activeAudioSource === connectionId;

  // отправлять аудио только когда мы — активный источник
  const guardedSend = useCallback((buf: ArrayBuffer) => {
    const st = useMeetingStore.getState();
    if (st.connectionId && st.activeAudioSource === st.connectionId) {
      sendBinary(buf);
    }
  }, [sendBinary]);

  const { start: startMic, stop: stopMic } = useAudioRecorder(guardedSend, setLevel);

  // подключение к комнате как phone
  useEffect(() => {
    getMobileMeeting(meetingId).then(setMeeting).catch(() => {});
    useMeetingStore.getState().setCurrentMeetingId(meetingId);
    connect({ meetingId, deviceRole: 'phone' });
    return () => {
      stopMic();
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId]);

  // запрет записи — глушим микрофон
  useEffect(() => {
    if (recordPermissionDenied && micOn) {
      stopMic();
      setMicOn(false);
    }
  }, [recordPermissionDenied, micOn, stopMic]);

  // источник занят другим устройством — освобождаем микрофон
  useEffect(() => {
    if (micOn && activeAudioSource && !isActiveSource) {
      stopMic();
      setMicOn(false);
    }
  }, [micOn, activeAudioSource, isActiveSource, stopMic]);

  // таймер записи
  useEffect(() => {
    if (isActiveSource && recording) {
      const t = setInterval(() => setSeconds((s) => s + 1), 1000);
      return () => clearInterval(t);
    }
    setSeconds(0);
  }, [isActiveSource, recording]);

  const handleStart = async () => {
    useMeetingStore.getState().setRecordPermissionDenied(false);
    try {
      await startMic();
      setMicOn(true);
      sendJSON({ type: 'start_audio' });
    } catch {
      useMeetingStore.getState().setError('Не удалось получить доступ к микрофону');
      setMicOn(false);
    }
  };

  const handleStop = () => {
    stopMic();
    setMicOn(false);
    sendJSON({ type: 'stop_audio' });
  };

  let status = 'Подключение…';
  let statusColor: string = theme.text.muted;
  if (recordPermissionDenied) { status = 'Нет прав на запись'; statusColor = theme.accent.red; }
  else if (!isConnected) { status = 'Нет соединения'; statusColor = theme.accent.red; }
  else if (isActiveSource && recording) { status = 'Идёт запись'; statusColor = theme.accent.green; }
  else if (activeAudioSource && !isActiveSource) { status = 'Источник аудио занят'; statusColor = theme.accent.amber; }
  else { status = 'Подключено'; statusColor = theme.accent.green; }

  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  const lastLines = messages.slice(-5);

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <button style={styles.back} onClick={() => navigate(`/mobile/meetings/${meetingId}`)}>‹ Назад к встрече</button>
      </header>

      <div style={styles.body}>
        <div style={styles.title}>{meeting?.title || meeting?.meeting_topic || `Встреча #${meetingId}`}</div>
        <div style={styles.meta}>
          {meeting?.customer_name && <span>🏢 {meeting.customer_name}</span>}
          {meeting?.object_name && <span>📍 {meeting.object_name}</span>}
        </div>

        <div style={{ ...styles.status, color: statusColor }}>
          <span style={{ ...styles.statusDot, background: statusColor }} />
          {status}
        </div>

        {/* Уровень звука */}
        <div style={styles.levelTrack}>
          <div style={{ ...styles.levelFill, width: `${Math.round(level * 100)}%` }} />
        </div>

        {/* Таймер */}
        <div style={styles.timer}>{mm}:{ss}</div>

        {/* Большая кнопка */}
        {!canSendAudio ? (
          <>
            <button style={styles.btnDisabled} disabled>🎙 Запись недоступна</button>
            <div style={styles.permNote}>
              У вас есть доступ к просмотру встречи, но нет права запускать запись.
            </div>
          </>
        ) : isActiveSource && recording ? (
          <button style={styles.btnStop} onClick={handleStop}>■ Остановить запись</button>
        ) : (
          <button
            style={activeAudioSource ? styles.btnDisabled : styles.btnStart}
            onClick={handleStart}
            disabled={!isConnected || (!!activeAudioSource && !isActiveSource)}
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
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100vh', background: theme.bg.primary, color: theme.text.primary, fontFamily: theme.font.body },
  header: { height: 48, flexShrink: 0, display: 'flex', alignItems: 'center', padding: '0 12px', borderBottom: `1px solid ${theme.border.default}`, background: theme.bg.secondary },
  back: { background: 'transparent', border: 'none', color: theme.accent.amber, cursor: 'pointer', fontSize: 13, fontFamily: theme.font.mono },
  body: { flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: '24px 18px', maxWidth: 480, width: '100%', margin: '0 auto', boxSizing: 'border-box' as const },
  title: { fontFamily: theme.font.heading, fontWeight: 800, fontSize: 20, textAlign: 'center' as const },
  meta: { display: 'flex', gap: 12, flexWrap: 'wrap' as const, justifyContent: 'center', fontFamily: theme.font.mono, fontSize: 12, color: theme.text.secondary },
  status: { display: 'flex', alignItems: 'center', gap: 8, fontFamily: theme.font.mono, fontSize: 13, marginTop: 4 },
  statusDot: { width: 8, height: 8, borderRadius: '50%' },
  levelTrack: { width: '100%', height: 8, background: theme.bg.tertiary, borderRadius: 6, overflow: 'hidden', border: `1px solid ${theme.border.default}` },
  levelFill: { height: '100%', background: theme.accent.green, transition: 'width 0.08s linear' },
  timer: { fontFamily: theme.font.mono, fontSize: 40, fontWeight: 700, letterSpacing: '0.08em', color: theme.text.primary },
  btnStart: { width: '100%', maxWidth: 320, padding: '20px', background: theme.accent.amber, border: 'none', borderRadius: 16, color: '#080A0F', fontSize: 18, fontWeight: 700, cursor: 'pointer', fontFamily: theme.font.body },
  btnStop: { width: '100%', maxWidth: 320, padding: '20px', background: theme.accent.red, border: 'none', borderRadius: 16, color: '#fff', fontSize: 18, fontWeight: 700, cursor: 'pointer', fontFamily: theme.font.body },
  btnDisabled: { width: '100%', maxWidth: 320, padding: '20px', background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 16, color: theme.text.muted, fontSize: 16, fontWeight: 600, cursor: 'not-allowed', fontFamily: theme.font.body },
  permNote: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, textAlign: 'center' as const, lineHeight: 1.5, maxWidth: 320 },
  err: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 12, textAlign: 'center' as const },
  transcript: { width: '100%', background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 },
  transcriptLabel: { fontFamily: theme.font.mono, fontSize: 10, letterSpacing: '0.12em', color: theme.accent.amber },
  line: { fontSize: 13, color: theme.text.secondary, lineHeight: 1.5 },
  speaker: { color: theme.accent.amber, fontFamily: theme.font.mono, fontSize: 11 },
};
