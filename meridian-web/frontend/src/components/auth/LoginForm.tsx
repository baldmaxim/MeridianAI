import { useState, useEffect } from 'react';
import { useErrorShake } from '../../hooks/useErrorShake';
import { TextInput } from '../common';
import styles from './LoginForm.module.css';
import { cx } from '../../utils/cx';

interface Props {
  onLogin: (email: string, password: string) => Promise<void>;
  onSwitchToRegister: () => void;
  error?: string;
}

export function LoginForm({ onLogin, onSwitchToRegister, error }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
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
      await onLogin(email, password);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className={cx('auth-form t-input', styles.form)}>
      <h2 className={styles.title}>Вход</h2>
      {error && <div className={styles.error}>{error}</div>}
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
      />
      <button type="submit" className={cx('t-btn t-btn-amber', styles.button)} disabled={loading}>
        {loading ? 'Вход...' : 'Войти'}
      </button>
      <p className={styles.switch}>
        Нет аккаунта?{' '}
        <span onClick={onSwitchToRegister} className={styles.link}>
          Зарегистрироваться
        </span>
      </p>
    </form>
  );
}
