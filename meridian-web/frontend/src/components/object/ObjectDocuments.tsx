import { useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';
import { listDocumentRecords } from '../../api/documents';
import { listObjectOfferSubmissions } from '../../api/objects';
import { apiErrorMessage } from '../../lib/apiError';
import type { DocumentRecord, IOfferSubmission } from '../../types';
import { Collapse } from '../common/Collapse';
import { TextInput } from '../common/TextInput';
import { cx } from '../../utils/cx';
import { ObjectDocumentRow } from './ObjectDocumentRow';
import { ObjectSubmissions } from './ObjectSubmissions';
import type { IObjectSubmissionItem } from './ObjectSubmissions';
import { splitObjectDocuments } from './offerSubmissions';
import styles from './ObjectDocuments.module.css';

const PAGE_SIZE = 500; // максимум limit в GET /documents
const NO_TYPE_LABEL = 'Без типа';
const NO_FOLDER_LABEL = 'Вне папок подач';
// Ключи ручных переключений: подачи и группы типов не пересекаются по имени.
const subKey = (key: string) => `sub:${key}`;
const typeKey = (label: string) => `type:${label}`;

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
  const [submissions, setSubmissions] = useState<IOfferSubmission[]>([]);
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
    // Порядок подач (от новой к старой) — с бэкенда; при сбое список выведем из самих документов.
    listObjectOfferSubmissions(objectId)
      .then((list) => { if (!cancelled) setSubmissions(list); })
      .catch(() => { /* фолбэк: подачи из offer_submission документов */ });
    return () => { cancelled = true; };
  }, [objectId]);

  const searching = query.trim() !== '';

  const { submissionItems, latestKey, hasSubmissions, groups } = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = (d: DocumentRecord) => !needle || d.original_name.toLowerCase().includes(needle);
    const { bySubmission, general } = splitObjectDocuments(docs);

    // Порядок — как отдал бэкенд; подачи, которых в списке нет, но документы есть, — в конец.
    const known = new Set(submissions.map((s) => s.key));
    const ordered: IOfferSubmission[] = [
      ...submissions,
      ...[...bySubmission.keys()]
        .filter((k) => !known.has(k))
        .map((k) => ({ key: k, label: k || NO_FOLDER_LABEL, date: null, document_count: bySubmission.get(k)?.length ?? 0 })),
    ].filter((s) => bySubmission.has(s.key));

    const items: IObjectSubmissionItem[] = ordered
      .map((submission) => ({ submission, docs: (bySubmission.get(submission.key) ?? []).filter(matches) }))
      .filter((i) => i.docs.length > 0);

    const map = new Map<string, DocumentRecord[]>();
    general.filter(matches).forEach((d) => {
      const label = d.doc_type_label || NO_TYPE_LABEL;
      const list = map.get(label);
      if (list) list.push(d); else map.set(label, [d]);
    });
    const typeGroups: IDocGroup[] = [...map.entries()]
      .map(([label, list]) => ({ label, docs: list }))
      .sort((a, b) => b.docs.length - a.docs.length || a.label.localeCompare(b.label, 'ru'));

    return { submissionItems: items, latestKey: ordered[0]?.key ?? null, hasSubmissions: bySubmission.size > 0, groups: typeGroups };
  }, [docs, submissions, query]);

  const onQueryChange = (value: string) => {
    if ((value.trim() !== '') !== searching) setToggled({});
    setQuery(value);
  };

  // Группа раскрыта при непустом поиске; последняя подача КП — раскрыта по умолчанию.
  const isOpen = (id: string, byDefault = false) => toggled[id] ?? (searching || byDefault);
  const toggle = (id: string, byDefault = false) => setToggled((t) => ({ ...t, [id]: !isOpen(id, byDefault) }));

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

      {docs.length > 0 && searching && groups.length === 0 && submissionItems.length === 0 && (
        <div className={styles.muted}>Ничего не найдено</div>
      )}

      <ObjectSubmissions
        items={submissionItems}
        isOpen={(key) => isOpen(subKey(key), key === latestKey)}
        onToggle={(key) => toggle(subKey(key), key === latestKey)}
      />

      {groups.length > 0 && (
        <div className={styles.subsection}>
          {hasSubmissions && <div className={styles.subTitle}>Общий контекст</div>}
          <div className={styles.groups}>
            {groups.map((g) => {
              const open = isOpen(typeKey(g.label));
              return (
                <div key={g.label} className={styles.group}>
                  <button
                    type="button"
                    className={styles.groupHead}
                    onClick={() => toggle(typeKey(g.label))}
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
        </div>
      )}
    </section>
  );
};
