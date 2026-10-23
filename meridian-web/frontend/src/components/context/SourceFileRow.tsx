import type { FC } from 'react';
import type { MeetingDocument } from '../../types';
import { DocumentIcon } from './DocumentIcon';
import {
  formatMetaLine, getDocTypeText, getSourceStatus, isInherited, type SourceStatusKind,
} from './sourcesModel';
import styles from './SourceFileRow.module.css';

interface ISourceFileRowProps {
  doc: MeetingDocument;
  onToggleIncluded: (doc: MeetingDocument) => void;
  onRemove: (doc: MeetingDocument) => void;
  onReprocess: (doc: MeetingDocument, missingPages?: boolean) => void;
}

const STATUS_CLASS: Record<SourceStatusKind, string> = {
  processing: styles.statusProcessing,
  awaiting: styles.statusAwaiting,
  error: styles.statusError,
};

export const SourceFileRow: FC<ISourceFileRowProps> = ({ doc, onToggleIncluded, onRemove, onReprocess }) => {
  const inherited = isInherited(doc);
  const status = getSourceStatus(doc);
  const metaLine = formatMetaLine(doc.doc_meta);
  const tags = doc.doc_tags ?? [];
  const note = status?.detail ?? (status == null ? (doc.ocr_note || doc.quality_note) : null);
  const typeText = getDocTypeText(doc);
  const typeKnown = !!doc.doc_type_label;
  const removeLabel = inherited
    ? `Скрыть «${doc.original_name}» из встречи`
    : `Открепить «${doc.original_name}»`;

  const reprocessAction = doc.status === 'error'
    ? { label: 'Распознать заново', missing: false }
    : doc.status === 'ready' && !doc.ocr_note && (doc.ocr_missing_pages?.length ?? 0) > 0
      ? { label: 'Дораспознать', missing: true }
      : null;

  return (
    <li className={`${styles.row} ${doc.included ? '' : styles.rowOff}`}>
      <div className={styles.top}>
        <DocumentIcon ext={doc.file_ext ?? ''} docType={doc.doc_type} />
        <div className={styles.main}>
          <div className={styles.name} title={doc.original_name}>{doc.original_name}</div>
          <div className={styles.badges}>
            <span className={typeKnown ? styles.typeBadge : styles.typeBadgeEmpty}>{typeText}</span>
            {status && (
              <span className={`${styles.status} ${STATUS_CLASS[status.kind]}`}>● {status.label}</span>
            )}
          </div>
          {tags.length > 0 && (
            <div className={styles.tags}>
              {tags.map((t) => <span key={t.key} className={styles.tag}>{t.label}</span>)}
            </div>
          )}
          {metaLine && <div className={styles.meta}>{metaLine}</div>}
          {note && <div className={`${styles.note} ${status?.kind === 'error' ? styles.noteError : ''}`}>{note}</div>}
        </div>
      </div>

      <div className={styles.actions}>
        <label className={styles.includeLabel}>
          <input
            type="checkbox"
            className={styles.checkbox}
            checked={doc.included}
            onChange={() => onToggleIncluded(doc)}
          />
          <span>в контексте</span>
        </label>
        {reprocessAction && (
          <button
            type="button"
            className={styles.textBtn}
            onClick={() => onReprocess(doc, reprocessAction.missing)}
          >
            {reprocessAction.label}
          </button>
        )}
        <button
          type="button"
          className={styles.removeBtn}
          onClick={() => onRemove(doc)}
          aria-label={removeLabel}
          title={inherited ? 'Скрыть из встречи' : 'Открепить'}
        >
          ✕
        </button>
      </div>
    </li>
  );
};
