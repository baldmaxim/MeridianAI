import { useMemo } from 'react';
import type { FC } from 'react';
import { decodeText } from '../../lib/documentPreview';
import viewer from './Viewer.module.css';
import styles from './TextViewer.module.css';

interface ITextViewerProps {
  data: ArrayBuffer;
}

/** .txt / .md — как есть, без разметки (никакого HTML из содержимого). */
export const TextViewer: FC<ITextViewerProps> = ({ data }) => {
  const text = useMemo(() => decodeText(data), [data]);
  return (
    <div className={viewer.scroll}>
      <pre className={styles.text}>{text}</pre>
    </div>
  );
};
