import { theme } from '../../styles/theme';

interface Props {
  /** true — админ смотрит интерфейс как обычный пользователь */
  viewAsUser: boolean;
  onToggle: () => void;
}

/** Слайдер «Админ ⟷ Пользователь» — визуальный предпросмотр интерфейса не-админа (только фронт). */
export function RoleSwitch({ viewAsUser, onToggle }: Props) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={viewAsUser ? 'Вернуться к виду администратора' : 'Посмотреть интерфейс как пользователь'}
      style={styles.wrap}
    >
      <span style={{ ...styles.label, color: viewAsUser ? theme.text.muted : theme.accent.amber }}>Админ</span>
      <span style={styles.track}>
        <span style={{ ...styles.knob, transform: viewAsUser ? 'translateX(18px)' : 'translateX(0)' }} />
      </span>
      <span style={{ ...styles.label, color: viewAsUser ? theme.accent.amber : theme.text.muted }}>Пользователь</span>
    </button>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'inline-flex', alignItems: 'center', gap: 8,
    background: 'transparent', border: 'none', cursor: 'pointer', padding: 4,
  },
  label: {
    fontFamily: theme.font.mono, fontSize: 10, fontWeight: 600,
    letterSpacing: '0.04em', transition: 'color 0.2s', whiteSpace: 'nowrap',
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
