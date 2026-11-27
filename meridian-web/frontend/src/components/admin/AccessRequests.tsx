import { useState } from 'react';
import type { FC } from 'react';
import { useObjectAccessRequests, useResolveAccessRequest } from '../../hooks/queries/admin';
import { apiErrorMessage } from '../../lib/apiError';
import { formatMoscowDateTime } from '../../lib/datetime';
import { cx } from '../../utils/cx';
import styles from './AccessRequests.module.css';

/** Очередь заявок на доступ к проектам: одобрить / отклонить. */
export const AccessRequests: FC = () => {
  const { data: requests = [], isPending, error } = useObjectAccessRequests();
  const resolveMut = useResolveAccessRequest();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState('');

  const resolve = async (id: number, approve: boolean) => {
    setBusyId(id);
    setActionError('');
    try {
      await resolveMut.mutateAsync({ id, approve });
    } catch (e) {
      setActionError(apiErrorMessage(e, 'Не удалось обработать заявку'));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Заявки на доступ</span>
        {requests.length > 0 && <span className={styles.count}>{requests.length}</span>}
      </div>

      {isPending && <div className={styles.hint}>Загрузка…</div>}
      {!isPending && error && <div className={styles.error}>{apiErrorMessage(error, 'Не удалось загрузить заявки')}</div>}
      {!isPending && !error && requests.length === 0 && <div className={styles.hint}>Заявок нет</div>}
      {actionError && <div className={styles.error}>{actionError}</div>}

      <div className={styles.list}>
        {requests.map((r) => (
          <div key={r.id} className={cx('admin-item', styles.item)}>
            <div className={styles.info}>
              <div className={styles.user}>{r.user_display_name || r.user_email}</div>
              {r.user_display_name && <div className={styles.meta}>{r.user_email}</div>}
              <div className={styles.object}>{r.object_name}</div>
              <div className={styles.meta}>{r.customer_name} · {formatMoscowDateTime(r.created_at)}</div>
            </div>
            <div className={styles.actions}>
              <button
                type="button"
                className={cx('t-btn t-btn-green', styles.approveBtn)}
                disabled={busyId === r.id}
                onClick={() => resolve(r.id, true)}
              >
                Одобрить
              </button>
              <button
                type="button"
                className={cx('t-btn t-btn-red', styles.rejectBtn)}
                disabled={busyId === r.id}
                onClick={() => resolve(r.id, false)}
              >
                Отклонить
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
