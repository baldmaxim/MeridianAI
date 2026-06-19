import { usePageAccess, useUpdatePageAccess } from '../../hooks/queries/admin';
import { theme } from '../../styles/theme';

const ROLE_LABELS: Record<string, string> = { admin: 'Админ', user: 'Пользователь' };

export function PageAccessMatrix() {
  const { data: config, isPending, isError } = usePageAccess();
  const updateMut = useUpdatePageAccess();
  const saving = updateMut.isPending;

  const header = (
    <div style={styles.header}>
      <span style={styles.dot} />
      <span style={styles.title}>Доступ к страницам</span>
    </div>
  );

  if (!config) {
    const msg = isError ? 'Не удалось загрузить настройки доступа' : isPending ? 'Загрузка…' : '';
    return <div style={styles.container}>{header}<div style={styles.muted}>{msg}</div></div>;
  }

  const roleNames = config.roles.map((r) => r.role_name);
  const allowedByRole: Record<string, Set<string>> = {};
  config.roles.forEach((r) => { allowedByRole[r.role_name] = new Set(r.allowed_pages); });
  const isLocked = (role: string, key: string) => (config.locked[role] || []).includes(key);

  const toggle = (role: string, key: string) => {
    if (saving || isLocked(role, key)) return;
    const next = new Set(allowedByRole[role]);
    if (next.has(key)) next.delete(key); else next.add(key);
    // оптимистичное обновление + откат/инвалидация + показ ошибки — внутри useUpdatePageAccess
    updateMut.mutate({ role, allowedPages: Array.from(next) });
  };

  return (
    <div style={styles.container}>
      {header}
      {updateMut.isError && <div style={styles.error}>Не удалось сохранить</div>}
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={{ ...styles.th, textAlign: 'left' }}>Страница</th>
              {roleNames.map((r) => <th key={r} style={styles.th}>{ROLE_LABELS[r] || r}</th>)}
            </tr>
          </thead>
          <tbody>
            {config.catalog.map((p) => (
              <tr key={p.key}>
                <td style={styles.tdLabel}>{p.label}</td>
                {roleNames.map((r) => {
                  const locked = isLocked(r, p.key);
                  return (
                    <td key={r} style={styles.tdCheck}>
                      <input
                        type="checkbox"
                        checked={allowedByRole[r].has(p.key)}
                        disabled={locked || saving}
                        onChange={() => toggle(r, p.key)}
                        title={locked ? 'Всегда доступно' : undefined}
                        style={{ cursor: locked ? 'not-allowed' : 'pointer', accentColor: theme.accent.amber, width: 16, height: 16 }}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={styles.muted}>
        Залоченные галочки — всегда доступно (нельзя снять). Изменения вступают в силу после перезахода пользователя.
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', gap: 14 },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary,
  },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
  tableWrap: { overflowX: 'auto' as const },
  table: { borderCollapse: 'collapse' as const, width: '100%', minWidth: 360 },
  th: {
    padding: '8px 12px', fontFamily: theme.font.mono, fontSize: 10, fontWeight: 600,
    letterSpacing: '0.06em', color: theme.text.secondary, textAlign: 'center' as const,
    borderBottom: `1px solid ${theme.border.default}`, textTransform: 'uppercase' as const,
  },
  tdLabel: {
    padding: '10px 12px', fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary,
    borderBottom: `1px solid ${theme.border.default}`,
  },
  tdCheck: {
    padding: '10px 12px', textAlign: 'center' as const,
    borderBottom: `1px solid ${theme.border.default}`,
  },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 10 },
};
