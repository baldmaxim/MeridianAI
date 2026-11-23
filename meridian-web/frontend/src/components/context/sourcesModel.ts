import type {
  DocClassifierItem, DocMeta, IOfferSubmission, MeetingDocument, MeetingDocumentSource,
} from '../../types';
import { splitObjectDocuments } from '../object/offerSubmissions';

// Чистая модель панели «Источники»: группировка, фильтры, счётчики, подписи статусов.

export interface ISourceGroup {
  source: MeetingDocumentSource;
  title: string;
  docs: MeetingDocument[];
}

export interface ITypeChip {
  key: string;
  label: string;
  count: number;
}

export type SourceStatusKind = 'processing' | 'awaiting' | 'error';

export interface ISourceStatus {
  kind: SourceStatusKind;
  label: string;
  detail?: string;
}

export const SOURCE_GROUP_ORDER: readonly MeetingDocumentSource[] = ['meeting', 'customer', 'object'];

export const SOURCE_GROUP_TITLES: Record<MeetingDocumentSource, string> = {
  meeting: 'Файлы встречи',
  customer: 'Из контрагента',
  object: 'Из объекта',
};

const TYPE_PENDING_LABEL = 'Определяется…';
const TYPE_EMPTY_LABEL = '—';

/** Документы без поля source (старый бэкенд) считаем файлами встречи. */
export const getDocSource = (doc: MeetingDocument): MeetingDocumentSource => doc.source ?? 'meeting';

export const isInherited = (doc: MeetingDocument): boolean => getDocSource(doc) !== 'meeting';

export const groupBySource = (docs: readonly MeetingDocument[]): ISourceGroup[] =>
  SOURCE_GROUP_ORDER
    .map((source) => ({
      source,
      title: SOURCE_GROUP_TITLES[source],
      docs: docs.filter((d) => getDocSource(d) === source),
    }))
    .filter((g) => g.docs.length > 0);

export type DocGroupKind = 'submission' | 'documentation' | 'meeting';

export interface IDocGroup {
  /** Стабильный ключ: для подачи — `submission:<key>`. */
  id: string;
  kind: DocGroupKind;
  title: string;
  docs: MeetingDocument[];
  defaultOpen: boolean;
}

export const NO_FOLDER_LABEL = 'Вне папок подач';

/**
 * Группы списка документов: «Отправка: …» (по подаче КП), «Документация» (общий контекст объекта/контрагента),
 * «Добавлены к встрече» (загружены к самой встрече). Пустые группы скрыты.
 * Подачи — в порядке списка подач (новая первая), выбранная подача — первой; неизвестные ключи — в конце.
 */
export const buildDocGroups = (
  docs: readonly MeetingDocument[],
  submissions: readonly IOfferSubmission[],
  selectedSubmission: string | null,
): IDocGroup[] => {
  const added = docs.filter((d) => !isInherited(d));
  const { bySubmission, general } = splitObjectDocuments(docs.filter(isInherited));

  const order = submissions.map((s) => s.key);
  const rank = (key: string): number => {
    if (key === selectedSubmission) return -1;
    const i = order.indexOf(key);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  const labelOf = (key: string): string =>
    submissions.find((s) => s.key === key)?.label ?? (key || NO_FOLDER_LABEL);

  const groups: IDocGroup[] = [...bySubmission.keys()]
    .sort((a, b) => rank(a) - rank(b))
    .map((key) => ({
      id: `submission:${key}`,
      kind: 'submission' as const,
      title: `Отправка: ${labelOf(key)}`,
      docs: bySubmission.get(key) ?? [],
      defaultOpen: true,
    }));
  if (general.length > 0) {
    groups.push({ id: 'documentation', kind: 'documentation', title: 'Документация', docs: general, defaultOpen: false });
  }
  if (added.length > 0) {
    groups.push({ id: 'meeting', kind: 'meeting', title: 'Добавлены к встрече', docs: added, defaultOpen: true });
  }
  return groups;
};

/** Чипы фильтра по типу: только типы, встречающиеся в списке; порядок — по словарю, затем по появлению. */
export const buildTypeChips = (
  docs: readonly MeetingDocument[],
  vocabTypes: readonly DocClassifierItem[] = [],
): ITypeChip[] => {
  const map = new Map<string, ITypeChip>();
  for (const d of docs) {
    if (!d.doc_type) continue;
    const prev = map.get(d.doc_type);
    if (prev) {
      prev.count += 1;
    } else {
      const label = d.doc_type_label
        ?? vocabTypes.find((t) => t.key === d.doc_type)?.label
        ?? d.doc_type;
      map.set(d.doc_type, { key: d.doc_type, label, count: 1 });
    }
  }
  const order = (key: string): number => {
    const i = vocabTypes.findIndex((t) => t.key === key);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  return [...map.values()].sort((a, b) => order(a.key) - order(b.key));
};

export const filterByType = (docs: readonly MeetingDocument[], typeKey: string | null): MeetingDocument[] =>
  typeKey == null ? [...docs] : docs.filter((d) => d.doc_type === typeKey);

export const countIncluded = (docs: readonly MeetingDocument[]): { included: number; total: number } => ({
  included: docs.filter((d) => d.included).length,
  total: docs.length,
});

export const isDocPending = (doc: MeetingDocument): boolean =>
  doc.status === 'processing' || doc.status === 'uploaded';

/** Подпись типа: метка классификатора, «Определяется…» пока идёт обработка, иначе «—». */
export const getDocTypeText = (doc: MeetingDocument): string => {
  if (doc.doc_type_label) return doc.doc_type_label;
  return isDocPending(doc) ? TYPE_PENDING_LABEL : TYPE_EMPTY_LABEL;
};

/** Статус обработки; для готового документа — null. */
export const getSourceStatus = (doc: MeetingDocument): ISourceStatus | null => {
  switch (doc.status) {
    case 'ready':
      return null;
    case 'error':
      return { kind: 'error', label: 'Ошибка', detail: doc.processing_error ?? undefined };
    case 'awaiting_ocr':
      return { kind: 'awaiting', label: 'Ждёт OCR', detail: doc.ocr_note ?? undefined };
    default:
      return { kind: 'processing', label: 'Обработка' };
  }
};

const POLL_PENDING_MS = 3000;
const POLL_AWAITING_MS = 60000;

/** Интервал опроса списка: часто, пока документ обрабатывается; редко, пока скан ждёт OCR; null — не опрашивать. */
export const getPollInterval = (docs: readonly MeetingDocument[]): number | null => {
  if (docs.some((d) => !['ready', 'error', 'awaiting_ocr'].includes(d.status))) return POLL_PENDING_MS;
  if (docs.some((d) => d.status === 'awaiting_ocr' || !!d.ocr_note)) return POLL_AWAITING_MS;
  return null;
};

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

const formatMetaDate = (value: string): string => {
  const m = ISO_DATE.exec(value);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : value;
};

/** Строка метаданных: «№ 12 · от 01.02.2025 · контрагент · сумма». Пустая строка, если данных нет. */
export const formatMetaLine = (meta: DocMeta | null | undefined): string => {
  if (!meta) return '';
  const parts: string[] = [];
  if (meta.number) parts.push(`№ ${meta.number}`);
  if (meta.date) parts.push(`от ${formatMetaDate(meta.date)}`);
  if (meta.counterparty_name) parts.push(meta.counterparty_name);
  if (meta.amount) parts.push(meta.amount);
  return parts.join(' · ');
};
