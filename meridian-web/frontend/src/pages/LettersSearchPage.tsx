import { useEffect, useMemo, useState } from 'react';
import { searchLetters, type LetterHit } from '../api/letters';
import { listObjects } from '../api/objects';
import type { ProjectObject } from '../types';
import { apiErrorMessage } from '../lib/apiError';
import { navigate, paths } from '../lib/navigation';
import { SearchableSelect, type SearchableOption } from '../components/common';
import { theme } from '../styles/theme';

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
        <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <span style={styles.optName}>{o.name}</span>
          {o.customer_name && <span style={styles.optMeta}>{o.customer_name}</span>}
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
    <div style={styles.container}>
      <div style={styles.head}>
        <button className="t-btn" style={styles.back} onClick={onBack}>← Назад</button>
        <span style={styles.title}>Поиск по письмам</span>
        <span style={styles.subtitle}>PayHub · семантический + полнотекстовый</span>
        <button className="t-btn" style={styles.linkProjects} onClick={() => navigate(paths.projectLinks)}>Связка проектов</button>
      </div>

      <div style={styles.searchRow}>
        <input
          style={styles.input}
          placeholder="О чём письма? Напр.: срок поставки оборудования"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
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
          style={styles.objectSelect}
          wrapperStyle={styles.objectWrap}
        />
        <button className="t-btn t-btn-amber" style={styles.searchBtn} onClick={run} disabled={loading}>
          {loading ? 'Поиск…' : 'Найти'}
        </button>
      </div>

      {unlinked && (
        <div style={styles.hint}>
          Объект «{selectedObject?.name}» не привязан к проекту PayHub — поиск идёт по всему корпусу.{' '}
          <button style={styles.hintLink} onClick={() => navigate(paths.projectLinks)}>Привязать проекты</button>
        </div>
      )}

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.results}>
        {!loading && searched && hits.length === 0 && !error && (
          <div style={styles.empty}>Ничего не найдено</div>
        )}
        {hits.map((h) => (
          <div key={h.chunkId} style={styles.card}>
            <div style={styles.cardHead}>
              <span style={styles.badge}>{directionLabel(h.direction)}</span>
              <span style={styles.cardNum}>№ {letterNumber(h)}</span>
              {h.letterDate && <span style={styles.cardDate}>{h.letterDate}</span>}
              <span style={styles.score}>{h.score.toFixed(3)}</span>
            </div>
            {h.subject && <div style={styles.subject}>{h.subject}</div>}
            <div style={styles.snippet}>{h.text}</div>
            {(h.pageFrom != null || h.pageTo != null) && (
              <div style={styles.pages}>стр. {h.pageFrom ?? '?'}–{h.pageTo ?? '?'}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    padding: '18px 20px',
    gap: 14,
    overflow: 'hidden',
  },
  head: { display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' },
  back: {
    padding: '5px 12px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 5, color: theme.accent.amber, cursor: 'pointer',
    fontSize: 11, fontFamily: theme.font.mono, letterSpacing: '0.06em',
  },
  title: { fontFamily: theme.font.heading, fontWeight: 800, fontSize: 18, color: theme.text.primary },
  subtitle: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.08em' },
  linkProjects: {
    marginLeft: 'auto', padding: '5px 12px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 5, color: theme.accent.amber, cursor: 'pointer',
    fontSize: 11, fontFamily: theme.font.mono, letterSpacing: '0.06em',
  },
  searchRow: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  input: {
    flex: 1, minWidth: 240, padding: '10px 14px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.primary,
    fontSize: 14, fontFamily: theme.font.body, outline: 'none',
  },
  objectWrap: { width: 260 },
  objectSelect: {
    padding: '10px 14px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.primary,
    fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  optName: { fontSize: 13, color: theme.text.primary, fontFamily: theme.font.body, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  optMeta: { fontSize: 11, color: theme.text.muted, fontFamily: theme.font.mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  hint: {
    fontSize: 12, fontFamily: theme.font.body, color: theme.text.secondary,
    display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
  },
  hintLink: {
    background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
    color: theme.accent.amber, fontSize: 12, fontFamily: theme.font.body, textDecoration: 'underline',
  },
  searchBtn: {
    padding: '10px 20px', borderRadius: 8, border: `1px solid ${theme.accent.amber}`,
    background: theme.accent.amberGlow, color: theme.accent.amber, cursor: 'pointer',
    fontSize: 13, fontFamily: theme.font.mono, fontWeight: 600, letterSpacing: '0.06em',
  },
  error: {
    padding: '10px 14px', background: theme.accent.redDim, border: `1px solid ${theme.accent.red}`,
    borderRadius: 8, color: theme.accent.red, fontSize: 13, fontFamily: theme.font.body,
  },
  results: { flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 },
  empty: { padding: 24, textAlign: 'center', color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13 },
  card: {
    padding: '12px 14px', background: theme.bg.card, border: `1px solid ${theme.border.default}`,
    borderRadius: 10, display: 'flex', flexDirection: 'column', gap: 6,
  },
  cardHead: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
  badge: {
    padding: '2px 9px', borderRadius: 12, fontSize: 10, fontFamily: theme.font.mono,
    color: theme.accent.blue, border: '1px solid rgba(91,156,246,0.25)', letterSpacing: '0.06em',
  },
  cardNum: { fontFamily: theme.font.mono, fontSize: 12, color: theme.text.secondary },
  cardDate: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  score: {
    marginLeft: 'auto', fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber,
    opacity: 0.8,
  },
  subject: { fontFamily: theme.font.body, fontSize: 14, fontWeight: 600, color: theme.text.primary },
  snippet: {
    fontFamily: theme.font.body, fontSize: 13, color: theme.text.secondary, lineHeight: 1.5,
    whiteSpace: 'pre-wrap', maxHeight: 140, overflow: 'hidden',
  },
  pages: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
};
