import type { FC } from 'react';
import styles from './DocumentList.module.css';

interface IDocumentIconProps {
  ext: string;
}

type DocKind = 'pdf' | 'md' | 'other';

const getDocKind = (ext: string): DocKind => {
  switch (ext.toUpperCase()) {
    case 'PDF': return 'pdf';
    case 'MD': return 'md';
    default: return 'other';
  }
};

const DOC_ICON_CLASS: Record<DocKind, string> = {
  pdf: styles.iconPdf,
  md: styles.iconMd,
  other: styles.iconOther,
};

export const DocumentIcon: FC<IDocumentIconProps> = ({ ext }) => (
  <div className={`${styles.icon} ${DOC_ICON_CLASS[getDocKind(ext)]}`}>
    {ext.toUpperCase()}
  </div>
);
