import { useEffect, useState } from 'react';
import type { FC } from 'react';
import { listMeetingDocuments } from '../../api/meetingDocuments';
import { DocumentPreviewButton } from '../../components/documentPreview/DocumentPreviewButton';
import type { MeetingDetail, MeetingDocument } from '../../types';
import { NEGOTIATION_TYPE_LABELS, getDocTone } from './meetingDetailFormat';
import styles from './ContextBlock.module.css';

interface IContextBlockProps {
  meeting: MeetingDetail;
}

export const ContextBlock: FC<IContextBlockProps> = ({ meeting }) => {
  // В деталях встречи документы без id — для предпросмотра сопоставляем по имени со списком документов встречи.
  const [attached, setAttached] = useState<MeetingDocument[]>([]);
  useEffect(() => {
    let cancelled = false;
    listMeetingDocuments(meeting.id)
      .then((list) => { if (!cancelled) setAttached(list); })
      .catch(() => { /* список недоступен — просто без кнопки «Открыть» */ });
    return () => { cancelled = true; };
  }, [meeting.id]);

  const fields = [
    { label: 'Тема', value: meeting.meeting_topic },
    { label: 'Тип переговоров', value: meeting.negotiation_type ? (NEGOTIATION_TYPE_LABELS[meeting.negotiation_type] || meeting.negotiation_type) : null },
    { label: 'Роль', value: meeting.meeting_role },
    { label: 'Заметки', value: meeting.meeting_notes },
    { label: 'Слабости оппонента', value: meeting.opponent_weaknesses },
  ].filter(f => f.value);

  const docs = meeting.documents || [];
  const hasContent = fields.length > 0 || docs.length > 0;

  if (!hasContent) {
    return <div className={styles.emptyPanel}>Контекст не заполнен</div>;
  }

  return (
    <div className={styles.contextFields}>
      {fields.map((f, i) => (
        <div key={i}>
          <div className={styles.contextLabel}>{f.label}</div>
          <div className={styles.contextValue}>{f.value}</div>
        </div>
      ))}
      {docs.length > 0 && (
        <div>
          <div className={styles.contextLabel}>Документы</div>
          <div className={styles.docList}>
            {docs.map((doc) => {
              const ext = doc.filename.split('.').pop() || '';
              const extLower = ext.toLowerCase();
              const countLabel = extLower === 'xlsx' ? `${doc.page_count} лист.`
                : ['txt', 'md'].includes(extLower) ? '' : `${doc.page_count} стр.`;
              const source = attached.find((a) => a.original_name === doc.filename);
              return (
                <div key={doc.filename} className={styles.doc}>
                  <span className={`${styles.docExt} ${styles[getDocTone(ext)]}`}>
                    {ext.toUpperCase()}
                  </span>
                  <span className={styles.docName}>{doc.filename}</span>
                  <span className={styles.docMeta}>
                    {doc.doc_type_label}{countLabel ? ` · ${countLabel}` : ''}
                  </span>
                  {source && (
                    <DocumentPreviewButton
                      documentId={source.document_id}
                      name={doc.filename}
                      fileExt={source.file_ext}
                      status={source.status}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
