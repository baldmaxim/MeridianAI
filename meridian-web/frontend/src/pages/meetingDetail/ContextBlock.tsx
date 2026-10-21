import type { FC } from 'react';
import type { MeetingDetail } from '../../types';
import { NEGOTIATION_TYPE_LABELS, getDocTone } from './meetingDetailFormat';
import styles from './ContextBlock.module.css';

interface IContextBlockProps {
  meeting: MeetingDetail;
}

export const ContextBlock: FC<IContextBlockProps> = ({ meeting }) => {
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
              return (
                <div key={doc.filename} className={styles.doc}>
                  <span className={`${styles.docExt} ${styles[getDocTone(ext)]}`}>
                    {ext.toUpperCase()}
                  </span>
                  <span className={styles.docName}>{doc.filename}</span>
                  <span className={styles.docMeta}>
                    {doc.doc_type_label}{countLabel ? ` · ${countLabel}` : ''}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
