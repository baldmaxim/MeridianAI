import { useState, useEffect } from 'react';
import { theme } from '../../styles/theme';
import { useErrorShake } from '../../hooks/useErrorShake';

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
    <form ref={formRef} onSubmit={handleSubmit} className="auth-form t-input" style={styles.form}>
      <h2 style={styles.title}>Регистрация</h2>
      {error && <div style={styles.error}>{error}</div>}
      <input
        type="text"
        placeholder="Имя (необязательно)"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        style={styles.input}
      />
      <input
        type="text"
        placeholder="Отдел"
        value={department}
        onChange={(e) => setDepartment(e.target.value)}
        required
        style={styles.input}
      />
      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        style={styles.input}
      />
      <input
        type="password"
        placeholder="Пароль"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        minLength={6}
        style={styles.input}
      />
      <button type="submit" className="t-btn t-btn-amber" disabled={loading} style={styles.button}>
        {loading ? 'Регистрация...' : 'Зарегистрироваться'}
      </button>
      <p style={styles.switch}>
        Уже есть аккаунт?{' '}
        <span onClick={onSwitchToLogin} style={styles.link}>
          Войти
        </span>
      </p>
    </form>
  );
}

const styles: Record<string, React.CSSProperties> = {
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    width: '100%',
    maxWidth: 360,
    padding: 32,
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
  },
  title: {
    color: theme.text.primary,
    margin: 0,
    textAlign: 'center',
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 18,
  },
  input: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 14,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  button: {
    padding: '10px 14px',
    background: theme.accent.amber,
    border: 'none',
    borderRadius: 7,
    color: '#080A0F',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: theme.font.body,
  },
  error: {
    padding: 8,
    background: theme.accent.redDim,
    border: '1px solid rgba(255,75,110,0.2)',
    borderRadius: 6,
    color: theme.accent.red,
    fontSize: 13,
  },
  switch: {
    color: theme.text.secondary,
    textAlign: 'center',
    fontSize: 13,
    margin: 0,
  },
  link: {
    color: theme.accent.amber,
    cursor: 'pointer',
  },
};
