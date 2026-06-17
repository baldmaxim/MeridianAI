import { useMemo } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import type { PublicSpeakerSide } from '../../types';
import { toPublicSpeakerSide, speakerSideLabel, speakerSideColor } from '../../lib/speakerSides';

interface SpeakerSideAssignmentPanelProps {
  meetingId: number | null;
  canEdit?: boolean;
  compact?: boolean;
  onSetSpeakerSide: (speaker: string, side: PublicSpeakerSide | '' | null) => void | Promise<void>;
}

// Быстрое назначение стороны спикерам: «Мы» / «Не мы». Speaker label — это метка STT,
// а не имя человека; для подсказок достаточно двух сторон.
export function SpeakerSideAssignmentPanel({ canEdit = true, compact, onSetSpeakerSide }: SpeakerSideAssignmentPanelProps) {
  const turns = useMeetingStore((s) => s.turns);
  const messages = useMeetingStore((s) => s.messages);
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const treeUnassigned = useMeetingStore((s) => s.treeUnassigned);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);

  const speakers = useMemo(() => {
    const set = new Set<string>();
    turns.forEach((t) => t.speaker && set.add(t.speaker));
    messages.forEach((m) => m.speaker && set.add(m.speaker));
    committedSegments.forEach((s) => { if (s.speaker) set.add(s.speaker); });
    treeUnassigned.forEach((n) => n && set.add(n));
    Object.keys(speakerRoles).forEach((n) => n && set.add(n));
    const list = Array.from(set);
    // unassigned первыми, потом assigned; внутри — по имени
    return list.sort((a, b) => {
      const aa = toPublicSpeakerSide(speakerRoles[a]) === '' ? 0 : 1;
      const bb = toPublicSpeakerSide(speakerRoles[b]) === '' ? 0 : 1;
      if (aa !== bb) return aa - bb;
      return a.localeCompare(b, 'ru');
    });
  }, [turns, messages, committedSegments, treeUnassigned, speakerRoles]);

  const assignedCount = speakers.filter((s) => toPublicSpeakerSide(speakerRoles[s]) !== '').length;
  const allAssigned = speakers.length > 0 && assignedCount === speakers.length;

  return (
    <div style={{ ...styles.panel, ...(allAssigned ? styles.panelMuted : {}) }}>
      <div style={styles.head}>
        <span style={styles.title}>Стороны спикеров</span>
        {speakers.length > 0 && <span style={styles.counter}>Назначено {assignedCount}/{speakers.length}</span>}
      </div>
      {!compact && (
        <div style={styles.hint}>
          Назначьте, кто говорит от нашей стороны, а кто от другой. Для подсказок достаточно двух сторон.
        </div>
      )}

      {speakers.length === 0 ? (
        <div style={styles.empty}>Спикеры появятся после первых реплик.</div>
      ) : (
        <div style={styles.list}>
          {speakers.map((name) => {
            const side = toPublicSpeakerSide(speakerRoles[name]);
            return (
              <div key={name} style={styles.row}>
                <span style={styles.name} title={name}>{name}</span>
                {canEdit ? (
                  <div style={styles.btns}>
                    <button
                      type="button"
                      style={side === 'self' ? styles.btnSelfOn : styles.btnOff}
                      onClick={() => onSetSpeakerSide(name, 'self')}
                    >Мы</button>
                    <button
                      type="button"
                      style={side === 'opponent' ? styles.btnOppOn : styles.btnOff}
                      onClick={() => onSetSpeakerSide(name, 'opponent')}
                    >Не мы</button>
                    {side !== '' && (
                      <button type="button" style={styles.clearBtn} onClick={() => onSetSpeakerSide(name, '')} title="Очистить">✕</button>
                    )}
                  </div>
                ) : (
                  <span style={{ ...styles.roBadge, color: speakerSideColor(side) }}>{speakerSideLabel(side)}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: {
    display: 'flex', flexDirection: 'column', gap: 8, padding: 10, marginBottom: 8,
    background: theme.bg.elevated, border: `1px solid ${theme.border.amber}`, borderRadius: 9,
  },
  panelMuted: { borderColor: theme.border.default, opacity: 0.8 },
  head: { display: 'flex', alignItems: 'baseline', gap: 8 },
  title: {
    flex: 1, fontFamily: theme.font.heading, fontWeight: 700, fontSize: 10,
    letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: theme.text.primary,
  },
  counter: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.secondary },
  hint: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, lineHeight: 1.4 },
  empty: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  list: { display: 'flex', flexDirection: 'column', gap: 6 },
  row: { display: 'flex', alignItems: 'center', gap: 8 },
  name: {
    flex: 1, minWidth: 0, fontSize: 12, fontWeight: 600, color: theme.text.primary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  },
  btns: { display: 'flex', gap: 4, flexShrink: 0 },
  btnOff: {
    padding: '4px 9px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  btnSelfOn: {
    padding: '4px 9px', background: 'rgba(46,229,157,0.12)', border: `1px solid ${theme.accent.green}`,
    borderRadius: 6, color: theme.accent.green, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  btnOppOn: {
    padding: '4px 9px', background: 'rgba(255,75,110,0.12)', border: `1px solid ${theme.accent.red}`,
    borderRadius: 6, color: theme.accent.red, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  clearBtn: {
    padding: '4px 8px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.muted, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  roBadge: { fontFamily: theme.font.mono, fontSize: 10, fontWeight: 700, flexShrink: 0 },
};
