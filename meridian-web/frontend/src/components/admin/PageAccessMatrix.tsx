import { usePageAccess, useUpdatePageAccess } from '../../hooks/queries/admin';
import styles from './PageAccessMatrix.module.css';
import { cx } from '../../utils/cx';

const ROLE_LABELS: Record<string, string> = { admin: 'Админ', user: 'Пользователь' };

export function PageAccessMatrix() {
  const { data: config, isPending, isError } = usePageAccess();
  const updateMut = useUpdatePageAccess();
  const saving = updateMut.isPending;

  const header = (
    <div className={styles.header}>
      <span className={styles.dot} />
      <span className={styles.title}>Доступ к страницам</span>
    </div>
  );

  if (!config) {
    const msg = isError ? 'Не удалось загрузить настройки доступа' : isPending ? 'Загрузка…' : '';
    return <div className={styles.container}>{header}<div className={styles.muted}>{msg}</div></div>;
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
    <div className={styles.container}>
      {header}
      {updateMut.isError && <div className={styles.error}>Не удалось сохранить</div>}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={cx(styles.th, styles.thLeft)}>Страница</th>
              {roleNames.map((r) => <th key={r} className={styles.th}>{ROLE_LABELS[r] || r}</th>)}
            </tr>
          </thead>
          <tbody>
            {config.catalog.map((p) => (
              <tr key={p.key}>
                <td className={styles.tdLabel}>{p.label}</td>
                {roleNames.map((r) => {
                  const locked = isLocked(r, p.key);
                  return (
                    <td key={r} className={styles.tdCheck}>
                      <input
                        type="checkbox"
                        checked={allowedByRole[r].has(p.key)}
                        disabled={locked || saving}
                        onChange={() => toggle(r, p.key)}
                        title={locked ? 'Всегда доступно' : undefined}
                        className={cx(styles.checkbox, locked && styles.checkboxLocked)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.muted}>
        Залоченные галочки — всегда доступно (нельзя снять). Изменения вступают в силу после перезахода пользователя.
      </div>
    </div>
  );
}
