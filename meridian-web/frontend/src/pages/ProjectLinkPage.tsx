import { useEffect, useMemo, useState } from 'react';
import { listPayhubProjects, type PayhubProject } from '../api/letters';
import { listObjects, updateObject } from '../api/objects';
import type { ProjectObject } from '../types';
import { apiErrorMessage } from '../lib/apiError';
import { theme } from '../styles/theme';

interface Props {
  onBack: () => void;
}

/** Экран связки «проект PayHub → наш объект».
 *  Слева — проекты PayHub (реальные названия + кол-во писем), справа — наши объекты.
 *  Выбираем проект слева → привязываем к объекту справа (payhub_project_id). */
export function ProjectLinkPage({ onBack }: Props) {
  const [projects, setProjects] = useState<PayhubProject[]>([]);
  const [objects, setObjects] = useState<ProjectObject[]>([]);
  const [selected, setSelected] = useState<PayhubProject | null>(null);
  const [leftQ, setLeftQ] = useState('');
  const [rightQ, setRightQ] = useState('');
  // Раздельные флаги: объекты (локальные, быстрые) не ждут проекты PayHub
  // (внешняя БД, секунды) — иначе правая колонка висит из-за медленного запроса.
  const [objectsLoading, setObjectsLoading] = useState(true);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [notConfigured, setNotConfigured] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    // Наши объекты — сразу по готовности, не дожидаясь PayHub.
    listObjects()
      .then(setObjects)
      .catch((e) => setError(apiErrorMessage(e, 'Не удалось загрузить объекты')))
      .finally(() => setObjectsLoading(false));

    // Проекты PayHub — отдельно; их сбой даёт мягкую деградацию левой колонки,
    // но не блокирует объекты и не роняет общий error.
    listPayhubProjects()
      .then(setProjects)
      .catch(() => setNotConfigured(true))
      .finally(() => setProjectsLoading(false));
  }, []);

  const projectName = useMemo(() => {
    const m = new Map<number, string>();
    projects.forEach((p) => m.set(p.projectId, p.name));
    return m;
  }, [projects]);

  const linkedByProject = useMemo(() => {
    const m = new Map<number, string>(); // projectId → имя объекта (первый привязанный)
    objects.forEach((o) => { if (o.payhub_project_id != null && !m.has(o.payhub_project_id)) m.set(o.payhub_project_id, o.name); });
    return m;
  }, [objects]);

  const filteredProjects = useMemo(() => {
    const q = leftQ.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) => p.name.toLowerCase().includes(q) || String(p.projectId).includes(q));
  }, [projects, leftQ]);

  const filteredObjects = useMemo(() => {
    const q = rightQ.trim().toLowerCase();
    if (!q) return objects;
    return objects.filter((o) => o.name.toLowerCase().includes(q) || (o.customer_name ?? '').toLowerCase().includes(q));
  }, [objects, rightQ]);

  async function setLink(obj: ProjectObject, payhubProjectId: number | null) {
    setSavingId(obj.id);
    setError('');
    try {
      const updated = await updateObject(obj.id, { payhub_project_id: payhubProjectId });
      setObjects((prev) => prev.map((o) => (o.id === obj.id ? { ...o, payhub_project_id: updated.payhub_project_id } : o)));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сохранить связку'));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="plp" style={styles.container}>
      <style>{`
        @media (max-width: 820px) {
          .plp { overflow-y: auto !important; }
          .plp-cols { flex-direction: column !important; flex: none !important; }
          .plp-col { flex: none !important; }
          .plp-list { max-height: 50vh; }
        }
      `}</style>
      <div style={styles.head}>
        <button className="t-btn" style={styles.back} onClick={onBack}>← Назад</button>
        <span style={styles.title}>Связка проектов</span>
        <span style={styles.subtitle}>PayHub → наши объекты</span>
      </div>

      {error && <div style={styles.error}>{error}</div>}
      {selected && (
        <div style={styles.selectedBar}>
          Выбран проект PayHub: <b style={{ color: theme.accent.amber }}>{selected.name}</b>
          <button style={styles.clearSel} onClick={() => setSelected(null)}>сбросить</button>
        </div>
      )}

      <div className="plp-cols" style={styles.cols}>
        {/* Левая колонка — проекты PayHub */}
        <div className="plp-col" style={styles.col}>
          <div style={styles.colHead}>Проекты PayHub</div>
          <input style={styles.search} placeholder="Поиск проекта…" value={leftQ} onChange={(e) => setLeftQ(e.target.value)} />
          <div className="plp-list" style={styles.list}>
            {projectsLoading && <div style={styles.empty}>Загрузка…</div>}
            {!projectsLoading && notConfigured && (
              <div style={styles.empty}>Таблица проектов PayHub не настроена (PAYHUB_PROJECTS_TABLE).</div>
            )}
            {!projectsLoading && !notConfigured && filteredProjects.length === 0 && (
              <div style={styles.empty}>Проекты не найдены</div>
            )}
            {filteredProjects.map((p) => {
              const isSel = selected?.projectId === p.projectId;
              const linkedTo = linkedByProject.get(p.projectId);
              return (
                <button
                  key={p.projectId}
                  type="button"
                  onClick={() => setSelected(p)}
                  className="t-btn"
                  style={{ ...styles.row, ...(isSel ? styles.rowSel : null) }}
                >
                  <span style={styles.rowMain}>
                    <span style={styles.rowName}>{p.name}</span>
                    <span style={styles.rowMeta}>
                      id {p.projectId}{p.letterCount != null ? ` · ${p.letterCount} писем` : ''}
                      {linkedTo ? ` · → ${linkedTo}` : ''}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Правая колонка — наши объекты */}
        <div className="plp-col" style={styles.col}>
          <div style={styles.colHead}>Наши объекты</div>
          <input style={styles.search} placeholder="Поиск объекта или заказчика…" value={rightQ} onChange={(e) => setRightQ(e.target.value)} />
          <div className="plp-list" style={styles.list}>
            {objectsLoading && <div style={styles.empty}>Загрузка…</div>}
            {!objectsLoading && filteredObjects.length === 0 && <div style={styles.empty}>Объекты не найдены</div>}
            {filteredObjects.map((o) => {
              const linkedName = o.payhub_project_id != null
                ? (projectName.get(o.payhub_project_id) ?? `#${o.payhub_project_id}`)
                : null;
              return (
                <div key={o.id} style={styles.row}>
                  <span style={styles.rowMain}>
                    <span style={styles.rowName}>{o.name}</span>
                    <span style={styles.rowMeta}>
                      {o.customer_name ?? '—'}
                      {linkedName ? ` · привязан: ${linkedName}` : ''}
                    </span>
                  </span>
                  <span style={styles.rowActions}>
                    <button
                      className="t-btn"
                      style={{ ...styles.linkBtn, opacity: selected && savingId !== o.id ? 1 : 0.5 }}
                      disabled={!selected || savingId === o.id}
                      title={selected ? `Привязать «${selected.name}»` : 'Сначала выберите проект слева'}
                      onClick={() => selected && setLink(o, selected.projectId)}
                    >
                      {savingId === o.id ? '…' : 'Привязать'}
                    </button>
                    {o.payhub_project_id != null && (
                      <button
                        className="t-btn"
                        style={styles.unlinkBtn}
                        disabled={savingId === o.id}
                        onClick={() => setLink(o, null)}
                      >
                        Отвязать
                      </button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: '18px 20px', gap: 14, overflow: 'hidden' },
  head: { display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' },
  back: {
    padding: '5px 12px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 5, color: theme.accent.amber, cursor: 'pointer',
    fontSize: 11, fontFamily: theme.font.mono, letterSpacing: '0.06em',
  },
  title: { fontFamily: theme.font.heading, fontWeight: 800, fontSize: 18, color: theme.text.primary },
  subtitle: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.08em' },
  error: {
    padding: '10px 14px', background: theme.accent.redDim, border: `1px solid ${theme.accent.red}`,
    borderRadius: 8, color: theme.accent.red, fontSize: 13, fontFamily: theme.font.body,
  },
  selectedBar: {
    padding: '8px 14px', background: theme.accent.amberGlow, border: `1px solid ${theme.border.amber}`,
    borderRadius: 8, color: theme.text.secondary, fontSize: 13, fontFamily: theme.font.body,
    display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
  },
  clearSel: {
    marginLeft: 'auto', background: 'transparent', border: 'none', cursor: 'pointer',
    color: theme.accent.amber, fontSize: 12, fontFamily: theme.font.mono, textDecoration: 'underline',
  },
  cols: { flex: 1, minHeight: 0, display: 'flex', gap: 16, flexWrap: 'nowrap' },
  col: {
    flex: '1 1 320px', minWidth: 0, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 8,
    background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`, borderRadius: 10, padding: 12,
  },
  colHead: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber, letterSpacing: '0.08em', textTransform: 'uppercase' },
  search: {
    padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  list: { flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 },
  row: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', textAlign: 'left',
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 8,
    cursor: 'pointer', width: '100%',
  },
  rowSel: { border: `1px solid ${theme.accent.amber}`, background: theme.accent.amberGlow },
  rowMain: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' },
  rowName: { fontSize: 13, fontWeight: 600, color: theme.text.primary, fontFamily: theme.font.body, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  rowMeta: { fontSize: 11, color: theme.text.muted, fontFamily: theme.font.mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginTop: 2 },
  rowActions: { display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 },
  linkBtn: {
    padding: '6px 12px', background: theme.accent.amber, border: 'none', borderRadius: 6,
    color: '#080A0F', cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono, fontWeight: 700, letterSpacing: '0.04em',
  },
  unlinkBtn: {
    padding: '6px 10px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 6,
    color: theme.accent.red, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono, fontWeight: 600,
  },
  empty: { padding: 16, textAlign: 'center', color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13 },
};
