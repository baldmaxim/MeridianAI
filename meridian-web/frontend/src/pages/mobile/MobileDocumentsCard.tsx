import { useState, type FC } from 'react';
import { patchMeetingDocument } from '../../api/meetingDocuments';
import { useDocumentPreview } from '../../components/documentPreview/useDocumentPreview';
import { formatMetaLine, getDocTypeText, groupBySource, isDocPending } from '../../components/context/sourcesModel';
import { apiErrorMessage } from '../../lib/apiError';
import { getDocumentDisplayName } from '../../lib/documentName';
import type { MeetingDocument } from '../../types';
import styles from './MobileDocumentsCard.module.css';

interface IMobileDocumentsCardProps {
  meetingId: number;
  documents: MeetingDocument[];
  onChange: (update: (docs: MeetingDocument[]) => MeetingDocument[]) => void;
}

interface IMobileDocumentRowProps {
  doc: MeetingDocument;
  details: string;
  tags: string;
  onToggle: (doc: MeetingDocument) => Promise<void>;
}

const MobileDocumentRow: FC<IMobileDocumentRowProps> = ({ doc, details, tags, onToggle }) => {
  const name = getDocumentDisplayName(doc);
  const preview = useDocumentPreview({
    documentId: doc.document_id, name, fileExt: doc.file_ext, status: doc.status,
  });

  const info = (
    <>
      <span className={styles.main}>
        <span className={styles.name} title={doc.original_name}>{name}</span>
        {details && <span className={styles.details}>{details}</span>}
        {tags && <span className={styles.tags}>{tags}</span>}
      </span>
      <span className={styles.state}>
        {doc.status === 'ready' ? `${doc.chunks_count} фр.` : doc.status}
      </span>
    </>
  );

  return (
    <div className={styles.rowWrap}>
      {/* чекбокс — своя тап-цель вне кнопки предпросмотра: тап по нему только переключает */}
      <label className={styles.check}>
        <input
          type="checkbox"
          className={styles.checkbox}
          checked={doc.included}
          onChange={() => { void onToggle(doc); }}
          aria-label={`В контексте: ${name}`}
        />
      </label>
      {preview.canPreview ? (
        <button
          type="button"
          className={`${styles.row} ${styles.rowBtn}`}
          onClick={preview.openPreview}
          aria-label={`Открыть ${name}`}
        >
          {info}
        </button>
      ) : (
        <div className={styles.row}>{info}</div>
      )}
      {preview.modal}
    </div>
  );
};

export const MobileDocumentsCard: FC<IMobileDocumentsCardProps> = ({ meetingId, documents, onChange }) => {
  const [error, setError] = useState('');

  const replace = (documentId: number, patch: Partial<MeetingDocument>) =>
    onChange((docs) => docs.map((d) => (d.document_id === documentId ? { ...d, ...patch } : d)));

  const toggle = async (doc: MeetingDocument) => {
    setError('');
    replace(doc.document_id, { included: !doc.included });
    try {
      const saved = await patchMeetingDocument(meetingId, doc.document_id, { included: !doc.included });
      replace(doc.document_id, saved);
    } catch (e) {
      replace(doc.document_id, { included: doc.included });
      setError(apiErrorMessage(e, 'Не удалось изменить документ'));
    }
  };

  const groups = groupBySource(documents);

  return (
    <div className={styles.card}>
      <div className={styles.cardLabel}>ДОКУМЕНТЫ</div>
      {error && <div className={styles.error}>{error}</div>}
      {groups.map((g) => (
        <div key={g.source} className={styles.group}>
          {g.source !== 'meeting' && <div className={styles.groupTitle}>{g.title}</div>}
          {g.docs.map((d) => {
            const typeShown = !!d.doc_type_label || isDocPending(d);
            const tags = (d.doc_tags ?? []).map((t) => t.label).join(', ');
            const details = [typeShown ? getDocTypeText(d) : '', formatMetaLine(d.doc_meta)]
              .filter(Boolean)
              .join(' · ');
            return (
              <MobileDocumentRow key={d.document_id} doc={d} details={details} tags={tags} onToggle={toggle} />
            );
          })}
        </div>
      ))}
      <div className={styles.hint}>Галочка — учитывать документ в подсказках</div>
    </div>
  );
};
