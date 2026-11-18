import type { FC } from 'react';
import type { DocumentRecord, IOfferSubmission } from '../../types';
import { ObjectSubmissionCard } from './ObjectSubmissionCard';
import styles from './ObjectDocuments.module.css';

export interface IObjectSubmissionItem {
  submission: IOfferSubmission;
  docs: DocumentRecord[];
}

interface IObjectSubmissionsProps {
  /** Подачи в порядке от новой к старой; только те, где есть что показать. */
  items: IObjectSubmissionItem[];
  isOpen: (key: string) => boolean;
  onToggle: (key: string) => void;
}

/** Секция «Подачи КП»: каждая подача — единым пакетом файлов. Пустая секция не рисуется. */
export const ObjectSubmissions: FC<IObjectSubmissionsProps> = ({ items, isOpen, onToggle }) => {
  if (items.length === 0) return null;
  const total = items.reduce((n, i) => n + i.docs.length, 0);
  return (
    <div className={styles.subsection}>
      <div className={styles.subTitle}>Подачи КП ({total})</div>
      <div className={styles.groups}>
        {items.map(({ submission, docs }) => (
          <ObjectSubmissionCard
            key={submission.key}
            submission={submission}
            docs={docs}
            open={isOpen(submission.key)}
            onToggle={() => onToggle(submission.key)}
          />
        ))}
      </div>
    </div>
  );
};
