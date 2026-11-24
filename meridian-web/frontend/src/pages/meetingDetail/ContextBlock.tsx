import { useEffect, useState } from 'react';
import type { FC } from 'react';
import { listMeetingDocuments } from '../../api/meetingDocuments';
import { useDocumentPreview } from '../../components/documentPreview/useDocumentPreview';
import type { MeetingDetail, MeetingDocument } from '../../types';
import { NEGOTIATION_TYPE_LABELS, getDocTone } from './meetingDetailFormat';
import styles from './ContextBlock.module.css';

interface IContextBlockProps {
  meeting: MeetingDetail;
}

interface IContextDocRowProps {
  filename: string;
  ext: string;
  meta: string;
  /** Документ встречи с id — без него предпросмотр недоступен. */
  source?: MeetingDocument;
}

const ContextDocRow: FC<IContextDocRowProps> = ({ filename, ext, meta, source }) => {
  const preview = useDocumentPreview({
    documentId: source?.document_id ?? 0,
    name: filename,
    fileExt: source?.file_ext,
    status: source?.status ?? 'pending',
  });
  const canOpen = source != null && preview.canPreview;

  const content = (
    <>
      <span className={`${styles.docExt} ${styles[getDocTone(ext)]}`}>{ext.toUpperCase()}</span>
      <span className={styles.docName}>{filename}</span>
      <span className={styles.docMeta}>{meta}</span>
    </>
  );

  return canOpen ? (
    <>
      <button
        type="button"
        className={`${styles.doc} ${styles.docBtn}`}
        onClick={preview.openPreview}
        aria-label={`Открыть ${filename}`}
      >
        {content}
      </button>
      {preview.modal}
    </>
  ) : (
    <div className={styles.doc}>{content}</div>
  );
};

export const ContextBlock: FC<IContextBlockProps> = ({ meeting }) => {
  // В деталях встречи документы без id — для предпросмотра сопоставляем по имени со списком документов встречи.
  const [attached, setAttached] = useState<MeetingDocument[]>([]);
  useEffect(() => {
    let cancelled = false;
    listMeetingDocuments(meeting.id)
      .then((list) => { if (!cancelled) setAttached(list); })
      .catch(() => { /* список недоступен — просто без предпросмотра */ });
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
                <ContextDocRow
                  key={doc.filename}
                  filename={doc.filename}
                  ext={ext}
                  meta={`${doc.doc_type_label}${countLabel ? ` · ${countLabel}` : ''}`}
                  source={source}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
