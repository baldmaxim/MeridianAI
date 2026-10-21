import { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useWakeLock } from '../hooks/useWakeLock';
import { useMeetingStore } from '../store/meetingStore';
import { getMobileMeeting } from '../api/mobile';
import { navigate } from '../lib/navigation';
import type { MobileMeetingDetail } from '../types';
import styles from './RecorderPage.module.css';
import { cx } from '../utils/cx';

interface Props {
  meetingId: number;
}

export function RecorderPage({ meetingId }: Props) {
  const [closed, setClosed] = useState(false);
  const { connect, disconnect, sendJSON, sendBinary } = useWebSocket(() => setClosed(true));
  const [level, setLevel] = useState(0);
  const [micOn, setMicOn] = useState(false);
  const [paused, setPaused] = useState(false);
  // Wake Lock: не даём экрану авто-гаснуть во время записи (см. useWakeLock).
  const wakeLock = useWakeLock();
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

  // Прерывание захвата ОС (экран заблокирован/звонок). Обработчики снимаются в stop(),
  // поэтому колбэк прилетает только во время активной записи.
  const onMicInterrupt = useCallback(() => setPaused(true), []);
  const { start: startMic, stop: stopMic } = useAudioRecorder(guardedSend, setLevel, onMicInterrupt);

  // подключение к комнате как phone
  useEffect(() => {
    getMobileMeeting(meetingId).then(setMeeting).catch(() => { /* заголовок встречи необязателен — запись работает и без него */ });
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
      wakeLock.release();
      setMicOn(false);
      setPaused(false);
    }
  }, [recordPermissionDenied, micOn, stopMic, wakeLock]);

  // источник занят другим устройством — освобождаем микрофон
  useEffect(() => {
    if (micOn && activeAudioSource && !isActiveSource) {
      stopMic();
      wakeLock.release();
      setMicOn(false);
      setPaused(false);
    }
  }, [micOn, activeAudioSource, isActiveSource, stopMic, wakeLock]);

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
      void wakeLock.request();
      setMicOn(true);
      setPaused(false);
      sendJSON({ type: 'start_audio' });
    } catch {
      useMeetingStore.getState().setError('Не удалось получить доступ к микрофону');
      setMicOn(false);
    }
  };

  const handleStop = () => {
    stopMic();
    wakeLock.release();
    setMicOn(false);
    setPaused(false);
    sendJSON({ type: 'stop_audio' });
  };

  // Возобновление после прерывания ОС: пересоздаём захват (старый трек/контекст мертвы).
  // Тап = user-gesture, который iOS требует для повторного getUserMedia.
  const handleResume = async () => {
    try {
      stopMic();
      await startMic();
      void wakeLock.request();
      sendJSON({ type: 'start_audio' });
      setPaused(false);
    } catch {
      useMeetingStore.getState().setError('Не удалось возобновить запись');
      setMicOn(false);
    }
  };

  let status: string;
  let statusTone: string;
  if (recordPermissionDenied) { status = 'Нет прав на запись'; statusTone = styles.statusRed; }
  else if (!isConnected) { status = 'Нет соединения'; statusTone = styles.statusRed; }
  else if (isActiveSource && recording) { status = 'Идёт запись'; statusTone = styles.statusGreen; }
  else if (activeAudioSource && !isActiveSource) { status = 'Источник аудио занят'; statusTone = styles.statusAmber; }
  else { status = 'Подключено'; statusTone = styles.statusGreen; }

  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  const lastLines = messages.slice(-5);

  if (closed) {
    return (
      <div className={styles.root}>
        <div className={cx(styles.body, styles.bodyCentered)}>
          <div className={styles.title}>Встреча удалена</div>
          <div className={styles.permNote}>Эта встреча была удалена. Запись недоступна.</div>
          <button className={styles.btnStart} onClick={() => navigate('/mobile/meetings')}>К списку встреч</button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <header className={styles.header}>
        <button className={styles.back} onClick={() => navigate(`/mobile/meetings/${meetingId}`)}>‹ Назад к встрече</button>
      </header>

      <div className={styles.body}>
        <div className={styles.title}>{meeting?.title || meeting?.meeting_topic || `Встреча #${meetingId}`}</div>
        <div className={styles.meta}>
          {meeting?.customer_name && <span>🏢 {meeting.customer_name}</span>}
          {meeting?.object_name && <span>📍 {meeting.object_name}</span>}
        </div>

        <div className={cx(styles.status, statusTone)}>
          <span className={styles.statusDot} />
          {status}
        </div>

        {/* Уровень звука */}
        <div className={styles.levelTrack}>
          <div className={styles.levelFill} style={{ transform: `scaleX(${Math.round(level * 100) / 100})` }} />
        </div>

        {/* Таймер */}
        <div className={styles.timer}>{mm}:{ss}</div>

        {/* Большая кнопка */}
        {!canSendAudio ? (
          <>
            <button className={styles.btnDisabled} disabled>🎙 Запись недоступна</button>
            <div className={styles.permNote}>
              У вас есть доступ к просмотру встречи, но нет права запускать запись.
            </div>
          </>
        ) : isActiveSource && recording ? (
          <button className={styles.btnStop} onClick={handleStop}>■ Остановить запись</button>
        ) : (
          <button
            className={cx(activeAudioSource ? styles.btnDisabled : styles.btnStart)}
            onClick={handleStart}
            disabled={!isConnected || (!!activeAudioSource && !isActiveSource)}
          >
            ● Начать запись
          </button>
        )}

        {paused && (
          <div className={styles.pausedBanner} role="alert">
            <span>Запись приостановлена — экран был заблокирован.</span>
            <button className={styles.resumeBtn} onClick={handleResume}>Продолжить запись</button>
          </div>
        )}

        {isActiveSource && recording && !paused && (
          <div className={styles.recHint}>
            Не блокируйте экран. На iPhone запись в фоне при выключенном экране невозможна.
          </div>
        )}

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
    </div>
  );
}
