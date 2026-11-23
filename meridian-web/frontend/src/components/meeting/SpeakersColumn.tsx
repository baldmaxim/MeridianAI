import { useState } from 'react';
import type { ComponentProps, FC } from 'react';
import { SpeakersPanel } from './SpeakersPanel';
import { useSpeakerList } from './useSpeakerList';
import styles from './SpeakersPanel.module.css';

const OPEN_KEY = 'meridian:meeting-speakers-panel';
/** От этой ширины окна панель спикеров по умолчанию раскрыта, ниже — узкая полоса. */
const WIDE_DEFAULT_PX = 1280;

type TPanelProps = Omit<ComponentProps<typeof SpeakersPanel>, 'variant' | 'onCollapse'>;

const readOpen = (): boolean => {
  try {
    const stored = window.localStorage.getItem(OPEN_KEY);
    if (stored === '1') return true;
    if (stored === '0') return false;
  } catch {
    /* localStorage недоступен — берём значение по ширине окна */
  }
  return window.innerWidth >= WIDE_DEFAULT_PX;
};

/** Колонка спикеров справа от транскрипта: панель или узкая полоса (состояние — в localStorage). */
export const SpeakersColumn: FC<TPanelProps> = (props) => {
  const [open, setOpen] = useState(readOpen);
  const { unassignedCount } = useSpeakerList();

  const toggle = (next: boolean) => {
    setOpen(next);
    try {
      window.localStorage.setItem(OPEN_KEY, next ? '1' : '0');
    } catch {
      /* выбор живёт до перезагрузки */
    }
  };

  if (open) {
    return (
      <div className={styles.column}>
        <SpeakersPanel {...props} variant="column" onCollapse={() => toggle(false)} />
      </div>
    );
  }

  return (
    <div className={styles.strip}>
      <button
        type="button"
        className={`t-btn ${styles.stripBtn}`}
        onClick={() => toggle(true)}
        aria-label={unassignedCount > 0 ? `Показать спикеров, неназначено: ${unassignedCount}` : 'Показать спикеров'}
        title="Показать панель спикеров"
      >
        <span className={styles.stripIcon} aria-hidden="true">◧</span>
        {unassignedCount > 0 && <span className={styles.stripBadge}>{unassignedCount}</span>}
        <span className={styles.stripLabel}>Спикеры</span>
      </button>
    </div>
  );
};
