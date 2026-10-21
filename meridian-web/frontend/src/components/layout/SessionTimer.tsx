import { useEffect, useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './SessionTimer.module.css';

export const SessionTimer: FC = () => {
  const isListening = useMeetingStore((s) => s.isListening);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!isListening) return;
    const start = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => {
      clearInterval(timer);
      setElapsed(0); // сброс при остановке сессии (в cleanup, а не в теле эффекта)
    };
  }, [isListening]);

  if (!isListening) return null;

  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');

  return (
    <div className={`header-session-group ${styles.group}`}>
      <span className={`header-session-badge ${styles.badge}`}>
        <span className={`pulse-dot ${styles.dot}`} />
        <span className="header-session-text">СЕССИЯ АКТИВНА</span>
      </span>
      <span className={`header-timer ${styles.timer}`}>{h} : {m} : {s}</span>
      {/* Compact mobile badge: dot + mm:ss */}
      <span className={`header-session-compact ${styles.compact}`}>
        <span className={`pulse-dot ${styles.dot}`} />
        {m}:{s}
      </span>
    </div>
  );
};
