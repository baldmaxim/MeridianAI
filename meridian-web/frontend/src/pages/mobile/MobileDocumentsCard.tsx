import { useState, type FC } from 'react';
import { patchMeetingDocument } from '../../api/meetingDocuments';
import { formatMetaLine, getDocTypeText, groupBySource, isDocPending } from '../../components/context/sourcesModel';
import { apiErrorMessage } from '../../lib/apiError';
import type { MeetingDocument } from '../../types';
import styles from './MobileDocumentsCard.module.css';

interface IMobileDocumentsCardProps {
  meetingId: number;
  documents: MeetingDocument[];
  onChange: (update: (docs: MeetingDocument[]) => MeetingDocument[]) => void;
}

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
              <label key={d.document_id} className={styles.row}>
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={d.included}
                  onChange={() => { void toggle(d); }}
                  aria-label={`В контексте: ${d.original_name}`}
                />
                <span className={styles.main}>
                  <span className={styles.name}>{d.original_name}</span>
                  {details && <span className={styles.details}>{details}</span>}
                  {tags && <span className={styles.tags}>{tags}</span>}
                </span>
                <span className={styles.state}>
                  {d.status === 'ready' ? `${d.chunks_count} фр.` : d.status}
                </span>
              </label>
            );
          })}
        </div>
      ))}
      <div className={styles.hint}>Галочка — учитывать документ в подсказках</div>
    </div>
  );
};
