import { useEffect, useRef } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme, getSpeakerTextColor } from '../../styles/theme';

export function ChatDisplay() {
  const messages = useMeetingStore((s) => s.messages);
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Lookup for low-confidence segments
  const lowConfidenceIds = new Set(
    committedSegments
      .filter((s) => s.confidence !== null && s.confidence < -1.0)
      .map((s) => s.segment_id)
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="chat-display" style={styles.container}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Транскрипция</span>
      </div>
      <div style={styles.messages}>
        {messages.length === 0 && (
          <div style={styles.placeholder}>
            Транскрипция появится здесь...
          </div>
        )}
        {messages.map((msg) => {
          const isLowConf = lowConfidenceIds.has(msg.id);
          return (
            <div
              key={msg.id}
              style={{
                ...styles.message,
                opacity: msg.is_partial ? 0.6 : isLowConf ? 0.7 : 1,
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
