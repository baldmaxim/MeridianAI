import { useState } from 'react';
import type { User } from '../../types';
import { useUsers, useUpdateUser, useDeleteUser } from '../../hooks/queries/admin';
import { useMe } from '../../hooks/queries/auth';
import styles from './UserManager.module.css';
import { cx } from '../../utils/cx';
import { EditUserModal } from './EditUserModal';

/** Цветовые варианты аватара (цвета — токены темы, см. UserManager.module.css). */
const AVATAR_TONES = [
  styles.avatarTone0, styles.avatarTone1, styles.avatarTone2,
  styles.avatarTone3, styles.avatarTone4, styles.avatarTone5,
];

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
    } catch {
      // ошибку покажет глобальный обработчик запросов; список обновится при следующей загрузке
    }
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
    } catch {
      // ошибку покажет глобальный обработчик запросов; список обновится при следующей загрузке
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Пользователи</span>
      </div>

      <div className={styles.list}>
        {groupByDepartment(users).map((group) => (
          <div key={group.dept} className={styles.group}>
            <div className={styles.groupHeader}>
              {group.dept}
              <span className={styles.groupCount}>{group.items.length}</span>
            </div>
            {group.items.map((u) => {
              const isSelf = u.id === currentUserId;
              return (
                <div key={u.id} className={cx('admin-item', styles.item)}>
                  <div className={cx(styles.avatar, AVATAR_TONES[u.id % AVATAR_TONES.length])}>
                    {getInitials(u)}
                  </div>
                  <div className={styles.info}>
                    <div className={styles.email}>
                      {u.email}
                      {!u.is_active && <span className={styles.inactiveTag}>выкл</span>}
                    </div>
                    <div className={styles.meta}>{u.display_name || '—'}</div>
                  </div>
                  <span className={cx(styles.roleBadge, u.role === 'admin' ? styles.roleAdmin : styles.roleUser)}>
                    {u.role.toUpperCase()}
                  </span>

                  <button onClick={() => setEditing(u)} className={cx('t-btn', styles.editBtn)}>
                    Изменить
                  </button>

                  {!isSelf && (
                    <button
                      onClick={() => toggleActive(u)}
                      className={cx('t-btn', styles.toggleBtn, u.is_active ? styles.toggleDeactivate : styles.toggleActivate)}
                    >
                      {u.is_active ? 'Деактивировать' : 'Активировать'}
                    </button>
                  )}

                  {!isSelf && (
                    <button onClick={() => handleDelete(u)} className={cx('t-btn t-btn-red', styles.deleteBtn)}>
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
