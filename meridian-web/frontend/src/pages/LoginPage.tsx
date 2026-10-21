import { useState, useEffect } from 'react';
import { LoginForm } from '../components/auth/LoginForm';
import { RegisterForm } from '../components/auth/RegisterForm';
import { errorDetail } from '../lib/errorDetail';
import styles from './LoginPage.module.css';

interface Props {
  onLogin: (email: string, password: string) => Promise<unknown>;
  onRegister: (email: string, password: string, displayName?: string, department?: string) => Promise<unknown>;
}

/* Inline SVG compass mark */
function LogoMark() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="20" stroke="var(--accent)" strokeWidth="1" opacity="0.25"/>
      <circle cx="24" cy="24" r="12" stroke="var(--accent)" strokeWidth="1.5" opacity="0.6"/>
      <circle cx="24" cy="24" r="4" fill="var(--accent)"/>
      <line x1="24" y1="4" x2="24" y2="10" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="24" y1="38" x2="24" y2="44" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="4" y1="24" x2="10" y2="24" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="38" y1="24" x2="44" y2="24" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

export function LoginPage({ onLogin, onRegister }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [error, setError] = useState('');
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => {
    fetch('/api/auth/config')
      .then((r) => r.json())
      .then((c) => setSsoEnabled(!!c.oidc_enabled))
      .catch(() => {});
  }, []);

  const handleLogin = async (email: string, password: string) => {
    setError('');
    try {
      await onLogin(email, password);
    } catch (err) {
      setError(errorDetail(err) || 'Ошибка входа');
    }
  };

  const handleRegister = async (email: string, password: string, displayName?: string, department?: string) => {
    setError('');
    try {
      await onRegister(email, password, displayName, department);
    } catch (err) {
      setError(errorDetail(err) || 'Ошибка регистрации');
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.brand}>
        <LogoMark />
        <div className={styles.brandText}>
          MERIDI<span className={styles.brandAccent}>AN</span>
        </div>
      </div>
      {mode === 'login' ? (
        <LoginForm
          onLogin={handleLogin}
          onSwitchToRegister={() => { setMode('register'); setError(''); }}
          error={error}
        />
      ) : (
        <RegisterForm
          onRegister={handleRegister}
          onSwitchToLogin={() => { setMode('login'); setError(''); }}
          error={error}
        />
      )}
      {ssoEnabled && (
        <button
          type="button"
          onClick={() => { window.location.href = '/api/auth/oidc/login'; }}
          className={styles.ssoBtn}
        >
          Войти через SSO (Keycloak)
        </button>
      )}
    </div>
  );
}
