import { useMemo } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import type { PublicSpeakerSide } from '../../types';
import { toPublicSpeakerSide, speakerSideLabel, speakerSideColor } from '../../lib/speakerSides';
import { Select } from '../common';
import { SpeakerNameInput } from './SpeakerNameInput';
import styles from './SpeakerSideAssignmentPanel.module.css';

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
    <div className={`${styles.panel} ${allAssigned ? styles.panelMuted : ''}`}>
      <div className={styles.head}>
        <span className={styles.title}>Спикеры</span>
        {speakers.length > 0 && <span className={styles.counter}>Назначено {assignedCount}/{speakers.length}</span>}
      </div>
      {onSetMaxSpeakers && (
        <div className={styles.countRow}>
          <span className={styles.countLabel}>Ожидается спикеров</span>
          <Select
            value={String(maxSpeakers || 3)}
            onChange={(v) => onSetMaxSpeakers(Number(v))}
            options={MAX_SPEAKER_OPTIONS}
            triggerClassName={styles.countSelect}
            ariaLabel="Ожидаемое число спикеров"
          />
        </div>
      )}
      {onSetMaxSpeakers && isListening && (
        <div className={styles.countHint}>Изменение применится сразу — распознавание перезапустится.</div>
      )}
      {!compact && (
        <div className={styles.hint}>
          Впишите имя каждого голоса — оно подставится по всему транскрипту. Сторону «Мы»/«Не мы» выбирайте отдельно.
        </div>
      )}

      {speakers.length === 0 ? (
        <div className={styles.empty}>Спикеры появятся после первых реплик.</div>
      ) : (
        <div className={styles.list}>
          {speakers.map((name) => {
            const side = toPublicSpeakerSide(speakerRoles[name]);
            const canName = canEdit && !!onSetSpeakerName;
            return (
              <div key={name} className={styles.row}>
                <div className={styles.idCol}>
                  {canName ? (
                    <SpeakerNameInput
                      value={speakerNames[name] || ''}
                      placeholder={name}
                      onCommit={(v) => onSetSpeakerName!(name, v)}
                    />
                  ) : (
                    <span className={styles.name} title={name}>{speakerNames[name] || name}</span>
                  )}
                  <span className={styles.rawLabel} title="Метка распознавания">{name}</span>
                </div>
                {canEdit ? (
                  <div className={styles.btns}>
                    <button
                      type="button"
                      className={side === 'self' ? styles.btnSelfOn : styles.btnOff}
                      onClick={() => onSetSpeakerSide(name, 'self')}
                    >Мы</button>
                    <button
                      type="button"
                      className={side === 'opponent' ? styles.btnOppOn : styles.btnOff}
                      onClick={() => onSetSpeakerSide(name, 'opponent')}
                    >Не мы</button>
                    {side !== '' && (
                      <button type="button" className={styles.clearBtn} onClick={() => onSetSpeakerSide(name, '')} title="Очистить сторону">✕</button>
                    )}
                  </div>
                ) : (
                  <span className={styles.roBadge} style={{ color: speakerSideColor(side) }}>{speakerSideLabel(side)}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
