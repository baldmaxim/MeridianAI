import { useState, useEffect } from 'react';
import type { Customer } from '../../types';
import { listCustomers, createCustomer, updateCustomer, deleteCustomer } from '../../api/customers';
import { apiErrorMessage } from '../../lib/apiError';
import { dirStyles as s } from './directoryStyles';

export function CustomersDirectory() {
  const [items, setItems] = useState<Customer[]>([]);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<Customer | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [inn, setInn] = useState('');
  const [notes, setNotes] = useState('');

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setItems(await listCustomers());
    } catch (e) {
      setError(apiErrorMessage(e, 'Ошибка загрузки заказчиков'));
    }
  }

  function startCreate() {
    setEditing(null);
    setName(''); setInn(''); setNotes('');
    setShowForm(true);
  }

  function startEdit(c: Customer) {
    setEditing(c);
    setName(c.name); setInn(c.inn || ''); setNotes(c.notes || '');
    setShowForm(true);
  }

  async function save() {
    setError('');
    if (!name.trim()) { setError('Укажите название'); return; }
    const payload = { name: name.trim(), inn: inn.trim() || null, notes: notes.trim() || null };
    try {
      if (editing) await updateCustomer(editing.id, payload);
      else await createCustomer(payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сохранить'));
    }
  }

  async function remove(c: Customer) {
    if (!confirm(`Удалить заказчика «${c.name}»?`)) return;
    setError('');
    try {
      await deleteCustomer(c.id);
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось удалить'));
    }
  }

  return (
    <div style={s.container}>
      <div style={s.toolbar}>
        <div style={s.header}><span style={s.dot} /><span style={s.title}>Заказчики</span></div>
        <span style={{ flex: 1 }} />
        <button style={s.btn} onClick={startCreate}>+ Заказчик</button>
      </div>

      {error && <div style={s.error}>{error}</div>}

      {showForm && (
        <div style={s.formCard}>
          <label style={s.label}>Название *</label>
          <input style={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="ООО «Стройзаказ»" />
          <label style={s.label}>ИНН</label>
          <input style={s.input} value={inn} onChange={(e) => setInn(e.target.value)} placeholder="необязательно" />
          <label style={s.label}>Заметки</label>
          <input style={s.input} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="необязательно" />
          <div style={s.formRow}>
            <button style={s.btn} onClick={save}>{editing ? 'Сохранить' : 'Создать'}</button>
            <button style={s.btnGhost} onClick={() => setShowForm(false)}>Отмена</button>
          </div>
        </div>
      )}

      {items.length === 0 && <div style={s.empty}>Заказчиков пока нет</div>}
      <div style={s.list}>
        {items.map((c) => (
          <div key={c.id} style={s.item}>
            <div style={s.itemMain}>
              <div style={s.itemName}>{c.name}</div>
              <div style={s.itemMeta}>{c.inn ? `ИНН ${c.inn}` : '—'}{c.notes ? ` · ${c.notes}` : ''}</div>
            </div>
            <button style={s.btnGhost} onClick={() => startEdit(c)}>Изменить</button>
            <button style={s.btnDanger} onClick={() => remove(c)}>Удалить</button>
          </div>
        ))}
      </div>
    </div>
  );
}
