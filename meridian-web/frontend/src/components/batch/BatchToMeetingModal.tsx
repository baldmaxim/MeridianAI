import { useEffect, useMemo, useState } from 'react';
import { Modal } from '../common/Modal';
import { SearchableSelect } from '../common/SearchableSelect';
import { theme } from '../../styles/theme';
import { batchToMeeting } from '../../api/batch';
import type { BatchToMeetingResult } from '../../api/batch';
import { listCustomers } from '../../api/customers';
import { listObjects } from '../../api/objects';
import type { Customer, ProjectObject } from '../../types';

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
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Не удалось сделать встречу из записи');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <div style={styles.body}>
        <h3 style={styles.title}>Сделать встречу из записи</h3>
        <p style={styles.hint}>
          Транскрипт переедет во встречу, после чего соберутся протокол, решения, поручения,
          риски и открытые вопросы — и появятся кандидаты в базу знаний.
        </p>

        <label style={styles.label}>Название встречи</label>
        <input
          style={styles.input}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Название встречи"
        />

        <label style={styles.label}>Заказчик</label>
        <SearchableSelect
          value={customerId}
          onChange={setCustomerId}
          options={customerOptions}
          placeholder="— не выбран —"
          searchPlaceholder="Поиск заказчика…"
          style={styles.select}
        />
        <div style={styles.note}>
          Без заказчика особенности контрагента из этой встречи в базу знаний не попадут.
        </div>

        <label style={styles.label}>Объект</label>
        <SearchableSelect
          value={objectId}
          onChange={setObjectId}
          options={objectOptions}
          placeholder={customerId ? '— не выбран —' : 'Сначала выберите заказчика'}
          searchPlaceholder="Поиск объекта…"
          disabled={!customerId}
          style={styles.select}
        />

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.actions}>
          <button type="button" style={styles.cancel} onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="button" style={styles.submit} onClick={submit} disabled={busy}>
            {busy ? 'Создаю…' : 'Сделать встречу'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  body: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 320 },
  title: { margin: 0, fontSize: 15, fontWeight: 700, color: theme.text.primary, fontFamily: theme.font.heading },
  hint: { margin: 0, color: theme.text.secondary, fontSize: 12, lineHeight: 1.5 },
  label: { color: theme.text.secondary, fontSize: 11, marginTop: 8, fontFamily: theme.font.body },
  input: {
    background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6,
    padding: '8px 10px', fontSize: 13, fontFamily: theme.font.body,
  },
  select: {
    background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6,
    padding: '8px 10px', fontSize: 13, fontFamily: theme.font.body, width: '100%',
  },
  note: { color: theme.text.muted, fontSize: 10.5, lineHeight: 1.5 },
  error: {
    marginTop: 8, background: 'rgba(255,75,110,0.1)', color: theme.accent.red,
    borderRadius: 6, padding: '7px 10px', fontSize: 11.5,
  },
  actions: { display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 },
  cancel: {
    padding: '8px 14px', background: theme.bg.elevated, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
  },
  submit: {
    padding: '8px 14px', background: theme.accent.amber, color: '#080A0F', border: 'none',
    borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer',
  },
};
