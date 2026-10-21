import type { FC } from 'react';
import styles from './HistoryViewTabs.module.css';

export type THistoryView = 'finished' | 'drafts' | 'all';

const VIEWS: ReadonlyArray<{ key: THistoryView; label: string }> = [
  { key: 'finished', label: 'Завершённые' },
  { key: 'drafts', label: 'Черновики' },
  { key: 'all', label: 'Все' },
];

interface IHistoryViewTabsProps {
  view: THistoryView;
  onChange: (view: THistoryView) => void;
}

/** Вид списка: завершённые / черновики / все. */
export const HistoryViewTabs: FC<IHistoryViewTabsProps> = ({ view, onChange }) => (
  <div className={styles.viewTabs}>
    {VIEWS.map(({ key, label }) => (
      <button
        key={key}
        onClick={() => onChange(key)}
        className={`t-btn ${styles.viewTab}${view === key ? ` ${styles.viewTabActive}` : ''}`}
      >
        {label}
      </button>
    ))}
  </div>
);
