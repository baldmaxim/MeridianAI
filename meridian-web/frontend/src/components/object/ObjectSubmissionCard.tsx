import type { FC } from 'react';
import type { DocumentRecord, IOfferSubmission } from '../../types';
import { Collapse } from '../common/Collapse';
import { Icon } from '../common/Icon';
import { cx } from '../../utils/cx';
import { ObjectDocumentRow } from './ObjectDocumentRow';
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

const pluralFiles = (n: number): string => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} файл`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} файла`;
  return `${n} файлов`;
};

/** Одна подача КП: заголовок (название, дата, число файлов) и раскрывающийся список файлов. */
export const ObjectSubmissionCard: FC<IObjectSubmissionCardProps> = ({ submission, docs, open, onToggle }) => {
  const date = formatDate(submission.date);
  return (
    <div className={styles.group}>
      <button type="button" className={styles.groupHead} onClick={onToggle} aria-expanded={open}>
        <Icon name="chevron-right" size={16} className={cx(styles.chevron, open && styles.chevronOpen)} />
        <span className={styles.groupTitle}>{submission.label}</span>
        <span className={styles.groupDate}>{date ? `${date} · ${pluralFiles(docs.length)}` : pluralFiles(docs.length)}</span>
      </button>
      <Collapse open={open} className={styles.groupBody}>
        {docs.map((d) => (
          <ObjectDocumentRow
            key={d.id}
            doc={d}
          />
        ))}
      </Collapse>
    </div>
  );
};
