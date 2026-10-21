import { useState, useEffect } from 'react';
import { useErrorShake } from '../../hooks/useErrorShake';
import { TextInput } from '../common';
import styles from './RegisterForm.module.css';
import { cx } from '../../utils/cx';

interface Props {
  onRegister: (email: string, password: string, displayName?: string, department?: string) => Promise<void>;
  onSwitchToLogin: () => void;
  error?: string;
}

export function RegisterForm({ onRegister, onSwitchToLogin, error }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [department, setDepartment] = useState('');
  const [loading, setLoading] = useState(false);
  const [shakeKey, setShakeKey] = useState(0);
  const formRef = useErrorShake<HTMLFormElement>(shakeKey);

  // error-shake (transitions.dev 12): новая ошибка → перезапуск шейка.
  useEffect(() => {
    if (error) setShakeKey((k) => k + 1);
  }, [error]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await onRegister(email, password, displayName || undefined, department.trim());
    } finally {
      setLoading(false);
    }
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className={cx('auth-form t-input', styles.form)}>
      <h2 className={styles.title}>Регистрация</h2>
      {error && <div className={styles.error}>{error}</div>}
      <TextInput
        type="text"
        placeholder="Имя (необязательно)"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        onClear={() => setDisplayName('')}
        clearLabel="имя"
      />
      <TextInput
        type="text"
        placeholder="Отдел"
        value={department}
        onChange={(e) => setDepartment(e.target.value)}
        onClear={() => setDepartment('')}
        clearLabel="отдел"
        required
      />
      <TextInput
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        onClear={() => setEmail('')}
        clearLabel="email"
        required
      />
      <TextInput
        type="password"
        placeholder="Пароль"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        onClear={() => setPassword('')}
        clearLabel="пароль"
        required
        minLength={6}
      />
      <button type="submit" className={cx('t-btn t-btn-amber', styles.button)} disabled={loading}>
        {loading ? 'Регистрация...' : 'Зарегистрироваться'}
      </button>
      <p className={styles.switch}>
        Уже есть аккаунт?{' '}
        <span onClick={onSwitchToLogin} className={styles.link}>
          Войти
        </span>
      </p>
    </form>
  );
}
