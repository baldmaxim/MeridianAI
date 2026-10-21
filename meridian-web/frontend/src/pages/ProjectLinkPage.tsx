import { useEffect, useMemo, useState } from 'react';
import { listPayhubProjects, type PayhubProject } from '../api/letters';
import { listObjects, updateObject } from '../api/objects';
import type { ProjectObject } from '../types';
import { apiErrorMessage } from '../lib/apiError';
import styles from './ProjectLinkPage.module.css';
import { cx } from '../utils/cx';
import { TextInput } from '../components/common';

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
    <div className={styles.container}>
      <div className={styles.head}>
        <button className={cx('t-btn', styles.back)} onClick={onBack}>← Назад</button>
        <span className={styles.title}>Связка проектов</span>
        <span className={styles.subtitle}>PayHub → наши объекты</span>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {selected && (
        <div className={styles.selectedBar}>
          Выбран проект PayHub: <b className={styles.inline1}>{selected.name}</b>
          <button className={styles.clearSel} onClick={() => setSelected(null)}>сбросить</button>
        </div>
      )}

      <div className={styles.cols}>
        {/* Левая колонка — проекты PayHub */}
        <div className={styles.col}>
          <div className={styles.colHead}>Проекты PayHub</div>
          <TextInput inputClassName={styles.search} placeholder="Поиск проекта…" value={leftQ} onChange={(e) => setLeftQ(e.target.value)} onClear={() => setLeftQ('')} clearLabel="поиск проекта" />
          <div className={styles.list}>
            {projectsLoading && <div className={styles.empty}>Загрузка…</div>}
            {!projectsLoading && notConfigured && (
              <div className={styles.empty}>Таблица проектов PayHub не настроена (PAYHUB_PROJECTS_TABLE).</div>
            )}
            {!projectsLoading && !notConfigured && filteredProjects.length === 0 && (
              <div className={styles.empty}>Проекты не найдены</div>
            )}
            {filteredProjects.map((p) => {
              const isSel = selected?.projectId === p.projectId;
              const linkedTo = linkedByProject.get(p.projectId);
              return (
                <button
                  key={p.projectId}
                  type="button"
                  onClick={() => setSelected(p)}
                  className={cx('t-btn', styles.row, isSel && styles.rowSel)}
                >
                  <span className={styles.rowMain}>
                    <span className={styles.rowName}>{p.name}</span>
                    <span className={styles.rowMeta}>
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
        <div className={styles.col}>
          <div className={styles.colHead}>Наши объекты</div>
          <TextInput inputClassName={styles.search} placeholder="Поиск объекта или заказчика…" value={rightQ} onChange={(e) => setRightQ(e.target.value)} onClear={() => setRightQ('')} clearLabel="поиск объекта" />
          <div className={styles.list}>
            {objectsLoading && <div className={styles.empty}>Загрузка…</div>}
            {!objectsLoading && filteredObjects.length === 0 && <div className={styles.empty}>Объекты не найдены</div>}
            {filteredObjects.map((o) => {
              const linkedName = o.payhub_project_id != null
                ? (projectName.get(o.payhub_project_id) ?? `#${o.payhub_project_id}`)
                : null;
              return (
                <div key={o.id} className={styles.row}>
                  <span className={styles.rowMain}>
                    <span className={styles.rowName}>{o.name}</span>
                    <span className={styles.rowMeta}>
                      {o.customer_name ?? '—'}
                      {linkedName ? ` · привязан: ${linkedName}` : ''}
                    </span>
                  </span>
                  <span className={styles.rowActions}>
                    <button
                      className={cx('t-btn', styles.linkBtn)}
                      disabled={!selected || savingId === o.id}
                      title={selected ? `Привязать «${selected.name}»` : 'Сначала выберите проект слева'}
                      onClick={() => selected && setLink(o, selected.projectId)}
                    >
                      {savingId === o.id ? '…' : 'Привязать'}
                    </button>
                    {o.payhub_project_id != null && (
                      <button
                        className={cx('t-btn', styles.unlinkBtn)}
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
