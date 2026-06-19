import { useState } from 'react';
import type { User } from '../../types';
import { type UserPatch } from '../../api/users';
import { useUsers, useUpdateUser, useDeleteUser } from '../../hooks/queries/admin';
import { useMe } from '../../hooks/queries/auth';
import { theme } from '../../styles/theme';
import { Select } from '../common';

const AVATAR_COLORS = ['#F5A623', '#5B9CF6', '#2EE59D', '#A78BFA', '#FF4B6E', '#36D8B7'];

function getAvatarColor(index: number) {
  return AVATAR_COLORS[index % AVATAR_COLORS.length];
}

/** Сгруппировать пользователей по отделу (порядок групп — как в исходном списке). */
function groupByDepartment(users: User[]): { dept: string; items: User[] }[] {
  const groups: { dept: string; items: User[] }[] = [];
  const index = new Map<string, number>();
  for (const u of users) {
    const dept = u.department?.trim() || 'Без отдела';
    let gi = index.get(dept);
    if (gi === undefined) { gi = groups.length; index.set(dept, gi); groups.push({ dept, items: [] }); }
    groups[gi].items.push(u);
  }
  return groups;
}

function getInitials(user: User): string {
  if (user.display_name) {
    const parts = user.display_name.split(' ');
    return parts.length > 1
      ? (parts[0][0] + parts[1][0]).toUpperCase()
      : parts[0].substring(0, 2).toUpperCase();
  }
  return user.email.substring(0, 2).toUpperCase();
}

export function UserManager() {
  const [editing, setEditing] = useState<User | null>(null);

  const { data: users = [] } = useUsers();
  const { data: me } = useMe();
  const currentUserId = me?.id ?? null;
  const updateUserMut = useUpdateUser();
  const deleteUserMut = useDeleteUser();

  const toggleActive = async (user: User) => {
    try {
      await updateUserMut.mutateAsync({ id: user.id, patch: { is_active: !user.is_active } });
    } catch {}
  };

  const handleDelete = async (user: User) => {
    const ok = window.confirm(
      `Удалить пользователя ${user.email} НАВСЕГДА?\n\n` +
        'Будут безвозвратно удалены все его данные: встречи, документы, ' +
        'настройки и база знаний. Действие необратимо.'
    );
    if (!ok) return;
    try {
      await deleteUserMut.mutateAsync(user.id);
    } catch {}
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Пользователи</span>
      </div>

      <div style={styles.list}>
        {groupByDepartment(users).map((group) => (
          <div key={group.dept} style={styles.group}>
            <div style={styles.groupHeader}>
              {group.dept}
              <span style={styles.groupCount}>{group.items.length}</span>
            </div>
            {group.items.map((u) => {
              const avatarColor = getAvatarColor(u.id);
              const isSelf = u.id === currentUserId;
              return (
                <div key={u.id} className="admin-item" style={styles.item}>
                  <div style={{
                    ...styles.avatar,
                    background: avatarColor + '18',
                    border: `1px solid ${avatarColor}33`,
                    color: avatarColor,
                  }}>
                    {getInitials(u)}
                  </div>
                  <div style={styles.info}>
                    <div style={styles.email}>
                      {u.email}
                      {!u.is_active && <span style={styles.inactiveTag}>выкл</span>}
                    </div>
                    <div style={styles.meta}>{u.display_name || '—'}</div>
                  </div>
                  <span style={{
                    ...styles.roleBadge,
                    ...(u.role === 'admin' ? styles.roleAdmin : styles.roleUser),
                  }}>
                    {u.role.toUpperCase()}
                  </span>

                  <button onClick={() => setEditing(u)} className="t-btn" style={styles.editBtn}>
                    Изменить
                  </button>

                  {!isSelf && (
                    <button
                      onClick={() => toggleActive(u)}
                      className="t-btn"
                      style={{
                        ...styles.toggleBtn,
                        color: u.is_active ? theme.accent.red : theme.accent.green,
                        borderColor: u.is_active ? 'rgba(255,75,110,0.3)' : 'rgba(46,229,157,0.3)',
                      }}
                    >
                      {u.is_active ? 'Деактивировать' : 'Активировать'}
                    </button>
                  )}

                  {!isSelf && (
                    <button onClick={() => handleDelete(u)} className="t-btn t-btn-red" style={styles.deleteBtn}>
                      Удалить
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {editing && (
        <EditUserModal
          user={editing}
          isSelf={editing.id === currentUserId}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function EditUserModal({ user, isSelf, onClose, onSaved }: {
  user: User;
  isSelf: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(user.display_name ?? '');
  const [role, setRole] = useState<'user' | 'admin'>(user.role);
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const updateUserMut = useUpdateUser();

  const save = async () => {
    setError('');
    const patch: UserPatch = {};
    const trimmedName = name.trim();
    if (trimmedName !== (user.display_name ?? '')) patch.display_name = trimmedName || null;
    if (role !== user.role) patch.role = role;
    if (password.trim()) patch.password = password;

    if (Object.keys(patch).length === 0) { onClose(); return; }

    setSaving(true);
    try {
      await updateUserMut.mutateAsync({ id: user.id, patch });
      onSaved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Не удалось сохранить');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalTitle}>Редактировать пользователя</div>
        <div style={styles.modalEmail}>{user.email}</div>

        <label style={styles.label}>Имя</label>
        <input
          style={styles.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Отображаемое имя"
        />

        <label style={styles.label}>Роль</label>
        <Select
          style={styles.input}
          value={role}
          disabled={isSelf}
          onChange={(v) => setRole(v as 'user' | 'admin')}
          options={[{ value: 'user', label: 'user' }, { value: 'admin', label: 'admin' }]}
          ariaLabel="Роль"
        />
        {isSelf && <div style={styles.hint}>Нельзя менять собственную роль</div>}

        <label style={styles.label}>Новый пароль</label>
        <input
          style={styles.input}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Оставьте пустым, чтобы не менять"
          autoComplete="new-password"
        />

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.modalActions}>
          <button onClick={onClose} className="t-btn" style={styles.cancelBtn} disabled={saving}>
            Отмена
          </button>
          <button onClick={save} className="t-btn t-btn-amber" style={styles.saveBtn} disabled={saving}>
            {saving ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', gap: 14 },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 14 },
  group: { display: 'flex', flexDirection: 'column', gap: 8 },
  groupHeader: {
    display: 'flex', alignItems: 'center', gap: 8,
    fontFamily: theme.font.mono, fontSize: 11, fontWeight: 600,
    letterSpacing: '0.08em', textTransform: 'uppercase' as const,
    color: theme.accent.amber, padding: '2px 2px',
  },
  groupCount: {
    fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted,
    border: `1px solid ${theme.border.default}`, borderRadius: 10, padding: '0 7px',
  },
  item: {
    display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
    background: theme.bg.tertiary, borderRadius: 8,
    border: `1px solid ${theme.border.default}`, flexWrap: 'wrap' as const,
  },
  avatar: {
    width: 36, height: 36, borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 12, fontFamily: theme.font.heading, fontWeight: 700, flexShrink: 0,
  },
  info: { flex: 1, minWidth: 120 },
  email: {
    color: theme.text.primary, fontSize: 13, fontWeight: 500,
    fontFamily: theme.font.body, display: 'flex', alignItems: 'center', gap: 8,
  },
  inactiveTag: {
    fontSize: 9, fontFamily: theme.font.mono, color: theme.accent.red,
    border: `1px solid rgba(255,75,110,0.3)`, borderRadius: 4, padding: '1px 5px',
  },
  meta: { color: theme.text.muted, fontSize: 10, fontFamily: theme.font.mono, marginTop: 2 },
  roleBadge: {
    padding: '3px 10px', borderRadius: 5, fontSize: 10, fontFamily: theme.font.mono,
    fontWeight: 600, letterSpacing: '0.06em', flexShrink: 0,
  },
  roleAdmin: {
    background: 'rgba(245,166,35,0.12)', border: `1px solid rgba(245,166,35,0.25)`,
    color: theme.accent.amber,
  },
  roleUser: {
    background: 'rgba(255,255,255,0.04)', border: `1px solid ${theme.border.default}`,
    color: theme.text.muted,
  },
  editBtn: {
    padding: '5px 12px', background: 'transparent',
    border: `1px solid ${theme.border.amber || 'rgba(245,166,35,0.3)'}`,
    borderRadius: 5, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.body,
    color: theme.accent.amber, flexShrink: 0,
  },
  toggleBtn: {
    padding: '5px 12px', background: 'transparent', border: '1px solid',
    borderRadius: 5, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.body, flexShrink: 0,
  },
  deleteBtn: {
    padding: '5px 12px', background: 'transparent',
    border: `1px solid rgba(255,75,110,0.3)`, borderRadius: 5, cursor: 'pointer',
    fontSize: 11, fontFamily: theme.font.body, color: theme.accent.red, flexShrink: 0,
  },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
    backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center',
    justifyContent: 'center', zIndex: 1000, padding: 16,
  },
  modal: {
    width: '100%', maxWidth: 420, background: theme.bg.card,
    border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 24,
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  modalTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 16, color: theme.text.primary,
  },
  modalEmail: {
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, marginBottom: 8,
  },
  label: {
    fontFamily: theme.font.mono, fontSize: 10, color: theme.text.secondary,
    letterSpacing: '0.06em', textTransform: 'uppercase' as const, marginTop: 8,
  },
  input: {
    padding: '9px 12px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 7,
    color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  hint: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11, marginTop: 8 },
  modalActions: { display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 },
  cancelBtn: {
    padding: '8px 16px', background: 'transparent',
    border: `1px solid ${theme.border.default}`, borderRadius: 6, cursor: 'pointer',
    fontSize: 12, fontFamily: theme.font.body, color: theme.text.secondary,
  },
  saveBtn: {
    padding: '8px 16px', background: theme.accent.amber, border: 'none', borderRadius: 6,
    cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono, fontWeight: 700,
    color: '#080A0F',
  },
};
