import type { FC } from 'react';
import type { DocumentRecord, IOfferSubmission } from '../../types';
import { Collapse } from '../common/Collapse';
import { cx } from '../../utils/cx';
import { ObjectDocumentRow } from './ObjectDocumentRow';
import { stripOfferPrefix } from './offerSubmissions';
import styles from './ObjectDocuments.module.css';

interface IObjectSubmissionCardProps {
  submission: IOfferSubmission;
  docs: DocumentRecord[];
  open: boolean;
  onToggle: () => void;
}

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})/;

const formatDate = (date: string | null): string => {
  if (!date) return '';
  const m = ISO_DATE_RE.exec(date);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : date;
};

/** Одна подача КП: заголовок (название, дата, число файлов) и раскрывающийся список файлов. */
export const ObjectSubmissionCard: FC<IObjectSubmissionCardProps> = ({ submission, docs, open, onToggle }) => {
  const date = formatDate(submission.date);
  return (
    <div className={styles.group}>
      <button type="button" className={styles.groupHead} onClick={onToggle} aria-expanded={open}>
        <span className={cx(styles.chevron, open && styles.chevronOpen)}>▶</span>
        <span className={styles.groupTitle}>{submission.label}</span>
        {date && <span className={styles.groupDate}>{date}</span>}
        <span className={styles.groupCount}>{docs.length}</span>
      </button>
      <Collapse open={open} className={styles.groupBody}>
        {docs.map((d) => (
          <ObjectDocumentRow
            key={d.id}
            doc={d}
            displayName={stripOfferPrefix(d.original_name, submission.key)}
          />
        ))}
      </Collapse>
    </div>
  );
};
