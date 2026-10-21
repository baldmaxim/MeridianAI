import { useEffect, useMemo, useState } from 'react';
import { Modal } from '../common/Modal';
import { SearchableSelect } from '../common/SearchableSelect';
import { TextInput } from '../common';
import { theme } from '../../styles/theme';
import { batchToMeeting } from '../../api/batch';
import type { BatchToMeetingResult } from '../../api/batch';
import { listCustomers } from '../../api/customers';
import { listObjects } from '../../api/objects';
import type { Customer, ProjectObject } from '../../types';
import { errorDetail } from '../../lib/errorDetail';
import styles from './BatchToMeetingModal.module.css';

interface Props {
  jobId: number;
  defaultTitle: string;
  open: boolean;
  onClose: () => void;
  onDone: (result: BatchToMeetingResult) => void;
}

/**
 * Сделать встречу из диктофонной записи.
 *
 * Пока запись остаётся «батчем», у неё есть только markdown-протокол. Решения, поручения,
 * риски и открытые вопросы наполняет финализация встречи — поэтому запись нужно перевести
 * во встречу. Заказчик указывается не для порядка: без него особенности контрагента при
 * извлечении знаний отбрасываются, привязать их некуда.
 */
export function BatchToMeetingModal({ jobId, defaultTitle, open, onClose, onDone }: Props) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [objects, setObjects] = useState<ProjectObject[]>([]);
  const [customerId, setCustomerId] = useState('');
  const [objectId, setObjectId] = useState('');
  const [title, setTitle] = useState(defaultTitle);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTitle(defaultTitle);
    setError(null);
    listCustomers().then(setCustomers).catch(() => setCustomers([]));
  }, [open, defaultTitle]);

  useEffect(() => {
    if (!open) return;
    const cid = customerId ? Number(customerId) : undefined;
    listObjects(cid).then(setObjects).catch(() => setObjects([]));
    setObjectId('');
  }, [open, customerId]);

  const customerOptions = useMemo(
    () => customers.map((c) => ({ value: String(c.id), label: c.name, search: c.name })),
    [customers],
  );
  const objectOptions = useMemo(
    () => objects.map((o) => ({ value: String(o.id), label: o.name, search: o.name })),
    [objects],
  );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await batchToMeeting(jobId, {
        customer_id: customerId ? Number(customerId) : null,
        object_id: objectId ? Number(objectId) : null,
        title: title.trim() || null,
      });
      onDone(result);
      onClose();
    } catch (e) {
      setError(errorDetail(e) || 'Не удалось сделать встречу из записи');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <div className={styles.body}>
        <h3 className={styles.title}>Сделать встречу из записи</h3>
        <p className={styles.hint}>
          Транскрипт переедет во встречу, после чего соберутся протокол, решения, поручения,
          риски и открытые вопросы — и появятся кандидаты в базу знаний.
        </p>

        <label className={styles.label}>Название встречи</label>
        <TextInput
          inputClassName={styles.input}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onClear={() => setTitle('')}
          clearLabel="название встречи"
          placeholder="Название встречи"
        />

        <label className={styles.label}>Заказчик</label>
        <SearchableSelect
          value={customerId}
          onChange={setCustomerId}
          options={customerOptions}
          placeholder="— не выбран —"
          searchPlaceholder="Поиск заказчика…"
          style={selectStyle}
        />
        <div className={styles.note}>
          Без заказчика особенности контрагента из этой встречи в базу знаний не попадут.
        </div>

        <label className={styles.label}>Объект</label>
        <SearchableSelect
          value={objectId}
          onChange={setObjectId}
          options={objectOptions}
          placeholder={customerId ? '— не выбран —' : 'Сначала выберите заказчика'}
          searchPlaceholder="Поиск объекта…"
          disabled={!customerId}
          style={selectStyle}
        />

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.actions}>
          <button type="button" className={styles.cancel} onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="button" className={styles.submit} onClick={submit} disabled={busy}>
            {busy ? 'Создаю…' : 'Сделать встречу'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Стиль триггера <SearchableSelect>: компонент принимает только style (не className). */
const selectStyle: React.CSSProperties = {
  background: theme.bg.input,
  color: theme.text.primary,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 6,
  padding: '8px 10px',
  fontSize: 13,
  fontFamily: theme.font.body,
  width: '100%',
};
