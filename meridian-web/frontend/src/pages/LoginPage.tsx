import { useState, useEffect } from 'react';
import { LoginForm } from '../components/auth/LoginForm';
import { RegisterForm } from '../components/auth/RegisterForm';
import { theme } from '../styles/theme';

interface Props {
  onLogin: (email: string, password: string) => Promise<unknown>;
  onRegister: (email: string, password: string, displayName?: string, department?: string) => Promise<unknown>;
}

/* Inline SVG compass mark */
function LogoMark() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="20" stroke="#F5A623" strokeWidth="1" opacity="0.25"/>
      <circle cx="24" cy="24" r="12" stroke="#F5A623" strokeWidth="1.5" opacity="0.6"/>
      <circle cx="24" cy="24" r="4" fill="#F5A623"/>
      <line x1="24" y1="4" x2="24" y2="10" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="24" y1="38" x2="24" y2="44" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="4" y1="24" x2="10" y2="24" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="38" y1="24" x2="44" y2="24" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
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
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка входа');
    }
  };

  const handleRegister = async (email: string, password: string, displayName?: string, department?: string) => {
    setError('');
    try {
      await onRegister(email, password, displayName, department);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка регистрации');
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.brand}>
        <LogoMark />
        <div style={styles.brandText}>
          MERIDI<span style={{ color: theme.accent.amber }}>AN</span>
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
          style={styles.ssoBtn}
        >
          Войти через SSO (Keycloak)
        </button>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '100vh',
    background: theme.bg.primary,
    gap: 24,
    padding: 20,
  },
  brand: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
  },
  brandText: {
    fontFamily: theme.font.heading,
    fontWeight: 800,
    fontSize: 24,
    letterSpacing: '0.18em',
    color: theme.text.primary,
  },
  brandSub: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
    letterSpacing: '0.12em',
  },
  ssoBtn: {
    fontFamily: theme.font.body,
    fontSize: 13,
    padding: '10px 18px',
    background: 'transparent',
    color: theme.text.secondary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    cursor: 'pointer',
  },
};
