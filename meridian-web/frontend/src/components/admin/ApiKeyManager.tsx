import { useState } from 'react';
import { useApiKeys, useCreateApiKey, useUpdateApiKey, useDeleteApiKey } from '../../hooks/queries/admin';
import type { ApiKeyInfo } from '../../types';
import { theme } from '../../styles/theme';
import { Select } from '../common';

const SERVICES = ['openrouter', 'deepgram', 'elevenlabs', 'gemini', 'speechmatics'];

const SERVICE_COLORS: Record<string, string> = {
  openrouter: '#2EE59D',
  deepgram: '#5B9CF6',
  elevenlabs: '#F5A623',
  gemini: '#A78BFA',
  speechmatics: '#FF6B35',
};

export function ApiKeyManager() {
  const [service, setService] = useState('openrouter');
  const [apiKey, setApiKey] = useState('');

  const { data: keys = [] } = useApiKeys();
  const createKey = useCreateApiKey();
  const updateKey = useUpdateApiKey();
  const deleteKey = useDeleteApiKey();

  const handleAdd = async () => {
    if (!apiKey.trim()) return;
    try {
      await createKey.mutateAsync({ service, apiKey });
      setApiKey('');
    } catch {}
  };

  const handleToggle = async (k: ApiKeyInfo) => {
    try {
      await updateKey.mutateAsync({ id: k.id, updates: { is_active: !k.is_active } });
    } catch {}
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteKey.mutateAsync(id);
    } catch {}
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>API Ключи</span>
      </div>

      <div className="admin-add-row" style={styles.addRow}>
        <Select
          value={service}
          onChange={setService}
          options={SERVICES.map((s) => ({ value: s, label: s }))}
          style={styles.select}
          ariaLabel="Сервис"
        />
        <input
          type="password"
          placeholder="API ключ"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          style={styles.input}
        />
        <button onClick={handleAdd} disabled={createKey.isPending} className="t-btn t-btn-amber" style={styles.addBtn}>
          Добавить
        </button>
      </div>

      <div style={styles.list}>
        {keys.map((k) => {
          const color = SERVICE_COLORS[k.service] || theme.text.secondary;
          return (
            <div key={k.id} className="admin-item" style={styles.item}>
              <span style={{
                ...styles.serviceBadge,
                background: color + '18',
                border: `1px solid ${color}33`,
                color,
              }}>
                {k.service.toUpperCase()}
              </span>
              <span style={styles.masked}>{k.key_masked}</span>
              <span style={statusDot(k.is_active)} />
              <button
                onClick={() => handleToggle(k)}
                className="t-btn"
                style={{
                  ...styles.toggleBtn,
                  background: k.is_active ? 'rgba(46,229,157,0.12)' : 'rgba(255,75,110,0.12)',
                  border: `1px solid ${k.is_active ? 'rgba(46,229,157,0.25)' : 'rgba(255,75,110,0.2)'}`,
                  color: k.is_active ? theme.accent.green : theme.accent.red,
                }}
              >
                {k.is_active ? 'Вкл' : 'Выкл'}
              </button>
              <button onClick={() => handleDelete(k.id)} className="t-btn t-btn-red" style={styles.delBtn}>Отозвать</button>
            </div>
          );
        })}
        {keys.length === 0 && <div style={styles.empty}>Нет ключей. Добавьте API ключи для работы сервисов.</div>}
      </div>
    </div>
  );
}

const statusDot = (active: boolean): React.CSSProperties => ({
  width: 6,
  height: 6,
  borderRadius: '50%',
  background: active ? theme.accent.green : theme.accent.red,
  flexShrink: 0,
});

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
  addRow: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  select: {
    padding: '8px 12px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
  },
  input: {
    flex: 1, minWidth: 160, padding: '8px 12px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary,
    fontSize: 12, fontFamily: theme.font.body, outline: 'none',
  },
  addBtn: {
    padding: '8px 16px', background: theme.accent.amber, border: 'none',
    borderRadius: 7, color: '#080A0F', cursor: 'pointer', fontSize: 12,
    fontWeight: 600, fontFamily: theme.font.body,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  item: {
    display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
    background: theme.bg.tertiary, borderRadius: 8,
    border: `1px solid ${theme.border.default}`,
  },
  serviceBadge: {
    padding: '3px 10px',
    borderRadius: 5,
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.06em',
    flexShrink: 0,
  },
  masked: { color: theme.text.muted, fontSize: 12, flex: 1, fontFamily: theme.font.mono },
  toggleBtn: {
    padding: '5px 12px', borderRadius: 5, cursor: 'pointer', fontSize: 11,
    fontWeight: 600, fontFamily: theme.font.mono,
  },
  delBtn: {
    padding: '5px 12px', background: theme.accent.redDim, border: `1px solid rgba(255,75,110,0.2)`,
    borderRadius: 5, color: theme.accent.red, cursor: 'pointer', fontSize: 11,
    fontFamily: theme.font.body,
  },
  empty: { color: theme.text.muted, fontSize: 12, fontFamily: theme.font.mono, padding: 8 },
};
