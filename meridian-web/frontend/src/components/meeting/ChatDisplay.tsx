import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme, getSpeakerTextColor } from '../../styles/theme';
import type { PublicSpeakerSide } from '../../types';
import { nextPublicSpeakerSide, speakerSideBadge, speakerSideColor, speakerSideLabel } from '../../lib/speakerSides';
import { resolveSegmentSide, resolveSegmentSpeaker, isSegmentCorrected, segmentKeyForMessage } from '../../lib/segmentCorrections';

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
  const speakerCorrections = useMeetingStore((s) => s.speakerCorrections);
  const segmentHints = useMeetingStore((s) => s.segmentHints);
  const dismissSegmentHint = useMeetingStore((s) => s.dismissSegmentHint);
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
    <div className="chat-display" style={styles.container}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Транскрипция</span>
      </div>
      <div style={styles.messages}>
        {!hasTurns && messages.length === 0 && (
          <div style={styles.placeholder}>
            Транскрипция появится здесь...
          </div>
        )}
        {hasTurns
          ? turns.map((turn) => {
              const badge = speakerSideBadge(speakerRoles[turn.speaker]);
              const badgeColor = speakerSideColor(speakerRoles[turn.speaker]);
              return (
                <div key={turn.turn_id} style={styles.message}>
                  <span
                    style={{ ...styles.speaker, color: getSpeakerTextColor(turn.speaker), cursor: onSetSpeakerRole ? 'pointer' : undefined }}
                    onClick={() => cycleSpeakerRole(turn.speaker)}
                    title={onSetSpeakerRole ? 'Нажмите для смены стороны: Мы / Не мы' : undefined}
                  >
                    {turn.speaker}
                    {badge && (
                      <span style={{ ...styles.roleBadge, background: badgeColor + '25', color: badgeColor }}>{badge}</span>
                    )}
                  </span>
                  <span style={styles.text}>{turn.text}</span>
                </div>
              );
            })
          : messages.map((msg) => {
              const isLowConf = lowConfidenceIds.has(msg.id);
              const segKey = segmentKeyForMessage(msg);
              const segSide = resolveSegmentSide(segKey, msg.speaker, speakerCorrections, speakerRoles);
              const corrected = isSegmentCorrected(speakerCorrections, segKey);
              const effectiveSpeaker = resolveSegmentSpeaker(segKey, msg.speaker, speakerCorrections);
              const badge = speakerSideBadge(segSide);
              const badgeColor = speakerSideColor(segSide);
              const canEdit = !!onSetSegmentCorrection || !!onCorrectSegment;
              return (
                <div
                  key={msg.id}
                  style={{
                    ...styles.message,
                    opacity: isLowConf ? 0.7 : 1,
                  }}
                >
                  <span style={styles.speakerRow}>
                    <span
                      style={{ ...styles.speaker, color: getSpeakerTextColor(effectiveSpeaker), cursor: onCorrectSegment ? 'pointer' : undefined }}
                      onClick={onCorrectSegment ? () => onCorrectSegment(segKey, msg.speaker) : undefined}
                      title={onCorrectSegment ? 'Исправить сторону этой реплики: Мы / Не мы' : undefined}
                    >
                      {effectiveSpeaker}
                      {badge && (
                        <span style={{ ...styles.roleBadge, background: badgeColor + '25', color: badgeColor }}>{badge}</span>
                      )}
                      {corrected && <span style={styles.correctedMark} title="Спикер/сторона этой реплики исправлены вручную">✎</span>}
                      {isLowConf && (
                        <span style={styles.lowConfBadge} title="Низкая уверенность транскрипции">?</span>
                      )}
                    </span>
                    {canEdit && onSetSegmentCorrection && (
                      <button
                        type="button"
                        style={styles.menuBtn}
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
                      <div style={styles.hintRow}>
                        <span style={styles.hintText}>
                          Наблюдатель: вероятно «{speakerSideLabel(hint.side)}» ({Math.round(hint.confidence * 100)}%)
                        </span>
                        {onSetSegmentCorrection && (
                          <button type="button" style={styles.hintApply}
                            onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: hint.side! }); dismissSegmentHint(segKey); }}>
                            Применить
                          </button>
                        )}
                        <button type="button" style={styles.hintSkip} onClick={() => dismissSegmentHint(segKey)}>Скрыть</button>
                      </div>
                    );
                  })()}
                  {menuKey === segKey && onSetSegmentCorrection && (
                    <div style={styles.menu}>
                      <button type="button" style={styles.menuItem}
                        onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: 'self' }); setMenuKey(null); }}>
                        Эта реплика: Мы
                      </button>
                      <button type="button" style={styles.menuItem}
                        onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: 'opponent' }); setMenuKey(null); }}>
                        Эта реплика: Не мы
                      </button>
                      <div style={styles.menuLabelTitle}>Исправить speaker label</div>
                      <div style={styles.menuLabels}>
                        {knownLabels.filter((l) => l !== effectiveSpeaker).map((l) => (
                          <button key={l} type="button" style={styles.menuLabelBtn}
                            onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { correctedSpeakerLabel: l }); setMenuKey(null); }}>
                            {l}
                          </button>
                        ))}
                        {knownLabels.filter((l) => l !== effectiveSpeaker).length === 0 && (
                          <span style={styles.menuEmpty}>нет других меток</span>
                        )}
                      </div>
                      {corrected && (
                        <button type="button" style={styles.menuReset}
                          onClick={() => { onSetSegmentCorrection(segKey, msg.speaker, { side: '', correctedSpeakerLabel: null }); setMenuKey(null); }}>
                          Сбросить исправление
                        </button>
                      )}
                    </div>
                  )}
                  <span style={styles.text}>{msg.text}</span>
                </div>
              );
            })}
        {partialMessage && (
          <div style={{ ...styles.message, opacity: 0.6 }}>
            <span style={{ ...styles.speaker, color: getSpeakerTextColor(partialMessage.speaker) }}>
              {partialMessage.speaker}
            </span>
            <span style={styles.text}>{partialMessage.text}</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    background: theme.bg.tertiary,
    borderRadius: 10,
    border: `1px solid ${theme.border.default}`,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '12px 16px',
    borderBottom: `1px solid ${theme.border.default}`,
    flexShrink: 0,
  },
  dot: {
    width: 6, height: 6, borderRadius: '50%',
    background: theme.accent.amber, flexShrink: 0,
  },
  title: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  messages: {
    flex: 1,
    overflow: 'auto',
    padding: 14,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  placeholder: {
    color: theme.text.muted,
    textAlign: 'center',
    padding: 30,
    fontSize: 12,
    fontFamily: theme.font.mono,
  },
  message: {
    fontSize: 12,
    lineHeight: 1.55,
  },
  speaker: {
    display: 'block',
    fontWeight: 700,
    fontSize: 10,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    fontFamily: theme.font.mono,
    marginBottom: 2,
  },
  text: {
    color: theme.text.primary,
    fontFamily: theme.font.body,
    fontSize: 12,
  },
  roleBadge: {
    display: 'inline-block',
    marginLeft: 6,
    padding: '1px 5px',
    borderRadius: 3,
    fontSize: 8,
    fontWeight: 700,
    letterSpacing: '0.06em',
    verticalAlign: 'middle',
  },
  correctedMark: {
    display: 'inline-block',
    marginLeft: 5,
    fontSize: 9,
    color: theme.accent.amber,
    verticalAlign: 'middle',
  },
  speakerRow: { display: 'flex', alignItems: 'center', gap: 6 },
  hintRow: {
    display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' as const,
    margin: '3px 0', padding: '4px 8px', borderRadius: 6,
    background: theme.accent.amberGlow, border: `1px solid ${theme.border.amber}`,
  },
  hintText: { fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.amber },
  hintApply: {
    padding: '3px 9px', background: theme.accent.amber, border: 'none', borderRadius: 5,
    color: '#080A0F', cursor: 'pointer', fontSize: 10, fontWeight: 600, fontFamily: theme.font.body,
  },
  hintSkip: {
    padding: '3px 8px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 5, color: theme.text.muted, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  menuBtn: {
    padding: '0 6px', height: 16, lineHeight: '14px', background: 'transparent',
    border: `1px solid ${theme.border.default}`, borderRadius: 4, color: theme.text.muted,
    cursor: 'pointer', fontSize: 11, flexShrink: 0,
  },
  menu: {
    display: 'flex', flexDirection: 'column', gap: 4, margin: '4px 0 6px',
    padding: 8, background: theme.bg.elevated, border: `1px solid ${theme.border.default}`,
    borderRadius: 8, maxWidth: 280,
  },
  menuItem: {
    textAlign: 'left' as const, padding: '6px 8px', background: 'transparent',
    border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.primary,
    cursor: 'pointer', fontSize: 11, fontFamily: theme.font.body,
  },
  menuLabelTitle: {
    fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted,
    letterSpacing: '0.06em', textTransform: 'uppercase' as const, marginTop: 2,
  },
  menuLabels: { display: 'flex', flexWrap: 'wrap' as const, gap: 4 },
  menuLabelBtn: {
    padding: '4px 8px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  menuEmpty: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  menuReset: {
    textAlign: 'left' as const, padding: '6px 8px', background: 'transparent',
    border: `1px solid ${theme.accent.red}`, borderRadius: 6, color: theme.accent.red,
    cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono, marginTop: 2,
  },
  lowConfBadge: {
    display: 'inline-block',
    marginLeft: 4,
    width: 14,
    height: 14,
    lineHeight: '14px',
    textAlign: 'center' as const,
    borderRadius: '50%',
    background: theme.accent.amber + '30',
    color: theme.accent.amber,
    fontSize: 9,
    fontWeight: 700,
  },
};
