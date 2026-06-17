import { useState } from 'react';
import { theme } from '../../styles/theme';

interface Props {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  right?: React.ReactNode;
}

export function CollapsibleSection({ title, defaultOpen, children, right }: Props) {
  const [open, setOpen] = useState(defaultOpen ?? false);

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          style={styles.toggle}
        >
          <span style={{ ...styles.chevron, transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
          <span style={styles.dot} />
          <span style={styles.title}>{title}</span>
        </button>
        {right && <div style={{ flexShrink: 0 }}>{right}</div>}
      </div>
      {open && <div style={styles.body}>{children}</div>}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  header: { display: 'flex', alignItems: 'center', gap: 10 },
  toggle: {
    display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0,
    background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
    textAlign: 'left' as const,
  },
  chevron: {
    fontSize: 9, color: theme.text.secondary, flexShrink: 0,
    transition: 'transform 0.18s ease',
  },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  body: { display: 'flex', flexDirection: 'column', gap: 16 },
};
