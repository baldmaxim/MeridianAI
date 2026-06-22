import { useEffect, useMemo, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import type { PublicSpeakerSide } from '../../types';
import { toPublicSpeakerSide, speakerSideLabel, speakerSideColor } from '../../lib/speakerSides';
import { Select } from '../common';

const MAX_SPEAKER_OPTIONS = [2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: String(n) }));

interface SpeakerSideAssignmentPanelProps {
  meetingId: number | null;
  canEdit?: boolean;
  compact?: boolean;
  onSetSpeakerSide: (speaker: string, side: PublicSpeakerSide | '' | null) => void | Promise<void>;
  // Назначить человекочитаемое имя метке спикера (SM_0 → «Иван»)
  onSetSpeakerName?: (speaker: string, displayName: string) => void | Promise<void>;
  // Задать ожидаемое число спикеров для диаризации (per-meeting). undefined → контрол скрыт.
  onSetMaxSpeakers?: (n: number) => void;
}

// Идентификация спикеров: имя каждого голоса + сторона «Мы»/«Не мы». Метка вида SM_0 —
// это сырой ярлык STT; имя задаётся вручную и применяется по всему транскрипту.
export function SpeakerSideAssignmentPanel({ canEdit = true, compact, onSetSpeakerSide, onSetSpeakerName, onSetMaxSpeakers }: SpeakerSideAssignmentPanelProps) {
  const turns = useMeetingStore((s) => s.turns);
  const messages = useMeetingStore((s) => s.messages);
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const treeUnassigned = useMeetingStore((s) => s.treeUnassigned);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);
  const speakerNames = useMeetingStore((s) => s.speakerNames);
  const maxSpeakers = useMeetingStore((s) => s.maxSpeakers);
  const isListening = useMeetingStore((s) => s.isListening);

  const speakers = useMemo(() => {
    const set = new Set<string>();
    turns.forEach((t) => t.speaker && set.add(t.speaker));
    messages.forEach((m) => m.speaker && set.add(m.speaker));
    committedSegments.forEach((s) => { if (s.speaker) set.add(s.speaker); });
    treeUnassigned.forEach((n) => n && set.add(n));
    Object.keys(speakerRoles).forEach((n) => n && set.add(n));
    Object.keys(speakerNames).forEach((n) => n && set.add(n));
    const list = Array.from(set);
    // unassigned первыми, потом assigned; внутри — по имени
    return list.sort((a, b) => {
      const aa = toPublicSpeakerSide(speakerRoles[a]) === '' ? 0 : 1;
      const bb = toPublicSpeakerSide(speakerRoles[b]) === '' ? 0 : 1;
      if (aa !== bb) return aa - bb;
      return a.localeCompare(b, 'ru');
    });
  }, [turns, messages, committedSegments, treeUnassigned, speakerRoles, speakerNames]);

  const assignedCount = speakers.filter((s) => toPublicSpeakerSide(speakerRoles[s]) !== '').length;
  const allAssigned = speakers.length > 0 && assignedCount === speakers.length;

  return (
    <div style={{ ...styles.panel, ...(allAssigned ? styles.panelMuted : {}) }}>
      <div style={styles.head}>
        <span style={styles.title}>Спикеры</span>
        {speakers.length > 0 && <span style={styles.counter}>Назначено {assignedCount}/{speakers.length}</span>}
      </div>
      {onSetMaxSpeakers && (
        <div style={styles.countRow}>
          <span style={styles.countLabel}>Ожидается спикеров</span>
          <Select
            value={String(maxSpeakers || 3)}
            onChange={(v) => onSetMaxSpeakers(Number(v))}
            options={MAX_SPEAKER_OPTIONS}
            style={styles.countSelect}
            ariaLabel="Ожидаемое число спикеров"
          />
        </div>
      )}
      {onSetMaxSpeakers && isListening && (
        <div style={styles.countHint}>Изменение применится сразу — распознавание перезапустится.</div>
      )}
      {!compact && (
        <div style={styles.hint}>
          Впишите имя каждого голоса — оно подставится по всему транскрипту. Сторону «Мы»/«Не мы» выбирайте отдельно.
        </div>
      )}

      {speakers.length === 0 ? (
        <div style={styles.empty}>Спикеры появятся после первых реплик.</div>
      ) : (
        <div style={styles.list}>
          {speakers.map((name) => {
            const side = toPublicSpeakerSide(speakerRoles[name]);
            const canName = canEdit && !!onSetSpeakerName;
            return (
              <div key={name} style={styles.row}>
                <div style={styles.idCol}>
                  {canName ? (
                    <NameInput
                      value={speakerNames[name] || ''}
                      placeholder={name}
                      onCommit={(v) => onSetSpeakerName!(name, v)}
                    />
                  ) : (
                    <span style={styles.name} title={name}>{speakerNames[name] || name}</span>
                  )}
                  <span style={styles.rawLabel} title="Метка распознавания">{name}</span>
                </div>
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
                      <button type="button" style={styles.clearBtn} onClick={() => onSetSpeakerSide(name, '')} title="Очистить сторону">✕</button>
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

// Поле имени спикера: локальный draft, коммит по blur/Enter, синк при внешнем изменении.
function NameInput({ value, placeholder, onCommit }: {
  value: string; placeholder: string; onCommit: (v: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  const commit = () => { if (draft.trim() !== value.trim()) onCommit(draft); };
  return (
    <input
      style={styles.nameInput}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
    />
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
  countRow: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
    padding: '6px 0',
  },
  countLabel: { fontSize: 12, fontWeight: 600, color: theme.text.primary },
  countSelect: {
    padding: '5px 10px', minWidth: 64,
    background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6,
    color: theme.text.primary, fontSize: 12, fontFamily: theme.font.body, flexShrink: 0,
  },
  countHint: { fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, lineHeight: 1.4 },
  hint: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, lineHeight: 1.4 },
  empty: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  row: { display: 'flex', alignItems: 'center', gap: 8 },
  idCol: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 },
  name: {
    minWidth: 0, fontSize: 12, fontWeight: 600, color: theme.text.primary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  },
  nameInput: {
    width: '100%', boxSizing: 'border-box' as const, padding: '5px 8px',
    background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6,
    color: theme.text.primary, fontSize: 12, fontWeight: 600, fontFamily: theme.font.body,
  },
  rawLabel: {
    fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted,
    letterSpacing: '0.04em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
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
