import { useState } from 'react';
import { ApiKeyManager } from '../components/admin/ApiKeyManager';
import { LMStudioTest } from '../components/admin/LMStudioTest';
import { OcrAgentManager } from '../components/admin/OcrAgentManager';
import { UserManager } from '../components/admin/UserManager';
import { PageAccessMatrix } from '../components/admin/PageAccessMatrix';
import { theme } from '../styles/theme';
import styles from './AdminPage.module.css';
import { cx } from '../utils/cx';

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
    <div className={styles.statCard}>
      <div className={styles.statValue}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
      {change && (
        <div className={styles.statChange} style={{ color: changeColor || theme.accent.green }}>
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
    <div className={cx('admin-container', embedded ? styles.containerEmbedded : styles.container)}>
      {/* Top bar with back + title */}
      {!embedded && (
        <div className={cx('admin-topbar', styles.topBar)}>
          {onBack && (
            <button onClick={onBack} className={cx('t-btn', styles.backBtn)}>
              &larr; К переговорам
            </button>
          )}
          <span className={styles.topTitle}>ПАНЕЛЬ АДМИНИСТРАТОРА</span>
        </div>
      )}

      {/* Header */}
      <div>
        <h2 className={cx('admin-title', styles.title)}>
          Админ<span className={styles.titleAccent}>панель</span>
        </h2>
        <div className={styles.subtitle}>MERIDIAN v2.1 · Управление системой</div>
      </div>

      {/* Tabs */}
      <div className={cx('admin-tabs', styles.tabs)}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cx('t-btn', styles.tab, tab === t.key && styles.tabActive)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'stats' && (
        <div className={cx('admin-stats', styles.statsSection)}>
          <div className={styles.sectionHeader}>
            <span className={styles.dot} />
            <span className={styles.sectionTitle}>Статистика системы</span>
            <span className={styles.sectionMeta}>Обновлено 2 мин назад</span>
          </div>
          <div className={cx('stats-grid', styles.statsGrid)}>
            <StatCard value="—" label="Сессий за месяц" />
            <StatCard value="—" label="Подсказок выдано" />
            <StatCard value="—" label="Аптайм сервиса" />
            <StatCard value="—" label="Активных юзеров" />
          </div>
        </div>
      )}

      {tab === 'keys' && (
        <div className={cx('admin-section', styles.section)}>
          <ApiKeyManager />
          <LMStudioTest />
          <OcrAgentManager />
        </div>
      )}

      {tab === 'users' && (
        <div className={cx('admin-section', styles.section)}>
          <UserManager />
        </div>
      )}

      {tab === 'access' && (
        <div className={cx('admin-section', styles.section)}>
          <PageAccessMatrix />
        </div>
      )}
    </div>
  );
}
