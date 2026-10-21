import { useState } from 'react';
import { apiErrorMessage } from '../../lib/apiError';
import { useKnowledgeList, useArchiveKnowledgeItem } from '../../hooks/queries/knowledge';
import type {
  GlossaryTerm, TriggerPhrase, NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase, KnowledgeKind,
} from '../../types';
import styles from './KnowledgeList.module.css';

interface Props { kind: KnowledgeKind; }

type AnyItem = GlossaryTerm | TriggerPhrase | NegotiationPlaybook | CounterpartyTrait | ForbiddenPhrase;

const SCOPE_LABEL: Record<string, string> = { global: 'Общее', customer: 'Заказчик', object: 'Объект' };

function parseList(json: string | null): string[] {
  if (!json) return [];
  try { const a = JSON.parse(json); return Array.isArray(a) ? a : []; } catch { return []; }
}

function renderItem(kind: KnowledgeKind, it: AnyItem): { main: string; sub?: string; meta?: string } {
  switch (kind) {
    case 'terms': {
      const t = it as GlossaryTerm;
      const al = parseList(t.aliases_json);
      return { main: t.term + (al.length ? ` (${al.join(', ')})` : ''), sub: t.definition };
    }
    case 'triggers': {
      const t = it as TriggerPhrase;
      return { main: `«${t.phrase}»`, sub: t.recommended_reaction, meta: t.event_type };
    }
    case 'playbooks': {
      const p = it as NegotiationPlaybook;
      const ask = parseList(p.ask_in_return_json);
      return { main: p.situation, sub: `«${p.recommended_phrase}»` + (ask.length ? `  ·  взамен: ${ask.join('; ')}` : ''), meta: p.technique };
    }
    case 'traits': {
      const t = it as CounterpartyTrait;
      return { main: t.trait, sub: t.recommended_strategy || undefined, meta: t.evidence || undefined };
    }
    case 'forbidden': {
      const f = it as ForbiddenPhrase;
      return { main: f.phrase_or_risk, sub: f.better_alternative ? `Лучше: «${f.better_alternative}»` : undefined, meta: f.reason || undefined };
    }
  }
}

export function KnowledgeList({ kind }: Props) {
  const { data, isPending, error: queryError } = useKnowledgeList(kind, { status: 'approved' });
  const archiveMut = useArchiveKnowledgeItem();
  const items = (data ?? []) as AnyItem[];
  const [actionError, setActionError] = useState<string | null>(null);

  async function archive(id: number) {
    setActionError(null);
    try {
      await archiveMut.mutateAsync({ kind, id });
    } catch (e) { setActionError(apiErrorMessage(e, 'Не удалось архивировать')); }
  }

  if (isPending) return <div className={styles.muted}>Загрузка…</div>;
  const error = actionError ?? (queryError ? apiErrorMessage(queryError, 'Не удалось загрузить') : null);
  if (error) return <div className={styles.error}>{error}</div>;
  if (items.length === 0) return <div className={styles.muted}>Пока пусто. Элементы добавляются после проверки кандидатов.</div>;

  return (
    <div className={styles.list}>
      {items.map((it) => {
        const r = renderItem(kind, it);
        return (
          <div key={it.id} className={styles.card}>
            <div className={styles.row}>
              <span className={styles.scope}>{SCOPE_LABEL[(it as { scope?: string }).scope || 'global'] || 'Общее'}</span>
              {r.meta && <span className={styles.meta}>{r.meta}</span>}
              <span className={styles.spacer} />
              <button className={styles.archive} disabled={archiveMut.isPending && archiveMut.variables?.id === it.id} onClick={() => archive(it.id)}>В архив</button>
            </div>
            <div className={styles.main}>{r.main}</div>
            {r.sub && <div className={styles.sub}>{r.sub}</div>}
          </div>
        );
      })}
    </div>
  );
}
