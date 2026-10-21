import type { FC } from 'react';
import styles from './HistoryBatchBar.module.css';

interface IHistoryBatchBarProps {
  total: number;
  selectedCount: number;
  confirming: boolean;
  deleting: boolean;
  onToggleAll: () => void;
  onAskConfirm: () => void;
  onCancelConfirm: () => void;
  onDelete: () => void;
}

/** Пакетные действия над списком встреч: выбрать все / удалить выбранные (с подтверждением). */
export const HistoryBatchBar: FC<IHistoryBatchBarProps> = ({
  total, selectedCount, confirming, deleting, onToggleAll, onAskConfirm, onCancelConfirm, onDelete,
}) => {
  const hasSelection = selectedCount > 0;
  return (
    <div className={styles.batchBar}>
      <button onClick={onToggleAll} className={`t-btn ${styles.selectAllBtn}`}>
        {selectedCount === total ? 'Снять все' : 'Выбрать все'}
      </button>
      {hasSelection && !confirming && (
        <button onClick={onAskConfirm} className={`t-btn t-btn-red ${styles.batchDeleteBtn}`}>
          Удалить ({selectedCount})
        </button>
      )}
      {hasSelection && confirming && (
        <>
          <span className={styles.confirmText}>Удалить {selectedCount} встреч?</span>
          <button onClick={onDelete} disabled={deleting} className={`t-btn t-btn-red ${styles.confirmYes}`}>
            {deleting ? '...' : 'Да'}
          </button>
          <button onClick={onCancelConfirm} className={`t-btn ${styles.confirmNo}`}>Отмена</button>
        </>
      )}
    </div>
  );
};
