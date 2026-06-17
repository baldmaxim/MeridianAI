import type {
  MeetingDocument, MeetingContextSource, PreviousMeetingCandidate,
  DocumentStatus, PreviousMeetingSummaryCard,
} from '../../types';

// ── UI-only модель источников контекста ───────────────────────────────────────
// Эти типы НЕ совпадают с backend ContextSourceType. RAG-папки здесь существуют
// только для отображения — backend их пока не знает. Не подменять backend-типы.

export type ContextSourceKind =
  | 'document'
  | 'previous_meeting'
  | 'rag_folder'
  | 'manual'
  | 'knowledge'
  | 'customer_profile'
  | 'object_profile';

export type ContextSourceUiStatus =
  | 'ready'
  | 'processing'
  | 'pending'
  | 'error'
  | 'disabled';

export interface ContextSourceViewModel {
  id: string;
  kind: ContextSourceKind;
  title: string;
  subtitle?: string;
  meta?: string;
  included: boolean;
  status: ContextSourceUiStatus;
  statusLabel?: string;
  priority?: number;
  accessLost?: boolean;
  disabled?: boolean;
}

export interface ContextSourceSectionSummary {
  total: number;
  included: number;
  ready?: number;
  processing?: number;
  errors?: number;
}

const UI_STATUS_LABELS: Record<ContextSourceUiStatus, string> = {
  ready: 'готов',
  processing: 'обработка…',
  pending: 'ожидание',
  error: 'ошибка',
  disabled: 'недоступно',
};

function documentUiStatus(s: DocumentStatus): ContextSourceUiStatus {
  if (s === 'ready') return 'ready';
  if (s === 'error') return 'error';
  if (s === 'pending') return 'pending';
  // uploaded / processing → идёт обработка
  return 'processing';
}

function counts(c: Pick<PreviousMeetingSummaryCard, 'decisions_count' | 'action_items_count' | 'risks_count'>): string {
  const parts: string[] = [];
  if (c?.decisions_count) parts.push(`решения: ${c.decisions_count}`);
  if (c?.action_items_count) parts.push(`задачи: ${c.action_items_count}`);
  if (c?.risks_count) parts.push(`риски: ${c.risks_count}`);
  return parts.join(' · ');
}

function joinMeta(...parts: (string | null | undefined)[]): string | undefined {
  const out = parts.map((p) => (p ?? '').trim()).filter(Boolean);
  return out.length ? out.join('  ·  ') : undefined;
}

// ── Mappers (чистые преобразования, без API-запросов) ─────────────────────────

export function documentToContextSourceViewModel(doc: MeetingDocument): ContextSourceViewModel {
  const status = documentUiStatus(doc.status);
  const subtitle = status === 'error' ? (doc.processing_error ?? undefined) : undefined;
  const meta = status === 'ready' && doc.chunks_count ? `${doc.chunks_count} фрагм.` : undefined;
  return {
    id: `doc-${doc.id}`,
    kind: 'document',
    title: doc.original_name || `Документ #${doc.id}`,
    subtitle,
    meta,
    included: !!doc.included,
    status,
    statusLabel: UI_STATUS_LABELS[status],
    priority: doc.priority,
  };
}

export function previousMeetingSourceToContextSourceViewModel(source: MeetingContextSource): ContextSourceViewModel {
  const accessLost = !!source.access_lost;
  const summary = source.summary;
  const title = accessLost
    ? '— нет доступа —'
    : (summary?.title || `Встреча #${source.source_id ?? '?'}`);
  const subtitle = accessLost ? undefined : (summary?.micro_summary ?? undefined);
  const meta = accessLost || !summary
    ? undefined
    : joinMeta(
        [summary.customer_name, summary.object_name].filter(Boolean).join(' · '),
        counts(summary),
      );
  return {
    id: `pms-${source.id}`,
    kind: 'previous_meeting',
    title,
    subtitle,
    meta,
    included: !!source.included,
    status: accessLost ? 'disabled' : 'ready',
    statusLabel: accessLost ? UI_STATUS_LABELS.disabled : undefined,
    priority: source.priority,
    accessLost,
    disabled: accessLost,
  };
}

export function previousMeetingCandidateToContextSourceViewModel(candidate: PreviousMeetingCandidate): ContextSourceViewModel {
  const tags = (candidate.tags ?? []).slice(0, 3).join(', ');
  const meta = joinMeta(
    [candidate.customer_name, candidate.object_name].filter(Boolean).join(' · '),
    counts(candidate),
    tags,
  );
  return {
    id: `cand-${candidate.meeting_id}`,
    kind: 'previous_meeting',
    title: candidate.title || `Встреча #${candidate.meeting_id}`,
    subtitle: candidate.micro_summary ?? undefined,
    meta,
    included: !!candidate.already_added,
    status: 'ready',
  };
}

export function ragPlaceholderToContextSourceViewModel(): ContextSourceViewModel {
  return {
    id: 'rag-placeholder',
    kind: 'rag_folder',
    title: 'RAG-папки',
    subtitle: 'Скоро: перетащите папку из базы знаний/RAG в контекст встречи',
    included: false,
    status: 'disabled',
    statusLabel: 'скоро',
    disabled: true,
  };
}
