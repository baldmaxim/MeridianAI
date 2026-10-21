import { useEffect, useMemo, useState } from 'react';
import { searchLetters, type LetterHit } from '../api/letters';
import { listObjects } from '../api/objects';
import type { ProjectObject } from '../types';
import { apiErrorMessage } from '../lib/apiError';
import { navTo, paths } from '../lib/navigation';
import { SearchableSelect, TextInput, type SearchableOption } from '../components/common';
import { theme } from '../styles/theme';
import styles from './LettersSearchPage.module.css';
import { cx } from '../utils/cx';

interface Props {
  onBack: () => void;
}

const ALL_VALUE = '';

function directionLabel(d: string | null): string {
  return (d || '').toLowerCase() === 'incoming' ? 'входящее' : 'исходящее';
}

function letterNumber(h: LetterHit): string {
  return h.regNumber || h.number || h.customerNumber || '—';
}

/** Прямой семантический поиск по письмам PayHub (внешний RAG-корпус). */
export function LettersSearchPage({ onBack }: Props) {
  const [query, setQuery] = useState('');
  const [objects, setObjects] = useState<ProjectObject[]>([]);
  const [objectId, setObjectId] = useState<string>(ALL_VALUE); // '' = все письма
  const [hits, setHits] = useState<LetterHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    listObjects().then(setObjects).catch(() => { /* объектов может не быть */ });
  }, []);

  const selectedObject = useMemo(
    () => (objectId ? objects.find((o) => String(o.id) === objectId) ?? null : null),
    [objects, objectId],
  );
  const unlinked = selectedObject != null && selectedObject.payhub_project_id == null;

  const options: SearchableOption[] = useMemo(() => [
    { value: ALL_VALUE, label: 'Все письма', search: 'все письма все объекты' },
    ...objects.map((o) => ({
      value: String(o.id),
      label: (
        <span className={styles.cardBody}>
          <span className={styles.optName}>{o.name}</span>
          {o.customer_name && <span className={styles.optMeta}>{o.customer_name}</span>}
        </span>
      ),
      search: `${o.name} ${o.customer_name ?? ''}`,
    })),
  ], [objects]);

  async function run() {
    const q = query.trim();
    if (!q) return;
    const projectId = selectedObject?.payhub_project_id ?? null;
    setLoading(true);
    setError('');
    try {
      const res = await searchLetters({ query: q, k: 8, projectId });
      setHits(res);
      setSearched(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось выполнить поиск по письмам'));
      setHits([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.head}>
        <button className={cx('t-btn', styles.back)} onClick={onBack}>← Назад</button>
        <span className={styles.title}>Поиск по письмам</span>
        <span className={styles.subtitle}>PayHub · семантический + полнотекстовый</span>
        <button className={cx('t-btn', styles.linkProjects)} {...navTo(paths.projectLinks)}>Связка проектов</button>
      </div>

      <div className={styles.searchRow}>
        <TextInput
          className={styles.inputField}
          inputClassName={styles.input}
          placeholder="О чём письма? Напр.: срок поставки оборудования"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery('')}
          clearLabel="запрос"
          onKeyDown={(e) => { if (e.key === 'Enter') run(); }}
          autoFocus
        />
        <SearchableSelect
          value={objectId}
          onChange={setObjectId}
          options={options}
          placeholder="Все письма"
          searchPlaceholder="Объект или заказчик…"
          ariaLabel="Объект"
          style={objectSelectStyle}
          className={styles.objectWrap}
        />
        <button className={cx('t-btn t-btn-amber', styles.searchBtn)} onClick={run} disabled={loading}>
          {loading ? 'Поиск…' : 'Найти'}
        </button>
      </div>

      {unlinked && (
        <div className={styles.hint}>
          Объект «{selectedObject?.name}» не привязан к проекту PayHub — поиск идёт по всему корпусу.{' '}
          <button className={styles.hintLink} {...navTo(paths.projectLinks)}>Привязать проекты</button>
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.results}>
        {!loading && searched && hits.length === 0 && !error && (
          <div className={styles.empty}>Ничего не найдено</div>
        )}
        {hits.map((h) => (
          <div key={h.chunkId} className={styles.card}>
            <div className={styles.cardHead}>
              <span className={styles.badge}>{directionLabel(h.direction)}</span>
              <span className={styles.cardNum}>№ {letterNumber(h)}</span>
              {h.letterDate && <span className={styles.cardDate}>{h.letterDate}</span>}
              <span className={styles.score}>{h.score.toFixed(3)}</span>
            </div>
            {h.subject && <div className={styles.subject}>{h.subject}</div>}
            <div className={styles.snippet}>{h.text}</div>
            {(h.pageFrom != null || h.pageTo != null) && (
              <div className={styles.pages}>стр. {h.pageFrom ?? '?'}–{h.pageTo ?? '?'}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Стиль триггера <SearchableSelect>: компонент принимает только style (не className). */
const objectSelectStyle: React.CSSProperties = {
  padding: '10px 14px',
  background: theme.bg.input,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 8,
  color: theme.text.primary,
  fontSize: 13,
  fontFamily: theme.font.body,
  outline: 'none',
};
