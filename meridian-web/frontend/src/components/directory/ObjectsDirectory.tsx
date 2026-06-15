import { useState, useEffect } from 'react';
import type { Customer, Department, ProjectObject, ObjectAccessGrant, User, AccessLevel } from '../../types';
import { listObjects, createObject, updateObject, deleteObject, listObjectAccess, createObjectAccess, deleteObjectAccess } from '../../api/objects';
import { listCustomers } from '../../api/customers';
import { listDepartments } from '../../api/departments';
import { listUsers } from '../../api/users';
import { apiErrorMessage } from '../../lib/apiError';
import { dirStyles as s } from './directoryStyles';
import { theme } from '../../styles/theme';

const ACCESS_LABELS: Record<AccessLevel, string> = { view: 'просмотр', edit: 'правка', manage: 'управление' };

export function ObjectsDirectory() {
  const [items, setItems] = useState<ProjectObject[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState('');

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ProjectObject | null>(null);
  const [name, setName] = useState('');
  const [customerId, setCustomerId] = useState<number | ''>('');
  const [address, setAddress] = useState('');
  const [description, setDescription] = useState('');

  const [accessOpen, setAccessOpen] = useState<number | null>(null);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    try {
      const [objs, custs] = await Promise.all([listObjects(), listCustomers()]);
      setItems(objs); setCustomers(custs);
    } catch (e) {
      setError(apiErrorMessage(e, 'Ошибка загрузки объектов'));
    }
    // пользователи/отделы нужны для выдачи доступа; могут быть admin-only — не блокируем
    try { setDepartments(await listDepartments()); } catch { /* ignore */ }
    try { setUsers(await listUsers()); } catch { /* ignore */ }
  }

  function startCreate() {
    setEditing(null);
    setName(''); setCustomerId(customers[0]?.id ?? ''); setAddress(''); setDescription('');
    setShowForm(true);
  }

  function startEdit(o: ProjectObject) {
    setEditing(o);
    setName(o.name); setCustomerId(o.customer_id); setAddress(o.address || ''); setDescription(o.description || '');
    setShowForm(true);
  }

  async function save() {
    setError('');
    if (!name.trim()) { setError('Укажите название объекта'); return; }
    if (customerId === '') { setError('Выберите заказчика'); return; }
    const payload = { name: name.trim(), customer_id: Number(customerId), address: address.trim() || null, description: description.trim() || null };
    try {
      if (editing) await updateObject(editing.id, payload);
      else await createObject(payload);
      setShowForm(false);
      await loadAll();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сохранить объект'));
    }
  }

  async function remove(o: ProjectObject) {
    if (!confirm(`Удалить объект «${o.name}»?`)) return;
    setError('');
    try { await deleteObject(o.id); await loadAll(); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось удалить')); }
  }

  return (
    <div style={s.container}>
      <div style={s.toolbar}>
        <div style={s.header}><span style={s.dot} /><span style={s.title}>Объекты</span></div>
        <span style={{ flex: 1 }} />
        <button style={s.btn} onClick={startCreate} disabled={customers.length === 0}>+ Объект</button>
      </div>
      {customers.length === 0 && <div style={s.empty}>Сначала создайте заказчика — объект привязывается к нему.</div>}
      {error && <div style={s.error}>{error}</div>}

      {showForm && (
        <div style={s.formCard}>
          <label style={s.label}>Название *</label>
          <input style={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="ЖК «Рассвет», корпус 2" />
          <label style={s.label}>Заказчик *</label>
          <select style={s.select} value={customerId} onChange={(e) => setCustomerId(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">— выберите —</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <label style={s.label}>Адрес</label>
          <input style={s.input} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="необязательно" />
          <label style={s.label}>Описание</label>
          <input style={s.input} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="необязательно" />
          <div style={s.formRow}>
            <button style={s.btn} onClick={save}>{editing ? 'Сохранить' : 'Создать'}</button>
            <button style={s.btnGhost} onClick={() => setShowForm(false)}>Отмена</button>
          </div>
        </div>
      )}

      {items.length === 0 && customers.length > 0 && <div style={s.empty}>Объектов пока нет</div>}
      <div style={s.list}>
        {items.map((o) => (
          <div key={o.id} style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            <div style={s.item}>
              <div style={s.itemMain}>
                <div style={s.itemName}>{o.name}</div>
                <div style={s.itemMeta}>{o.customer_name || '—'}{o.address ? ` · ${o.address}` : ''}</div>
              </div>
              <button style={s.btnGhost} onClick={() => setAccessOpen(accessOpen === o.id ? null : o.id)}>Доступ</button>
              <button style={s.btnGhost} onClick={() => startEdit(o)}>Изменить</button>
              <button style={s.btnDanger} onClick={() => remove(o)}>Удалить</button>
            </div>
            {accessOpen === o.id && (
              <AccessPanel objectId={o.id} departments={departments} users={users} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AccessPanel({ objectId, departments, users }: { objectId: number; departments: Department[]; users: User[] }) {
  const [grants, setGrants] = useState<ObjectAccessGrant[]>([]);
  const [error, setError] = useState('');
  const [granteeType, setGranteeType] = useState<'user' | 'department'>('department');
  const [granteeId, setGranteeId] = useState<number | ''>('');
  const [level, setLevel] = useState<AccessLevel>('view');

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [objectId]);

  async function load() {
    try { setGrants(await listObjectAccess(objectId)); }
    catch (e) { setError(apiErrorMessage(e, 'Ошибка загрузки доступа')); }
  }

  async function add() {
    setError('');
    if (granteeId === '') { setError('Выберите получателя доступа'); return; }
    try {
      await createObjectAccess(objectId, {
        grantee_type: granteeType,
        grantee_user_id: granteeType === 'user' ? Number(granteeId) : null,
        grantee_department_id: granteeType === 'department' ? Number(granteeId) : null,
        access_level: level,
      });
      setGranteeId('');
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось выдать доступ'));
    }
  }

  async function remove(grantId: number) {
    setError('');
    try { await deleteObjectAccess(objectId, grantId); await load(); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось снять доступ')); }
  }

  const options = granteeType === 'user' ? users.map((u) => ({ id: u.id, label: u.display_name || u.email })) : departments.map((d) => ({ id: d.id, label: d.name }));

  return (
    <div style={{ ...s.formCard, borderTopLeftRadius: 0, borderTopRightRadius: 0, marginLeft: 14, marginRight: 14, background: theme.bg.elevated }}>
      <span style={s.label}>Доступ к объекту</span>
      {error && <div style={s.error}>{error}</div>}
      {grants.length === 0 && <div style={s.empty}>Доступ ещё не выдан</div>}
      {grants.map((g) => (
        <div key={g.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...s.itemMeta, flex: 1, color: theme.text.secondary }}>
            {g.grantee_type === 'user' ? '👤' : '🏢'} {g.grantee_name || `#${g.grantee_user_id ?? g.grantee_department_id}`} · {ACCESS_LABELS[g.access_level]}
          </span>
          <button style={s.btnDanger} onClick={() => remove(g.id)}>×</button>
        </div>
      ))}
      <div style={s.formRow}>
        <select style={{ ...s.select, flex: '0 0 130px' }} value={granteeType} onChange={(e) => { setGranteeType(e.target.value as 'user' | 'department'); setGranteeId(''); }}>
          <option value="department">Отдел</option>
          <option value="user">Сотрудник</option>
        </select>
        <select style={{ ...s.select, flex: 1, minWidth: 140 }} value={granteeId} onChange={(e) => setGranteeId(e.target.value === '' ? '' : Number(e.target.value))}>
          <option value="">— выберите —</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
        <select style={{ ...s.select, flex: '0 0 130px' }} value={level} onChange={(e) => setLevel(e.target.value as AccessLevel)}>
          <option value="view">просмотр</option>
          <option value="edit">правка</option>
          <option value="manage">управление</option>
        </select>
        <button style={s.btn} onClick={add}>Выдать</button>
      </div>
      {options.length === 0 && <div style={s.empty}>Нет {granteeType === 'user' ? 'сотрудников' : 'отделов'} для выбора (нужны права admin).</div>}
    </div>
  );
}
