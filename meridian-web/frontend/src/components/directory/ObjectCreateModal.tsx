import { useState, useEffect } from 'react';
import type { Customer } from '../../types';
import { createObject } from '../../api/objects';
import { listCustomers } from '../../api/customers';
import { apiErrorMessage } from '../../lib/apiError';
import { Modal } from '../common/Modal';
import { Combobox, TextInput } from '../common';
import { theme } from '../../styles/theme';
import { useErrorShake } from '../../hooks/useErrorShake';
import styles from './ObjectCreateModal.module.css';
import { cx } from '../../utils/cx';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

/** Стиль поля <Combobox>: компонент принимает только style (не className). */
const comboInputStyle: React.CSSProperties = {
  padding: '9px 12px',
  background: theme.bg.input,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 7,
  color: theme.text.primary,
  fontSize: 13,
  fontFamily: theme.font.body,
  outline: 'none',
};

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
  const [payhubProjectId, setPayhubProjectId] = useState('');
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
    const payhubRaw = payhubProjectId.trim();
    if (payhubRaw && !/^\d+$/.test(payhubRaw)) { fail('PayHub project_id — только число'); return; }
    setSaving(true);
    try {
      await createObject({
        name: name.trim(),
        customer_name: customerName.trim(),
        address: address.trim() || null,
        description: description.trim() || null,
        payhub_project_id: payhubRaw ? Number(payhubRaw) : null,
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
      <div className={styles.head}>
        <span className={styles.title}>Новый объект</span>
        <button className={cx('t-btn', styles.close)} onClick={onClose}>×</button>
      </div>

      <div ref={formRef} className={cx('t-input', styles.formCard)}>
        <label className={styles.label}>Название *</label>
        <TextInput inputClassName={styles.input} value={name} onChange={(e) => setName(e.target.value)} onClear={() => setName('')} clearLabel="название" placeholder="ЖК «Рассвет», корпус 2" autoFocus />
        <label className={styles.label}>Заказчик *</label>
        <Combobox
          style={comboInputStyle}
          value={customerName}
          onChange={setCustomerName}
          options={customers.map((c) => c.name)}
          placeholder="ООО «Стройзаказ» — выберите или впишите нового"
        />
        <label className={styles.label}>Адрес</label>
        <TextInput inputClassName={styles.input} value={address} onChange={(e) => setAddress(e.target.value)} onClear={() => setAddress('')} clearLabel="адрес" placeholder="необязательно" />
        <label className={styles.label}>Описание</label>
        <TextInput inputClassName={styles.input} value={description} onChange={(e) => setDescription(e.target.value)} onClear={() => setDescription('')} clearLabel="описание" placeholder="необязательно" />
        <label className={styles.label}>PayHub project_id</label>
        <TextInput inputClassName={styles.input} value={payhubProjectId} onChange={(e) => setPayhubProjectId(e.target.value)} onClear={() => setPayhubProjectId('')} clearLabel="PayHub project_id" placeholder="ID проекта в PayHub — для поиска писем (необязательно)" inputMode="numeric" />
        <div className={styles.formRow}>
          <button className={cx('t-btn t-btn-amber', styles.btn)} onClick={save} disabled={saving}>{saving ? 'Сохранение…' : 'Создать'}</button>
          <button className={cx('t-btn', styles.btnGhost)} onClick={onClose}>Отмена</button>
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}
    </Modal>
  );
}
