import { useState, useEffect } from 'react';
import type { Customer } from '../../types';
import { createObject } from '../../api/objects';
import { listCustomers } from '../../api/customers';
import { apiErrorMessage } from '../../lib/apiError';
import { dirStyles as s } from './directoryStyles';
import { theme } from '../../styles/theme';

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

/** Минимальная модалка создания объекта (для всех ролей).
 *  Заказчик — текстовое поле с подсказками из уже созданных (combobox): можно выбрать
 *  существующего или вписать нового — он создастся вместе с объектом. */
export function ObjectCreateModal({ onClose, onCreated }: Props) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [name, setName] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [address, setAddress] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // список — только источник подсказок; пустой список не мешает создавать объект
    listCustomers().then(setCustomers).catch(() => { /* справочник может быть пуст */ });
  }, []);

  async function save() {
    setError('');
    if (!name.trim()) { setError('Укажите название объекта'); return; }
    if (!customerName.trim()) { setError('Укажите заказчика'); return; }
    setSaving(true);
    try {
      await createObject({
        name: name.trim(),
        customer_name: customerName.trim(),
        address: address.trim() || null,
        description: description.trim() || null,
      });
      onCreated();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось создать объект'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.head}>
          <span style={s.title}>Новый объект</span>
          <button style={styles.close} onClick={onClose}>×</button>
        </div>

        <div style={s.formCard}>
          <label style={s.label}>Название *</label>
          <input style={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="ЖК «Рассвет», корпус 2" autoFocus />
          <label style={s.label}>Заказчик *</label>
          <input
            style={s.input}
            list="object-customers-dl"
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            placeholder="ООО «Стройзаказ» — выберите или впишите нового"
          />
          <datalist id="object-customers-dl">
            {customers.map((c) => <option key={c.id} value={c.name} />)}
          </datalist>
          <label style={s.label}>Адрес</label>
          <input style={s.input} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="необязательно" />
          <label style={s.label}>Описание</label>
          <input style={s.input} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="необязательно" />
          <div style={s.formRow}>
            <button style={s.btn} onClick={save} disabled={saving}>{saving ? 'Сохранение…' : 'Создать'}</button>
            <button style={s.btnGhost} onClick={onClose}>Отмена</button>
          </div>
        </div>

        {error && <div style={s.error}>{error}</div>}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(8,10,15,0.7)',
    backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
  },
  modal: {
    width: '100%', maxWidth: 460, maxHeight: '90vh', overflow: 'auto',
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 14,
    padding: 20, display: 'flex', flexDirection: 'column', gap: 14,
  },
  head: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  close: {
    width: 28, height: 28, borderRadius: 6, background: 'transparent',
    border: `1px solid ${theme.border.default}`, color: theme.text.secondary,
    cursor: 'pointer', fontSize: 16, lineHeight: 1,
  },
};
