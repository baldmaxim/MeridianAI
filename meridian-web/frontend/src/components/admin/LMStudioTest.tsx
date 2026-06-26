import { useState } from 'react';
import { useTestLmStudio } from '../../hooks/queries/admin';
import type { LMStudioTestResult } from '../../types';
import { theme } from '../../styles/theme';

export function LMStudioTest() {
  const test = useTestLmStudio();
  const [result, setResult] = useState<LMStudioTestResult | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handleTest = async () => {
    setResult(null);
    setErrMsg(null);
    try {
      setResult(await test.mutateAsync());
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErrMsg(detail || 'Не удалось проверить связь');
    }
  };

  const expected = result?.expected_present ?? {};

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>LM Studio · локальная машина</span>
      </div>
      <p style={styles.desc}>
        Токен добавляется выше как сервис <code style={styles.code}>lm_studio</code> (хранится
        зашифрованно). Проверка связи запрашивает список моделей сервера.
      </p>

      <button onClick={handleTest} disabled={test.isPending} className="t-btn t-btn-amber" style={styles.btn}>
        {test.isPending ? 'Проверка…' : 'Проверить связь'}
      </button>

      {errMsg && <div style={styles.errBox}>{errMsg}</div>}

      {result && !result.ok && (
        <div style={styles.errBox}>
          Ошибка подключения к {result.base_url}: {result.error}
        </div>
      )}

      {result && result.ok && (
        <div style={styles.resultBox}>
          <div style={styles.row}>
            <span style={styles.label}>Base URL</span>
            <span style={styles.value}>{result.base_url}</span>
          </div>
          <div style={styles.badges}>
            {Object.entries(expected).map(([model, present]) => {
              const color = present ? theme.accent.green : theme.accent.red;
              return (
                <span
                  key={model}
                  style={{
                    ...styles.badge,
                    background: color + '18',
                    border: `1px solid ${color}33`,
                    color,
                  }}
                >
                  {present ? '✓' : '✕'} {model}
                </span>
              );
            })}
          </div>
          {result.models && result.models.length > 0 && (
            <div style={styles.row}>
              <span style={styles.label}>Модели на сервере</span>
              <span style={styles.value}>{result.models.join(', ')}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    marginTop: 16,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: '#2DD4BF', flexShrink: 0 },
  title: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  desc: { fontSize: 12, fontFamily: theme.font.body, color: theme.text.secondary, lineHeight: 1.5, margin: 0 },
  code: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.accent.amber,
    background: theme.bg.input,
    padding: '1px 5px',
    borderRadius: 4,
  },
  btn: {
    alignSelf: 'flex-start',
    padding: '8px 16px',
    background: theme.accent.amber,
    border: 'none',
    borderRadius: 7,
    color: '#080A0F',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 600,
    fontFamily: theme.font.body,
  },
  resultBox: { display: 'flex', flexDirection: 'column', gap: 10 },
  errBox: {
    fontSize: 12,
    fontFamily: theme.font.mono,
    color: theme.accent.red,
    background: 'rgba(255,75,110,0.1)',
    border: '1px solid rgba(255,75,110,0.2)',
    borderRadius: 7,
    padding: '8px 12px',
  },
  row: { display: 'flex', flexDirection: 'column', gap: 4 },
  label: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
  },
  value: { fontSize: 12, fontFamily: theme.font.mono, color: theme.text.primary, wordBreak: 'break-all' as const },
  badges: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  badge: {
    padding: '4px 10px',
    borderRadius: 5,
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.04em',
  },
};
