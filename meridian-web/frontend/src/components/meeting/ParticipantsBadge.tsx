import { useState, useRef, useCallback } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { uniqueParticipantUsers, deviceRoleLabel, type ParticipantUser } from '../../lib/participants';
import { theme } from '../../styles/theme';

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
      style={styles.wrap}
      onMouseEnter={show}
      onMouseLeave={hideSoon}
    >
      <button
        type="button"
        className="t-btn"
        style={styles.badge}
        onClick={() => setOpen((v) => !v)}
        aria-label={`Участников: ${users.length}`}
      >
        <span style={styles.icon}>👥</span>
        <span style={styles.count}>{users.length}</span>
      </button>
      {open && (
        <div style={styles.popover} onMouseEnter={show} onMouseLeave={hideSoon}>
          <div style={styles.popHeader}>В комнате</div>
          {users.map((u, i) => (
            <UserRow key={u.userId != null ? `u${u.userId}` : `g${i}`} user={u} />
          ))}
        </div>
      )}
    </div>
  );
}

function UserRow({ user }: { user: ParticipantUser }) {
  const devices = user.roles.map(deviceRoleLabel).join(', ');
  return (
    <div style={styles.row}>
      <div style={styles.rowMain}>
        <span style={styles.name}>{user.label}</span>
        <span style={styles.devices}>{devices}</span>
      </div>
      <div style={styles.tags}>
        {user.isRecording && <span style={{ ...styles.tag, ...styles.tagRec }}>пишет звук</span>}
        {user.isHelper && <span style={{ ...styles.tag, ...styles.tagHelp }}>помогает</span>}
        {!user.isRecording && !user.isHelper && (
          <span style={{ ...styles.tag, ...styles.tagIdle }}>наблюдает</span>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { position: 'relative', marginLeft: 'auto', flexShrink: 0 },
  badge: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px',
    background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 20, color: theme.text.secondary, cursor: 'pointer',
    fontFamily: theme.font.mono, fontSize: 12,
  },
  icon: { fontSize: 13, lineHeight: 1 },
  count: { fontWeight: 700, color: theme.text.primary, letterSpacing: '0.02em' },
  popover: {
    position: 'absolute', top: 'calc(100% + 8px)', right: 0, zIndex: 60,
    minWidth: 240, maxWidth: 320, padding: 10,
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`,
    borderRadius: 10, boxShadow: '0 10px 30px rgba(0,0,0,0.45)',
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  popHeader: {
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.12em',
    textTransform: 'uppercase', color: theme.text.muted, padding: '2px 4px 4px',
  },
  row: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
    padding: '6px 4px', borderTop: `1px solid ${theme.border.default}`,
  },
  rowMain: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 },
  name: {
    fontFamily: theme.font.body, fontSize: 13, fontWeight: 600, color: theme.text.primary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  devices: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  tags: { display: 'flex', gap: 4, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' },
  tag: {
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.04em',
    padding: '2px 7px', borderRadius: 10, whiteSpace: 'nowrap',
  },
  tagRec: { background: 'rgba(46,229,157,0.14)', color: theme.accent.green, border: `1px solid ${theme.accent.green}` },
  tagHelp: { background: 'rgba(245,166,35,0.14)', color: theme.accent.amber, border: `1px solid ${theme.border.amber}` },
  tagIdle: { background: theme.bg.tertiary, color: theme.text.muted, border: `1px solid ${theme.border.default}` },
};
