import { useCallback, useEffect, useRef } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme, getSpeakerTextColor } from '../../styles/theme';
import type { SpeakerSide } from '../../types';

const SIDE_CYCLE: (SpeakerSide | '')[] = ['', 'self', 'opponent', 'ally', 'third_party'];
const SIDE_BADGES: Record<string, string> = { self: 'МЫ', opponent: 'ОПП', ally: 'СОЮЗ', third_party: '3-Я' };
const SIDE_COLORS: Record<string, string> = { self: '#2EE59D', opponent: '#FF4B6E', ally: '#5B9CF6', third_party: '#4A5568' };

export function ChatDisplay({ onSetSpeakerRole }: { onSetSpeakerRole?: (name: string, side: string) => void }) {
  const messages = useMeetingStore((s) => s.messages);
  const turns = useMeetingStore((s) => s.turns);
  const partialMessage = useMeetingStore((s) => s.partialMessage);
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);
  const bottomRef = useRef<HTMLDivElement>(null);

  const cycleSpeakerRole = useCallback((name: string) => {
    if (!onSetSpeakerRole) return;
    const current = speakerRoles[name] || '';
    const idx = SIDE_CYCLE.indexOf(current as SpeakerSide | '');
    const next = SIDE_CYCLE[(idx + 1) % SIDE_CYCLE.length];
    onSetSpeakerRole(name, next);
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
              const side = speakerRoles[turn.speaker];
              const badge = side ? SIDE_BADGES[side] : undefined;
              const badgeColor = side ? SIDE_COLORS[side] : undefined;
              return (
                <div key={turn.turn_id} style={styles.message}>
                  <span
                    style={{ ...styles.speaker, color: getSpeakerTextColor(turn.speaker), cursor: onSetSpeakerRole ? 'pointer' : undefined }}
                    onClick={() => cycleSpeakerRole(turn.speaker)}
                    title="Нажмите для смены роли"
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
              return (
                <div
                  key={msg.id}
                  style={{
                    ...styles.message,
                    opacity: isLowConf ? 0.7 : 1,
                  }}
                >
                  <span style={{ ...styles.speaker, color: getSpeakerTextColor(msg.speaker) }}>
                    {msg.speaker}
                    {isLowConf && (
                      <span style={styles.lowConfBadge} title="Низкая уверенность транскрипции">?</span>
                    )}
                  </span>
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
