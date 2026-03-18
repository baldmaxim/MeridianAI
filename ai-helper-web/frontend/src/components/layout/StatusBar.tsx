import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';

export function StatusBar() {
  const status = useMeetingStore((s) => s.statusMessage);
  const isConnected = useMeetingStore((s) => s.isConnected);
  const lastError = useMeetingStore((s) => s.lastError);

  return (
    <div style={styles.bar}>
      <span
        className="pulse-dot"
        style={{
          ...styles.dot,
          background: isConnected ? theme.accent.green : theme.accent.red,
        }}
      />
      <span style={styles.text}>{lastError || status}</span>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 24px',
    background: theme.bg.secondary,
    borderTop: `1px solid ${theme.border.default}`,
    minHeight: 28,
    flexShrink: 0,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  text: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    letterSpacing: '0.06em',
  },
};
