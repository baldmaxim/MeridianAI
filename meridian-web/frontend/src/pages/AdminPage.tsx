import { useState } from 'react';
import { ApiKeyManager } from '../components/admin/ApiKeyManager';
import { UserManager } from '../components/admin/UserManager';
import { PageAccessMatrix } from '../components/admin/PageAccessMatrix';
import { theme } from '../styles/theme';

type AdminTab = 'stats' | 'keys' | 'users' | 'access';

const TABS: { key: AdminTab; label: string }[] = [
  { key: 'stats', label: 'Статистика' },
  { key: 'keys', label: 'API-ключи' },
  { key: 'users', label: 'Пользователи' },
  { key: 'access', label: 'Доступ' },
];

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
  embedded?: boolean;
}

export function AdminPage({ onBack, embedded }: Props) {
  const [tab, setTab] = useState<AdminTab>('stats');

  return (
    <div className="admin-container" style={embedded ? styles.containerEmbedded : styles.container}>
      {/* Top bar with back + title */}
      {!embedded && (
        <div className="admin-topbar" style={styles.topBar}>
          {onBack && (
            <button onClick={onBack} className="t-btn" style={styles.backBtn}>
              &larr; К переговорам
            </button>
          )}
          <span style={styles.topTitle}>ПАНЕЛЬ АДМИНИСТРАТОРА</span>
        </div>
      )}

      {/* Header */}
      <div>
        <h2 className="admin-title" style={styles.title}>
          Админ<span style={{ color: theme.accent.amber }}>панель</span>
        </h2>
        <div style={styles.subtitle}>MERIDIAN v2.1 · Управление системой</div>
      </div>

      {/* Tabs */}
      <div className="admin-tabs" style={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="t-btn"
            style={{ ...styles.tab, ...(tab === t.key ? styles.tabActive : {}) }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'stats' && (
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
      )}

      {tab === 'keys' && (
        <div className="admin-section" style={styles.section}>
          <ApiKeyManager />
        </div>
      )}

      {tab === 'users' && (
        <div className="admin-section" style={styles.section}>
          <UserManager />
        </div>
      )}

      {tab === 'access' && (
        <div className="admin-section" style={styles.section}>
          <PageAccessMatrix />
        </div>
      )}
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
  containerEmbedded: {
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 24,
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
  tabs: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap' as const,
    borderBottom: `1px solid ${theme.border.default}`,
    paddingBottom: 0,
  },
  tab: {
    padding: '8px 16px',
    background: 'transparent',
    border: 'none',
    borderBottom: '2px solid transparent',
    color: theme.text.muted,
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.04em',
  },
  tabActive: {
    color: theme.accent.amber,
    borderBottom: `2px solid ${theme.accent.amber}`,
  },
  section: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
  },
};
