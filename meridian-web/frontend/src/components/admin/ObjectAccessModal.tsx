import { useMemo, useState } from 'react';
import type { FC } from 'react';
import type { User } from '../../types';
import type { IObjectAccess } from '../../api/objectAccess';
import { useUserObjectAccess, useSetUserObjectAccess } from '../../hooks/queries/admin';
import { useObjects, useCustomers } from '../../hooks/queries/directory';
import {
  groupObjectsByCustomer, isObjectChecked, toggleCustomerAccess, toggleObjectAccess,
} from '../../lib/objectAccessGroups';
import { apiErrorMessage } from '../../lib/apiError';
import { Modal, TextInput } from '../common';
import { cx } from '../../utils/cx';
import styles from './ObjectAccessModal.module.css';

interface IObjectAccessModalProps {
  /** Пользователь, которому настраивается доступ; null — модалка закрыта. */
  user: User | null;
  open: boolean;
  onClose: () => void;
}

interface IFormProps {
  user: User;
  onClose: () => void;
}

const ObjectAccessForm: FC<IFormProps> = ({ user, onClose }) => {
  const accessQuery = useUserObjectAccess(user.id);
  const objectsQuery = useObjects();
  const customersQuery = useCustomers();
  const saveMut = useSetUserObjectAccess(user.id);
  const [draft, setDraft] = useState<IObjectAccess | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');

  const access = draft ?? accessQuery.data ?? null;
  const loadError = accessQuery.error || objectsQuery.error || customersQuery.error;
  const loading = accessQuery.isPending || objectsQuery.isPending || customersQuery.isPending;

  const groups = useMemo(
    () => groupObjectsByCustomer(objectsQuery.data ?? [], customersQuery.data ?? [], query),
    [objectsQuery.data, customersQuery.data, query],
  );

  const update = (fn: (a: IObjectAccess) => IObjectAccess) => {
    if (access) setDraft(fn(access));
  };

  const save = async () => {
    if (!access) return;
    setError('');
    try {
      await saveMut.mutateAsync(access);
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сохранить'));
    }
  };

  return (
    <>
      <div className={styles.title}>Доступ к проектам</div>
      <div className={styles.userLine}>{user.display_name || user.email}</div>

      {loading && <div className={styles.hint}>Загрузка…</div>}
      {!loading && loadError && (
        <div className={styles.error}>{apiErrorMessage(loadError, 'Не удалось загрузить данные')}</div>
      )}

      {access && !loading && !loadError && (
        <>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={access.all_objects}
              onChange={(e) => update((a) => ({ ...a, all_objects: e.target.checked }))}
            />
            <span className={styles.checkLabel}>Все проекты (включая будущие)</span>
          </label>

          {!access.all_objects && (
            <>
              <TextInput
                inputClassName={styles.search}
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onClear={() => setQuery('')}
                clearLabel="поиск"
                placeholder="Поиск по проекту или заказчику"
              />
              <div className={styles.list}>
                {groups.length === 0 && <div className={styles.hint}>Ничего не найдено</div>}
                {groups.map((g) => {
                  const customerChecked = access.customer_ids.includes(g.customerId);
                  return (
                    <div key={g.customerId} className={styles.group}>
                      <label className={cx(styles.checkRow, styles.customerRow)}>
                        <input
                          type="checkbox"
                          checked={customerChecked}
                          onChange={() => update((a) => toggleCustomerAccess(a, g.customerId))}
                        />
                        <span className={styles.customerLabel}>
                          {g.customerName}
                          <span className={styles.customerHint}>Все проекты заказчика (и будущие)</span>
                        </span>
                      </label>
                      {g.objects.map((o) => (
                        <label key={o.id} className={cx(styles.checkRow, styles.objectRow)}>
                          <input
                            type="checkbox"
                            checked={isObjectChecked(access, o)}
                            disabled={customerChecked}
                            onChange={() => update((a) => toggleObjectAccess(a, o.id))}
                          />
                          <span className={styles.checkLabel}>{o.name}</span>
                        </label>
                      ))}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        <button type="button" onClick={onClose} className={cx('t-btn', styles.cancelBtn)} disabled={saveMut.isPending}>
          Отмена
        </button>
        <button
          type="button"
          onClick={save}
          className={cx('t-btn t-btn-amber', styles.saveBtn)}
          disabled={!access || loading || !!loadError || saveMut.isPending}
        >
          {saveMut.isPending ? 'Сохранение…' : 'Сохранить'}
        </button>
      </div>
    </>
  );
};

/** Модалка ручной выдачи доступа к проектам: «все», по заказчику или по отдельным проектам. */
export const ObjectAccessModal: FC<IObjectAccessModalProps> = ({ user, open, onClose }) => (
  <Modal open={open} onClose={onClose} maxWidth={520}>
    {user && <ObjectAccessForm key={user.id} user={user} onClose={onClose} />}
  </Modal>
);
