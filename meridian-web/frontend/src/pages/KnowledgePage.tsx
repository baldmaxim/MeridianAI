import { useState } from 'react';
import { LearningCandidates } from '../components/learning/LearningCandidates';
import { KnowledgeList } from '../components/learning/KnowledgeList';
import type { KnowledgeKind } from '../types';
import styles from './KnowledgePage.module.css';
import { cx } from '../utils/cx';

interface Props { onBack: () => void; }

type Tab = 'candidates' | KnowledgeKind;

const TABS: { key: Tab; label: string }[] = [
  { key: 'candidates', label: 'Кандидаты' },
  { key: 'terms', label: 'Термины' },
  { key: 'triggers', label: 'Триггеры' },
  { key: 'playbooks', label: 'Playbooks' },
  { key: 'traits', label: 'Особенности' },
  { key: 'forbidden', label: 'Стоп-фразы' },
];

export function KnowledgePage({ onBack }: Props) {
  const [tab, setTab] = useState<Tab>('candidates');

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <button onClick={onBack} className={styles.backBtn}>&larr; К переговорам</button>
        <span className={styles.topTitle}>БАЗА ЗНАНИЙ</span>
        <span className={styles.spacer} />
      </div>

      <div className={styles.tabs}>
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} className={cx(tab === t.key ? styles.tabActive : styles.tab)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className={styles.body}>
        {tab === 'candidates' ? (
          <>
            <p className={styles.hint}>
              AI предлагает элементы по итогам встреч. Они НЕ применяются автоматически — проверьте и одобрите нужное.
            </p>
            <LearningCandidates />
          </>
        ) : (
          <KnowledgeList kind={tab} />
        )}
      </div>
    </div>
  );
}
