import { useState, useEffect } from 'react';
import type { Customer } from '../../types';
import { createObject } from '../../api/objects';
import { listCustomers } from '../../api/customers';
import { apiErrorMessage } from '../../lib/apiError';
import { dirStyles as s } from './directoryStyles';
import { theme } from '../../styles/theme';
import { Modal } from '../common/Modal';
import { Combobox } from '../common';
import { useErrorShake } from '../../hooks/useErrorShake';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

/** Минимальная модалка создания объекта (для всех ролей).
 *  Заказчик — текстовое поле с подсказками из уже созданных (combobox): можно выбрать
 *  существующего или вписать нового — он создастся вместе с объектом.
 *  Анимации transitions.dev: вход/выход — Modal (06), ошибка — error-shake (12). */
export function ObjectCreateModal({ open, onClose, onCreated }: Props) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [name, setName] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [address, setAddress] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [shakeKey, setShakeKey] = useState(0);
  const formRef = useErrorShake<HTMLDivElement>(shakeKey);

  useEffect(() => {
    // список — только источник подсказок; пустой список не мешает создавать объект
    listCustomers().then(setCustomers).catch(() => { /* справочник может быть пуст */ });
  }, []);

  function fail(msg: string) {
    setError(msg);
    setShakeKey((k) => k + 1);
  }

  async function save() {
    setError('');
    if (!name.trim()) { fail('Укажите название объекта'); return; }
    if (!customerName.trim()) { fail('Укажите заказчика'); return; }
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
      fail(apiErrorMessage(e, 'Не удалось создать объект'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} maxWidth={460}>
      <div style={styles.head}>
        <span style={s.title}>Новый объект</span>
        <button className="t-btn" style={styles.close} onClick={onClose}>×</button>
      </div>

      <div ref={formRef} className="t-input" style={s.formCard}>
        <label style={s.label}>Название *</label>
        <input style={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="ЖК «Рассвет», корпус 2" autoFocus />
        <label style={s.label}>Заказчик *</label>
        <Combobox
          style={s.input}
          value={customerName}
          onChange={setCustomerName}
          options={customers.map((c) => c.name)}
          placeholder="ООО «Стройзаказ» — выберите или впишите нового"
        />
        <label style={s.label}>Адрес</label>
        <input style={s.input} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="необязательно" />
        <label style={s.label}>Описание</label>
        <input style={s.input} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="необязательно" />
        <div style={s.formRow}>
          <button className="t-btn t-btn-amber" style={s.btn} onClick={save} disabled={saving}>{saving ? 'Сохранение…' : 'Создать'}</button>
          <button className="t-btn" style={s.btnGhost} onClick={onClose}>Отмена</button>
        </div>
      </div>

      {error && <div style={s.error}>{error}</div>}
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  head: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  close: {
    width: 28, height: 28, borderRadius: 6, background: 'transparent',
    border: `1px solid ${theme.border.default}`, color: theme.text.secondary,
    cursor: 'pointer', fontSize: 16, lineHeight: 1,
  },
};
