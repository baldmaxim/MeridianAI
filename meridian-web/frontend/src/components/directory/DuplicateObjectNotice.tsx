import { useState } from 'react';
import type { FC } from 'react';
import { requestObjectAccess, type IDuplicateObjectDetail } from '../../api/objectAccess';
import { apiErrorMessage } from '../../lib/apiError';
import { cx } from '../../utils/cx';
import styles from './DuplicateObjectNotice.module.css';

interface IDuplicateObjectNoticeProps {
  detail: IDuplicateObjectDetail;
  saving: boolean;
  onOpen: (objectId: number) => void;
  /** Повторить создание с force=true (только когда совпадение неточное). */
  onForceCreate: () => void;
}

/** Блок «Похожий проект уже есть» после ответа 409 duplicate_object. */
export const DuplicateObjectNotice: FC<IDuplicateObjectNoticeProps> = ({ detail, saving, onOpen, onForceCreate }) => {
  // статус запроса доступа по id кандидата: текст рядом с кнопкой
  const [results, setResults] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  const requestAccess = async (id: number) => {
    setBusyId(id);
    try {
      const res = await requestObjectAccess(id);
      setResults((r) => ({ ...r, [id]: res.status === 'already_granted' ? 'Доступ уже есть' : 'Заявка отправлена' }));
    } catch (e) {
      setResults((r) => ({ ...r, [id]: apiErrorMessage(e, 'Не удалось отправить заявку') }));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className={styles.notice}>
      <div className={styles.heading}>Похожий проект уже есть:</div>
      <ul className={styles.list}>
        {detail.candidates.map((c) => (
          <li key={c.id} className={styles.item}>
            <span className={styles.name}>{c.name} — {c.customer_name}</span>
            {c.has_access ? (
              <button type="button" className={cx('t-btn', styles.actionBtn)} onClick={() => onOpen(c.id)}>
                Открыть
              </button>
            ) : results[c.id] ? (
              <span className={styles.result}>{results[c.id]}</span>
            ) : (
              <button
                type="button"
                className={cx('t-btn', styles.actionBtn)}
                disabled={busyId === c.id}
                onClick={() => requestAccess(c.id)}
              >
                Запросить доступ
              </button>
            )}
          </li>
        ))}
      </ul>
      {detail.exact ? (
        <div className={styles.hint}>Такой проект уже есть у этого заказчика — запросите доступ.</div>
      ) : (
        <button type="button" className={cx('t-btn', styles.actionBtn, styles.forceBtn)} disabled={saving} onClick={onForceCreate}>
          {saving ? 'Создание…' : 'Это другой проект — создать'}
        </button>
      )}
    </div>
  );
};
