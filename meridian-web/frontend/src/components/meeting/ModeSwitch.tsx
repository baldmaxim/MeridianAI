import { theme } from '../../styles/theme';
import { useMeetingStore } from '../../store/meetingStore';

/** Слайдер «Простой ⟷ Полный» режим экрана встречи. */
export function ModeSwitch() {
  const uiMode = useMeetingStore((s) => s.uiMode);
  const setUiMode = useMeetingStore((s) => s.setUiMode);
  const simple = uiMode === 'simple';

  return (
    <button
      type="button"
      onClick={() => setUiMode(simple ? 'full' : 'simple')}
      title={simple ? 'Переключить в полный режим' : 'Переключить в простой режим'}
      style={styles.wrap}
    >
      <span style={{ ...styles.label, color: simple ? theme.accent.amber : theme.text.muted }}>Простой</span>
      <span style={styles.track}>
        <span style={{ ...styles.knob, transform: simple ? 'translateX(0)' : 'translateX(18px)' }} />
      </span>
      <span style={{ ...styles.label, color: simple ? theme.text.muted : theme.accent.amber }}>Полный</span>
    </button>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'inline-flex', alignItems: 'center', gap: 8,
    background: 'transparent', border: 'none', cursor: 'pointer', padding: 4,
  },
  label: {
    fontFamily: theme.font.mono, fontSize: 11, fontWeight: 600,
    letterSpacing: '0.04em', transition: 'color 0.2s',
  },
  track: {
    position: 'relative', width: 40, height: 22, flexShrink: 0,
    background: theme.bg.tertiary, border: `1px solid ${theme.border.amber}`,
    borderRadius: 12, display: 'inline-block',
  },
  knob: {
    position: 'absolute', top: 2, left: 2, width: 16, height: 16,
    background: theme.accent.amber, borderRadius: '50%',
    transition: 'transform 0.2s ease',
  },
};
