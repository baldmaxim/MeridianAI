import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { getSpeakerTextColor } from '../../styles/theme';
import { withAlpha } from '../../utils/cssVar';
import type { PublicSpeakerSide, MultiChannelReconciliationEntry } from '../../types';
import { nextPublicSpeakerSide, speakerSideBadge, speakerSideColor, speakerSideLabel } from '../../lib/speakerSides';
import { resolveSegmentSide, resolveSegmentSpeaker, isSegmentCorrected, segmentKeyForMessage } from '../../lib/segmentCorrections';
import styles from './ChatDisplay.module.css';

interface SegmentCorrectionPatch {
  side?: PublicSpeakerSide | '';
  correctedSpeakerLabel?: string | null;
}

interface ChatDisplayProps {
  onSetSpeakerRole?: (name: string, side: PublicSpeakerSide | '') => void;
  // Этап 8: исправить сторону ОДНОЙ реплики (клик по бейджу — цикл стороны)
  onCorrectSegment?: (segmentKey: string, originalSpeaker: string) => void;
  // Этап 8.1: явная коррекция реплики (сторона и/или corrected_speaker_label) из меню
  onSetSegmentCorrection?: (segmentKey: string, originalSpeaker: string, patch: SegmentCorrectionPatch) => void;
}

export function ChatDisplay({ onSetSpeakerRole, onCorrectSegment, onSetSegmentCorrection }: ChatDisplayProps) {
  const messages = useMeetingStore((s) => s.messages);
  const turns = useMeetingStore((s) => s.turns);
  const partialMessage = useMeetingStore((s) => s.partialMessage);
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);
  const speakerNames = useMeetingStore((s) => s.speakerNames);
  const speakerCorrections = useMeetingStore((s) => s.speakerCorrections);
  const segmentHints = useMeetingStore((s) => s.segmentHints);
  const dismissSegmentHint = useMeetingStore((s) => s.dismissSegmentHint);
  // Этап 9.7: channel evidence по committed-реплике (только matched, не dismissed)
  const reconciliation = useMeetingStore((s) => s.multiChannelReconciliation);
  const dismissedRecon = useMeetingStore((s) => s.dismissedReconciliationEntries);
  const reconByKey = useMemo(() => {
    const m: Record<string, MultiChannelReconciliationEntry> = {};
    for (const e of reconciliation?.entries ?? []) {
      if (e.kind === 'matched' && e.primary_segment_key && !dismissedRecon[e.entry_id]) {
        m[e.primary_segment_key] = e;
      }
    }
    return m;
  }, [reconciliation, dismissedRecon]);
  // Этап 9.8: авторитетный источник транскрипта (баннер при multi-channel)
  const authority = useMeetingStore((s) => s.transcriptionAuthority);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [menuKey, setMenuKey] = useState<string | null>(null);

  // Известные speaker labels (для «исправить speaker label»)
  const knownLabels = useMemo(() => {
    const set = new Set<string>();
    messages.forEach((m) => m.speaker && set.add(m.speaker));
    turns.forEach((t) => t.speaker && set.add(t.speaker));
    Object.keys(speakerRoles).forEach((n) => n && set.add(n));
    Object.values(speakerCorrections).forEach((c) => {
      if (c.corrected_speaker_label) set.add(c.corrected_speaker_label);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ru'));
  }, [messages, turns, speakerRoles, speakerCorrections]);

  // Цикл двух сторон: Не назначено → Мы → Не мы → Не назначено
  const cycleSpeakerRole = useCallback((name: string) => {
    if (!onSetSpeakerRole) return;
    onSetSpeakerRole(name, nextPublicSpeakerSide(speakerRoles[name]));
  }, [speakerRoles, onSetSpeakerRole]);

  const hasTurns = turns.length > 0;

  // Lookup for low-confidence segments
  const lowConfidenceIds = new Set(
    committedSegments
      .filter((s) => s.confidence !== null && s.confidence < -1.0)
      .map((s) => s.segment_id)
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turns, partialMessage]);

  return (
    <div className={`chat-display ${styles.container}`}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Транскрипция</span>
        {authority?.current_source === 'multi_channel' && (
          <span className={styles.authBadge} title="Авторитетный источник — multi-channel">
            multi-channel
          </span>
        )}
      </div>
      {authority?.current_source === 'multi_channel' && (
        <div className={styles.authBanner}>
          Авторитетный транскрипт ведётся по multi-channel. Single STT продолжает работать как резерв.
        </div>
      )}
      <div className={styles.messages}>
        {!hasTurns && messages.length === 0 && (
          <div className={styles.placeholder}>
            Транскрипция появится здесь...
          </div>
        )}
        {hasTurns
          ? turns.map((turn) => {
              const badge = speakerSideBadge(speakerRoles[turn.speaker]);
              const badgeColor = speakerSideColor(speakerRoles[turn.speaker]);
              return (
                <div key={turn.turn_id} className={styles.message}>
                  <span
                    className={`${styles.speaker} ${onSetSpeakerRole ? styles.speakerClickable : ''}`}
                    style={{ color: getSpeakerTextColor(turn.speaker) }}
                    onClick={() => cycleSpeakerRole(turn.speaker)}
                    title={onSetSpeakerRole ? 'Нажмите для смены стороны: Мы / Не мы' : undefined}
                  >
                    {speakerNames[turn.speaker] || turn.speaker}
                    {badge && (
                      <span className={styles.roleBadge} style={{ background: withAlpha(badgeColor, 15), color: badgeColor }}>{badge}</span>
                    )}
                  </span>
                  <span className={styles.text}>{turn.text}</span>
                </div>
              );
            })
          : messages.map((msg) => {
              const isLowConf = lowConfidenceIds.has(msg.id);
              const segKey = segmentKeyForMessage(msg);
              const segSide = resolveSegmentSide(segKey, msg.speaker, speakerCorrections, speakerRoles);
              const corrected = isSegmentCorrected(speakerCorrections, segKey);
              const effectiveSpeaker = resolveSegmentSpeaker(segKey, msg.speaker, speakerCorrections, speakerNames);
              const badge = speakerSideBadge(segSide);
              const badgeColor = speakerSideColor(segSide);
              const canEdit = !!onSetSegmentCorrection || !!onCorrectSegment;
              return (
                <div
                  key={msg.id}
                  className={`${styles.message} ${isLowConf ? styles.messageLowConf : ''}`}
                >
                  <span className={styles.speakerRow}>
                    <span
                      className={`${styles.speaker} ${onCorrectSegment ? styles.speakerClickable : ''}`}
                      style={{ color: getSpeakerTextColor(effectiveSpeaker) }}
                      onClick={onCorrectSegment ? () => onCorrectSegment(segKey, msg.speaker) : undefined}
                      title={onCorrectSegment ? 'Исправить сторону этой реплики: Мы / Не мы' : undefined}
                    >
                      {effectiveSpeaker}
                      {badge && (
                        <span className={styles.roleBadge} style={{ background: withAlpha(badgeColor, 15), color: badgeColor }}>{badge}</span>
                      )}
                      {corrected && <span className={styles.correctedMark} title="Спикер/сторона этой реплики исправлены вручную">✎</span>}
                      {isLowConf && (
                        <span className={styles.lowConfBadge} title="Низкая уверенность транскрипции">?</span>
                      )}
                      {(() => {
                        // Этап 9.7: channel evidence chip (display-only; применение — в панели)
                        const re = reconByKey[segKey];
                        if (!re) return null;
                        if (re.side_agreement === 'confirmed') {
                          return <span className={styles.reconConfirmed} title="Канал подтверждает текущую сторону">канал ✓</span>;
                        }
                        if (re.side_agreement === 'conflict') {
                          const sd = re.channel_side === 'self' ? 'Мы' : 'Не мы';
                          return <span className={styles.reconConflict} title={`Канал ${(re.channel_index ?? 0) + 1}: ${(re.match_score * 100).toFixed(0)}% совпадение`}>конфликт: канал «{sd}»</span>;
                        }
                        if (re.can_apply_side && re.channel_side) {
                          const sd = re.channel_side === 'self' ? 'Мы' : 'Не мы';
                          return <span className={styles.reconSuggest} title={`Канал ${(re.channel_index ?? 0) + 1} · ${(re.hint_confidence * 100).toFixed(0)}% — применить в панели «Сопоставление»`}>канал: вероятно {sd} · {(re.hint_confidence * 100).toFixed(0)}%</span>;
                        }
                        return null;
                      })()}
                    </span>
                    {canEdit && onSetSegmentCorrection && (
                      <button
                        type="button"
                        className={styles.menuBtn}
                        onClick={() => setMenuKey(menuKey === segKey ? null : segKey)}
                        title="Исправить эту реплику"
                        aria-label="Исправить эту реплику"
                      >⋯</button>
                    )}
                  </span>
                  {(() => {
                    // Этап 9: observer-подсказка — показываем, пока реплика не исправлена вручную
                    const hint = segmentHints[segKey];
                    if (!hint || !hint.side || corrected) return null;
                    return (
                      <div className={styles.hintRow}>
                        <span className={styles.hintText}>
                          Наблюдатель: вероятно «{speakerSideLabel(hint.side)}» ({Math.round(hint.confidence * 100)}%)
                        </span>
                        {onSetSegmentCorrection && (
                          <button type="button" className={styles.hintApply}
                            onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: hint.side! }); dismissSegmentHint(segKey); }}>
                            Применить
                          </button>
                        )}
                        <button type="button" className={styles.hintSkip} onClick={() => dismissSegmentHint(segKey)}>Скрыть</button>
                      </div>
                    );
                  })()}
                  {menuKey === segKey && onSetSegmentCorrection && (
                    <div className={styles.menu}>
                      <button type="button" className={styles.menuItem}
                        onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: 'self' }); setMenuKey(null); }}>
                        Эта реплика: Мы
                      </button>
                      <button type="button" className={styles.menuItem}
                        onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: 'opponent' }); setMenuKey(null); }}>
                        Эта реплика: Не мы
                      </button>
                      <div className={styles.menuLabelTitle}>Исправить speaker label</div>
                      <div className={styles.menuLabels}>
                        {knownLabels.filter((l) => l !== effectiveSpeaker).map((l) => (
                          <button key={l} type="button" className={styles.menuLabelBtn}
                            onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { correctedSpeakerLabel: l }); setMenuKey(null); }}>
                            {l}
                          </button>
                        ))}
                        {knownLabels.filter((l) => l !== effectiveSpeaker).length === 0 && (
                          <span className={styles.menuEmpty}>нет других меток</span>
                        )}
                      </div>
                      {corrected && (
                        <button type="button" className={styles.menuReset}
                          onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: '', correctedSpeakerLabel: null }); setMenuKey(null); }}>
                          Сбросить исправление
                        </button>
                      )}
                    </div>
                  )}
                  <span className={styles.text}>{msg.text}</span>
                </div>
              );
            })}
        {partialMessage && (
          <div className={`${styles.message} ${styles.messagePartial}`}>
            <span className={styles.speaker} style={{ color: getSpeakerTextColor(partialMessage.speaker) }}>
              {partialMessage.speaker}
            </span>
            <span className={styles.text}>{partialMessage.text}</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
