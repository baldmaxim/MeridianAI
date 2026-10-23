import type { FC } from 'react';
import styles from './DocumentList.module.css';

interface IDocumentIconProps {
  ext: string;
  /** Тип из автоклассификации: если известен — иконка по типу, иначе по расширению. */
  docType?: string | null;
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

const DOC_TYPE_GLYPH: Record<string, string> = {
  letter: '✉',
  offer: '💼',
  contract: '📑',
  supplement: '➕',
  bor: '📋',
  estimate: '🧮',
  specification: '📐',
  act: '✅',
  protocol: '🗒',
  other: '📄',
};

export const DocumentIcon: FC<IDocumentIconProps> = ({ ext, docType }) => {
  const glyph = docType ? DOC_TYPE_GLYPH[docType] : undefined;
  if (glyph) {
    return <div className={`${styles.icon} ${styles.iconType}`} aria-hidden>{glyph}</div>;
  }
  return (
    <div className={`${styles.icon} ${DOC_ICON_CLASS[getDocKind(ext)]}`}>
      {ext.toUpperCase()}
    </div>
  );
};
