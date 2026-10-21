import { useState } from 'react';
import type { FC } from 'react';
import type { User } from '../../types';
import { type UserPatch } from '../../api/users';
import { useUpdateUser } from '../../hooks/queries/admin';
import { errorDetail } from '../../lib/errorDetail';
import { Select, TextInput } from '../common';
import { cx } from '../../utils/cx';
import styles from './EditUserModal.module.css';

interface IEditUserModalProps {
  user: User;
  isSelf: boolean;
  onClose: () => void;
  onSaved: () => void;
}

/** Модалка редактирования пользователя (имя, роль, новый пароль). */
export const EditUserModal: FC<IEditUserModalProps> = ({ user, isSelf, onClose, onSaved }) => {
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
    } catch (e) {
      setError(errorDetail(e) || 'Не удалось сохранить');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalTitle}>Редактировать пользователя</div>
        <div className={styles.modalEmail}>{user.email}</div>

        <label className={styles.label}>Имя</label>
        <TextInput
          inputClassName={styles.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onClear={() => setName('')}
          clearLabel="имя"
          placeholder="Отображаемое имя"
        />

        <label className={styles.label}>Роль</label>
        <Select
          style={selectStyle}
          value={role}
          disabled={isSelf}
          onChange={(v) => setRole(v as 'user' | 'admin')}
          options={[{ value: 'user', label: 'user' }, { value: 'admin', label: 'admin' }]}
          ariaLabel="Роль"
        />
        {isSelf && <div className={styles.hint}>Нельзя менять собственную роль</div>}

        <label className={styles.label}>Новый пароль</label>
        <TextInput
          inputClassName={styles.input}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onClear={() => setPassword('')}
          clearLabel="пароль"
          placeholder="Оставьте пустым, чтобы не менять"
          autoComplete="new-password"
        />

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.modalActions}>
          <button onClick={onClose} className={cx('t-btn', styles.cancelBtn)} disabled={saving}>
            Отмена
          </button>
          <button onClick={save} className={cx('t-btn t-btn-amber', styles.saveBtn)} disabled={saving}>
            {saving ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  );
};

/** Стиль триггера <Select>: компонент принимает только style (не className). */
const selectStyle: React.CSSProperties = {
  padding: '9px 12px',
  background: 'var(--bg-input)',
  border: '1px solid var(--border-default)',
  borderRadius: 7,
  color: 'var(--text)',
  fontSize: 13,
  fontFamily: "'Inter', sans-serif",
  outline: 'none',
};
