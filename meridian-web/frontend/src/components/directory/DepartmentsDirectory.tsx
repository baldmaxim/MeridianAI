import { useState, useEffect } from 'react';
import type { Department, DepartmentUser, User } from '../../types';
import { listDepartments, createDepartment, updateDepartment, deleteDepartment, listDepartmentUsers, addDepartmentUser, removeDepartmentUser } from '../../api/departments';
import { listUsers } from '../../api/users';
import { apiErrorMessage } from '../../lib/apiError';
import { dirStyles as s } from './directoryStyles';
import { theme } from '../../styles/theme';

export function DepartmentsDirectory() {
  const [items, setItems] = useState<Department[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Department | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [membersOpen, setMembersOpen] = useState<number | null>(null);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    try { setItems(await listDepartments()); }
    catch (e) { setError(apiErrorMessage(e, 'Ошибка загрузки отделов')); }
    try { setUsers(await listUsers()); } catch { /* admin-only — не блокируем */ }
  }

  function startCreate() { setEditing(null); setName(''); setDescription(''); setShowForm(true); }
  function startEdit(d: Department) { setEditing(d); setName(d.name); setDescription(d.description || ''); setShowForm(true); }

  async function save() {
    setError('');
    if (!name.trim()) { setError('Укажите название отдела'); return; }
    const payload = { name: name.trim(), description: description.trim() || null };
    try {
      if (editing) await updateDepartment(editing.id, payload);
      else await createDepartment(payload);
      setShowForm(false);
      await loadAll();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сохранить отдел'));
    }
  }

  async function remove(d: Department) {
    if (!confirm(`Удалить отдел «${d.name}»?`)) return;
    setError('');
    try { await deleteDepartment(d.id); await loadAll(); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось удалить')); }
  }

  return (
    <div style={s.container}>
      <div style={s.toolbar}>
        <div style={s.header}><span style={s.dot} /><span style={s.title}>Отделы</span></div>
        <span style={{ flex: 1 }} />
        <button style={s.btn} onClick={startCreate}>+ Отдел</button>
      </div>
      {error && <div style={s.error}>{error}</div>}

      {showForm && (
        <div style={s.formCard}>
          <label style={s.label}>Название *</label>
          <input style={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Отдел снабжения" />
          <label style={s.label}>Описание</label>
          <input style={s.input} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="необязательно" />
          <div style={s.formRow}>
            <button style={s.btn} onClick={save}>{editing ? 'Сохранить' : 'Создать'}</button>
            <button style={s.btnGhost} onClick={() => setShowForm(false)}>Отмена</button>
          </div>
        </div>
      )}

      {items.length === 0 && <div style={s.empty}>Отделов пока нет</div>}
      <div style={s.list}>
        {items.map((d) => (
          <div key={d.id} style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            <div style={s.item}>
              <div style={s.itemMain}>
                <div style={s.itemName}>{d.name}</div>
                <div style={s.itemMeta}>{d.description || '—'}</div>
              </div>
              <button style={s.btnGhost} onClick={() => setMembersOpen(membersOpen === d.id ? null : d.id)}>Сотрудники</button>
              <button style={s.btnGhost} onClick={() => startEdit(d)}>Изменить</button>
              <button style={s.btnDanger} onClick={() => remove(d)}>Удалить</button>
            </div>
            {membersOpen === d.id && <MembersPanel departmentId={d.id} users={users} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function MembersPanel({ departmentId, users }: { departmentId: number; users: User[] }) {
  const [members, setMembers] = useState<DepartmentUser[]>([]);
  const [error, setError] = useState('');
  const [pick, setPick] = useState<number | ''>('');

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [departmentId]);

  async function load() {
    try { setMembers(await listDepartmentUsers(departmentId)); }
    catch (e) { setError(apiErrorMessage(e, 'Ошибка загрузки сотрудников')); }
  }

  async function add() {
    setError('');
    if (pick === '') { setError('Выберите сотрудника'); return; }
    try { await addDepartmentUser(departmentId, Number(pick)); setPick(''); await load(); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось добавить')); }
  }

  async function remove(userId: number) {
    setError('');
    try { await removeDepartmentUser(departmentId, userId); await load(); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось убрать')); }
  }

  const memberIds = new Set(members.map((m) => m.user_id));
  const available = users.filter((u) => !memberIds.has(u.id));

  return (
    <div style={{ ...s.formCard, borderTopLeftRadius: 0, borderTopRightRadius: 0, marginLeft: 14, marginRight: 14, background: theme.bg.elevated }}>
      <span style={s.label}>Сотрудники отдела</span>
      {error && <div style={s.error}>{error}</div>}
      {members.length === 0 && <div style={s.empty}>В отделе пока никого нет</div>}
      {members.map((m) => (
        <div key={m.membership_id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...s.itemMeta, flex: 1, color: theme.text.secondary }}>{m.display_name || m.email}</span>
          <button style={s.btnDanger} onClick={() => remove(m.user_id)}>Убрать</button>
        </div>
      ))}
      <div style={s.formRow}>
        <select style={{ ...s.select, flex: 1, minWidth: 160 }} value={pick} onChange={(e) => setPick(e.target.value === '' ? '' : Number(e.target.value))}>
          <option value="">— выберите сотрудника —</option>
          {available.map((u) => <option key={u.id} value={u.id}>{u.display_name || u.email}</option>)}
        </select>
        <button style={s.btn} onClick={add}>Добавить</button>
      </div>
      {users.length === 0 && <div style={s.empty}>Список пользователей доступен только admin.</div>}
    </div>
  );
}
