import { theme } from '../styles/theme';
import { ObjectsDirectory } from '../components/directory/ObjectsDirectory';
import { DepartmentsDirectory } from '../components/directory/DepartmentsDirectory';

export type DirSection = 'objects' | 'departments';

const SECTIONS: { key: DirSection; label: string; desc: string }[] = [
  { key: 'objects', label: 'Объекты', desc: 'Объекты, заказчики и доступы' },
  { key: 'departments', label: 'Отделы', desc: 'Отделы и сотрудники' },
];

interface Props {
  /** Назад из хаба (к переговорам/проектам). */
  onBack: () => void;
  /** Если задан — рендерим одиночную страницу раздела, без хаба. */
  section?: DirSection;
  /** Открыть подстраницу из хаба. */
  onOpenSection?: (key: DirSection) => void;
  /** Назад из подстраницы — к хабу справочников. */
  onBackToHub?: () => void;
  /** Какие разделы доступны (для хаба); по умолчанию все. */
  accessible?: DirSection[];
}

export function DirectoryPage({ onBack, section, onOpenSection, onBackToHub, accessible }: Props) {
  // --- Режим одиночной страницы раздела ---
  if (section) {
    const meta = SECTIONS.find((s) => s.key === section);
    return (
      <div style={styles.container}>
        <div style={styles.topBar}>
          <button onClick={onBackToHub || onBack} style={styles.backBtn}>&larr; Справочники</button>
          <span style={styles.topTitle}>{(meta?.label || '').toUpperCase()}</span>
          <span style={{ flex: 1 }} />
        </div>
        <div style={styles.body}>
          {/* Заказчик создаётся прямо в форме объекта — отдельного справочника заказчиков нет. */}
          {section === 'objects' && <ObjectsDirectory />}
          {section === 'departments' && <DepartmentsDirectory />}
        </div>
      </div>
    );
  }

  // --- Режим хаба: карточки доступных разделов ---
  const visible = SECTIONS.filter((s) => !accessible || accessible.includes(s.key));
  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>&larr; К переговорам</button>
        <span style={styles.topTitle}>СПРАВОЧНИКИ</span>
        <span style={{ flex: 1 }} />
      </div>
      <div style={styles.cards}>
        {visible.map((s) => (
          <button key={s.key} style={styles.card} onClick={() => onOpenSection?.(s.key)}>
            <span style={styles.cardTitle}>{s.label}</span>
            <span style={styles.cardDesc}>{s.desc}</span>
          </button>
        ))}
        {visible.length === 0 && <div style={styles.empty}>Нет доступных разделов</div>}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '28px 32px',
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
    overflow: 'auto',
    flex: 1,
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    paddingBottom: 16,
    borderBottom: `1px solid ${theme.border.default}`,
  },
  backBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 16px',
    background: 'transparent',
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.04em',
    flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    fontWeight: 500,
    letterSpacing: '0.16em',
    color: theme.text.secondary,
  },
  // Контент раздела — на всю ширину (раньше был maxWidth: 760).
  body: {
    width: '100%',
  },
  sectionStack: {
    display: 'flex',
    flexDirection: 'column',
    gap: 28,
  },
  cards: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    gap: 14,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    alignItems: 'flex-start',
    textAlign: 'left' as const,
    padding: '18px 18px',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 10,
    cursor: 'pointer',
  },
  cardTitle: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 15,
    color: theme.text.primary,
  },
  cardDesc: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
  },
  empty: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12, padding: '8px 0' },
};
