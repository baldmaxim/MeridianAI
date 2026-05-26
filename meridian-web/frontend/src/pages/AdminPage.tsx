import { ApiKeyManager } from '../components/admin/ApiKeyManager';
import { UserManager } from '../components/admin/UserManager';
import { theme } from '../styles/theme';

function StatCard({ value, label, change, changeColor }: {
  value: string; label: string; change?: string; changeColor?: string;
}) {
  return (
    <div style={styles.statCard}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
      {change && (
        <div style={{ ...styles.statChange, color: changeColor || theme.accent.green }}>
          {change}
        </div>
      )}
    </div>
  );
}

interface Props {
  onBack?: () => void;
}

export function AdminPage({ onBack }: Props) {
  return (
    <div className="admin-container" style={styles.container}>
      {/* Top bar with back + title */}
      <div className="admin-topbar" style={styles.topBar}>
        {onBack && (
          <button onClick={onBack} style={styles.backBtn}>
            &larr; К переговорам
          </button>
        )}
        <span style={styles.topTitle}>ПАНЕЛЬ АДМИНИСТРАТОРА</span>
      </div>

      {/* Header */}
      <div>
        <h2 className="admin-title" style={styles.title}>
          Админ<span style={{ color: theme.accent.amber }}>панель</span>
        </h2>
        <div style={styles.subtitle}>MERIDIAN v2.1 · Управление системой</div>
      </div>

      {/* Stats */}
      <div className="admin-stats" style={styles.statsSection}>
        <div style={styles.sectionHeader}>
          <span style={styles.dot} />
          <span style={styles.sectionTitle}>Статистика системы</span>
          <span style={styles.sectionMeta}>Обновлено 2 мин назад</span>
        </div>
        <div className="stats-grid" style={styles.statsGrid}>
          <StatCard value="—" label="Сессий за месяц" />
          <StatCard value="—" label="Подсказок выдано" />
          <StatCard value="—" label="Аптайм сервиса" />
          <StatCard value="—" label="Активных юзеров" />
        </div>
      </div>

      {/* Two-column: API Keys + Users */}
      <div className="admin-columns" style={styles.columns}>
        <div className="admin-section" style={styles.section}>
          <ApiKeyManager />
        </div>
        <div className="admin-section" style={styles.section}>
          <UserManager />
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
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
  container: {
    padding: '28px 32px',
    display: 'flex',
    flexDirection: 'column',
    gap: 24,
    overflow: 'auto',
    flex: 1,
  },
  title: {
    margin: 0,
    fontSize: 28,
    fontFamily: theme.font.heading,
    fontWeight: 800,
    color: theme.text.primary,
  },
  subtitle: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
    letterSpacing: '0.06em',
    marginTop: 4,
  },
  statsSection: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  sectionTitle: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
    flex: 1,
  },
  sectionMeta: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 12,
  },
  statCard: {
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    padding: '16px 14px',
  },
  statValue: {
    fontFamily: theme.font.heading,
    fontWeight: 800,
    fontSize: 28,
    color: theme.text.primary,
  },
  statLabel: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
    marginTop: 2,
  },
  statChange: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    marginTop: 4,
  },
  columns: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 20,
  },
  section: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
  },
};
