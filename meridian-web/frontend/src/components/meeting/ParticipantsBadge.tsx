import { useState, useRef, useCallback } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { uniqueParticipantUsers } from '../../lib/participants';
import { ParticipantUserRow } from './ParticipantUserRow';
import styles from './ParticipantsBadge.module.css';

// Бейдж участников встречи в шапке: «👥 N» (N — уникальные люди). При наведении/тапе —
// поповер со списком: имя · устройства · роль (пишет звук / помогает распознаванию / наблюдает).
// Авто-обновляется по WS-снапшоту room_participants (без перезагрузки страницы).
export function ParticipantsBadge() {
  const participants = useMeetingStore((s) => s.participants);
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  }, []);
  const hideSoon = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  }, []);

  if (meetingId == null || participants.length === 0) return null;
  const users = uniqueParticipantUsers(participants);

  return (
    <div
      className={styles.wrap}
      onMouseEnter={show}
      onMouseLeave={hideSoon}
    >
      <button
        type="button"
        className={`t-btn ${styles.badge}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={`Участников: ${users.length}`}
      >
        <span className={styles.icon}>👥</span>
        <span className={styles.count}>{users.length}</span>
      </button>
      {open && (
        <div className={styles.popover} onMouseEnter={show} onMouseLeave={hideSoon}>
          <div className={styles.popHeader}>В комнате</div>
          {users.map((u, i) => (
            <ParticipantUserRow key={u.userId != null ? `u${u.userId}` : `g${i}`} user={u} />
          ))}
        </div>
      )}
    </div>
  );
}
