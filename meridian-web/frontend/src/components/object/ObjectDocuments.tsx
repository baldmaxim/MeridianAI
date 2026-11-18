import { useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';
import { listDocumentRecords } from '../../api/documents';
import { apiErrorMessage } from '../../lib/apiError';
import type { DocumentRecord } from '../../types';
import { Collapse } from '../common/Collapse';
import { TextInput } from '../common/TextInput';
import { cx } from '../../utils/cx';
import { ObjectDocumentRow } from './ObjectDocumentRow';
import styles from './ObjectDocuments.module.css';

const PAGE_SIZE = 500; // максимум limit в GET /documents
const NO_TYPE_LABEL = 'Без типа';

interface IObjectDocumentsProps {
  /** При смене объекта монтировать заново (key={objectId}) — состояние не переиспользуется. */
  objectId: number;
}

interface IDocGroup {
  label: string;
  docs: DocumentRecord[];
}

/** Все документы объекта: GET /documents отдаёт не больше 500 за запрос — листаем до конца. */
const loadAllObjectDocuments = async (objectId: number): Promise<DocumentRecord[]> => {
  const all = new Map<number, DocumentRecord>();
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const page = await listDocumentRecords({ object_id: objectId, limit: PAGE_SIZE, offset });
    page.forEach((d) => all.set(d.id, d));
    if (page.length < PAGE_SIZE) break;
  }
  return [...all.values()];
};

export const ObjectDocuments: FC<IObjectDocumentsProps> = ({ objectId }) => {
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  // Ручные переключения групп; без записи группа раскрыта только при непустом поиске.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    loadAllObjectDocuments(objectId)
      .then((list) => { if (!cancelled) setDocs(list.filter((d) => (d.status as string) !== 'deleted')); })
      .catch((e) => { if (!cancelled) setError(apiErrorMessage(e, 'Не удалось загрузить документы')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [objectId]);

  const searching = query.trim() !== '';

  const groups = useMemo<IDocGroup[]>(() => {
    const needle = query.trim().toLowerCase();
    const map = new Map<string, DocumentRecord[]>();
    docs.forEach((d) => {
      if (needle && !d.original_name.toLowerCase().includes(needle)) return;
      const label = d.doc_type_label || NO_TYPE_LABEL;
      const list = map.get(label);
      if (list) list.push(d); else map.set(label, [d]);
    });
    return [...map.entries()]
      .map(([label, list]) => ({ label, docs: list }))
      .sort((a, b) => b.docs.length - a.docs.length || a.label.localeCompare(b.label, 'ru'));
  }, [docs, query]);

  const onQueryChange = (value: string) => {
    if ((value.trim() !== '') !== searching) setToggled({});
    setQuery(value);
  };

  const isOpen = (label: string) => toggled[label] ?? searching;
  const toggle = (label: string) => setToggled((t) => ({ ...t, [label]: !isOpen(label) }));

  return (
    <section className={styles.section}>
      <div className={styles.sectionTitle}>Документы ({docs.length})</div>

      {loading && <div className={styles.muted}>Загрузка…</div>}
      {error && <div className={styles.error}>{error}</div>}

      {!loading && !error && docs.length === 0 && (
        <div className={styles.muted}>По объекту нет документов</div>
      )}

      {docs.length > 0 && (
        <TextInput
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onClear={() => onQueryChange('')}
          clearLabel="поиск документов"
          placeholder="Поиск по имени файла"
          aria-label="Поиск документов по имени файла"
        />
      )}

      {docs.length > 0 && searching && groups.length === 0 && (
        <div className={styles.muted}>Ничего не найдено</div>
      )}

      <div className={styles.groups}>
        {groups.map((g) => {
          const open = isOpen(g.label);
          return (
            <div key={g.label} className={styles.group}>
              <button
                type="button"
                className={styles.groupHead}
                onClick={() => toggle(g.label)}
                aria-expanded={open}
              >
                <span className={cx(styles.chevron, open && styles.chevronOpen)}>▶</span>
                <span className={styles.groupTitle}>{g.label}</span>
                <span className={styles.groupCount}>{g.docs.length}</span>
              </button>
              <Collapse open={open} className={styles.groupBody}>
                {g.docs.map((d) => <ObjectDocumentRow key={d.id} doc={d} />)}
              </Collapse>
            </div>
          );
        })}
      </div>
    </section>
  );
};
