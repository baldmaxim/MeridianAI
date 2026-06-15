import { useState } from 'react';
import { theme } from '../styles/theme';
import { LearningCandidates } from '../components/learning/LearningCandidates';
import { KnowledgeList } from '../components/learning/KnowledgeList';
import type { KnowledgeKind } from '../types';

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
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>&larr; К переговорам</button>
        <span style={styles.topTitle}>БАЗА ЗНАНИЙ</span>
        <span style={{ flex: 1 }} />
      </div>

      <div style={styles.tabs}>
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} style={tab === t.key ? styles.tabActive : styles.tab}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={styles.body}>
        {tab === 'candidates' ? (
          <>
            <p style={styles.hint}>
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

const styles: Record<string, React.CSSProperties> = {
  container: { padding: '28px 32px', display: 'flex', flexDirection: 'column', gap: 18, overflow: 'auto', flex: 1 },
  topBar: { display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 16, borderBottom: `1px solid ${theme.border.default}` },
  backBtn: { display: 'flex', alignItems: 'center', gap: 6, padding: '6px 16px', background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em', flexShrink: 0 },
  topTitle: { fontFamily: theme.font.mono, fontSize: 11, fontWeight: 500, letterSpacing: '0.16em', color: theme.text.secondary },
  tabs: { display: 'flex', gap: 8, flexWrap: 'wrap' as const },
  tab: { padding: '8px 16px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.secondary, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em' },
  tabActive: { padding: '8px 16px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`, borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono, fontWeight: 600, letterSpacing: '0.04em' },
  body: { maxWidth: 760, width: '100%' },
  hint: { fontSize: 12, color: theme.text.muted, lineHeight: 1.5, margin: '0 0 14px' },
};
