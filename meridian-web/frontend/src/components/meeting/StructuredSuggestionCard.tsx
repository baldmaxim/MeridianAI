import { useState } from 'react';
import type { FC } from 'react';
import type { SuggestionCard as SuggestionCardT } from '../../types';
import { Collapse } from '../common';
import { CARD_TYPE_META, colorVar } from './suggestionStyles';
import styles from './SuggestionPanel.module.css';

interface IStructuredSuggestionCardProps {
  card: SuggestionCardT;
}

export const StructuredSuggestionCard: FC<IStructuredSuggestionCardProps> = ({ card }) => {
  const [showEv, setShowEv] = useState(false);
  const meta = CARD_TYPE_META[card.type] || { label: card.type, color: 'var(--text-secondary)' };
  const conf = Math.round(card.confidence * 100);
  return (
    <div className={styles.card} style={colorVar(meta.color)}>
      <div className={styles.cardTop}>
        <span className={`${styles.badge} ${styles.badgeStrong}`}>{meta.label}</span>
        <div className={styles.cardTopRight}>
          {card.needs_user_check && <span className={styles.checkBadge}>Проверить</span>}
          <span className={styles.confidencePct}>{conf}%</span>
        </div>
      </div>
      {card.title && <div className={styles.cardTitle2}>{card.title}</div>}
      <div className={styles.cardText}>{card.text}</div>
      {card.why && <div className={styles.whyLine}>— {card.why}</div>}
      {card.needs_user_check && (card.check_reasons?.length ?? 0) > 0 && (
        <div className={styles.checkReasons}>Проверить: {card.check_reasons?.join('; ')}</div>
      )}
      {card.evidence.length > 0 && (
        <div>
          <button className={styles.evToggle} onClick={() => setShowEv((v) => !v)}>
            {showEv ? 'Скрыть источники' : `Источники (${card.evidence.length})`}
          </button>
          <Collapse open={showEv}>
            {card.evidence.map((e, i) => (
              <div key={i} className={styles.evRow}>
                <span className={styles.evSource}>{e.source}{e.ref ? ` · ${e.ref}` : ''}</span>
                <div>{e.text}</div>
              </div>
            ))}
          </Collapse>
        </div>
      )}
    </div>
  );
};
