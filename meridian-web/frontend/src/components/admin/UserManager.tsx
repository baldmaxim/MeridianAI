import { useState, useEffect } from 'react';
import api from '../../api/client';
import type { User } from '../../types';
import { theme } from '../../styles/theme';

const AVATAR_COLORS = ['#F5A623', '#5B9CF6', '#2EE59D', '#A78BFA', '#FF4B6E', '#36D8B7'];

function getAvatarColor(index: number) {
  return AVATAR_COLORS[index % AVATAR_COLORS.length];
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
  const [users, setUsers] = useState<User[]>([]);

  const loadUsers = async () => {
    try {
      const { data } = await api.get<User[]>('/admin/users');
      setUsers(data);
    } catch {}
  };

  useEffect(() => { loadUsers(); }, []);

  const toggleActive = async (userId: number, currentActive: boolean) => {
    await api.put(`/admin/users/${userId}`, null, {
      params: { is_active: !currentActive },
    });
    await loadUsers();
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Пользователи</span>
      </div>

      <div style={styles.list}>
        {users.map((u, i) => {
          const avatarColor = getAvatarColor(i);
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
                <div style={styles.email}>{u.email}</div>
                <div style={styles.meta}>
                  {u.display_name || '—'}
                </div>
              </div>
              <span style={{
                ...styles.roleBadge,
                ...(u.role === 'admin' ? styles.roleAdmin : styles.roleUser),
              }}>
                {u.role.toUpperCase()}
              </span>
              <button
                onClick={() => toggleActive(u.id, u.is_active)}
                style={{
                  ...styles.toggleBtn,
                  color: u.is_active ? theme.accent.red : theme.accent.green,
                  borderColor: u.is_active ? 'rgba(255,75,110,0.3)' : 'rgba(46,229,157,0.3)',
                }}
              >
                <span className="admin-toggle-full">{u.is_active ? 'Деактивировать' : 'Активировать'}</span>
                <span className="admin-toggle-short" style={{ display: 'none' }}>{u.is_active ? 'Выкл' : 'Вкл'}</span>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', gap: 14 },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  title: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  item: {
    display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
    background: theme.bg.tertiary, borderRadius: 8,
    border: `1px solid ${theme.border.default}`,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 12,
    fontFamily: theme.font.heading,
    fontWeight: 700,
    flexShrink: 0,
  },
  info: { flex: 1, minWidth: 0 },
  email: {
    color: theme.text.primary,
    fontSize: 13,
    fontWeight: 500,
    fontFamily: theme.font.body,
  },
  meta: {
    color: theme.text.muted,
    fontSize: 10,
    fontFamily: theme.font.mono,
    marginTop: 2,
  },
  roleBadge: {
    padding: '3px 10px',
    borderRadius: 5,
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.06em',
    flexShrink: 0,
  },
  roleAdmin: {
    background: 'rgba(245,166,35,0.12)',
    border: `1px solid rgba(245,166,35,0.25)`,
    color: theme.accent.amber,
  },
  roleUser: {
    background: 'rgba(255,255,255,0.04)',
    border: `1px solid ${theme.border.default}`,
    color: theme.text.muted,
  },
  toggleBtn: {
    padding: '5px 12px', background: 'transparent', border: '1px solid',
    borderRadius: 5, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.body,
    flexShrink: 0,
  },
};
