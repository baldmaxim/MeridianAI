import { useState } from 'react';
import type { FC } from 'react';
import { getDocumentDownloadUrl } from '../../api/documents';
import { apiErrorMessage } from '../../lib/apiError';
import { formatFileSize } from '../../lib/documentFiles';
import { getDocumentDisplayName } from '../../lib/documentName';
import type { DocumentRecord } from '../../types';
import { cx } from '../../utils/cx';
import { DocumentPreviewButton } from '../documentPreview/DocumentPreviewButton';
import styles from './ObjectDocuments.module.css';

const STATUS_LABELS: Record<string, string> = {
  pending: 'ожидает загрузки',
  uploaded: 'загружен',
  processing: 'обрабатывается',
  awaiting_ocr: 'ждёт распознавания',
  error: 'ошибка обработки',
};

interface IObjectDocumentRowProps {
  doc: DocumentRecord;
  /** Имя для показа (например, без префикса подачи КП); по умолчанию — display_name документа. */
  displayName?: string;
}

export const ObjectDocumentRow: FC<IObjectDocumentRowProps> = ({ doc, displayName }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const download = async () => {
    setBusy(true);
    setError('');
    try {
      const url = await getDocumentDownloadUrl(doc.id);
      // Content-Disposition: attachment — скачивание без ухода со страницы и без попап-блокера iOS
      window.location.assign(url);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось получить ссылку на файл'));
    } finally {
      setBusy(false);
    }
  };

  const meta: string[] = [];
  if (doc.file_ext) meta.push(doc.file_ext.replace(/^\./, '').toUpperCase());
  if (doc.file_size != null) meta.push(formatFileSize(doc.file_size));
  if (doc.page_count) meta.push(`${doc.page_count} стр.`);
  if (doc.sheet_count) meta.push(`${doc.sheet_count} л.`);

  return (
    <div className={styles.row}>
      <div className={styles.rowMain}>
        <div className={styles.rowName} title={doc.original_name}>{displayName ?? getDocumentDisplayName(doc)}</div>
        <div className={styles.rowMeta}>
          {meta.length > 0 && <span>{meta.join(' · ')}</span>}
          {doc.status !== 'ready' && (
            <span className={cx(styles.status, doc.status === 'error' && styles.statusError)}>
              {STATUS_LABELS[doc.status] ?? doc.status}
            </span>
          )}
        </div>
        {error && <div className={styles.rowError}>{error}</div>}
      </div>
      <DocumentPreviewButton
        documentId={doc.id}
        name={displayName ?? getDocumentDisplayName(doc)}
        fileExt={doc.file_ext}
        fileSize={doc.file_size}
        status={doc.status}
      />
      <button
        type="button"
        className={cx('t-btn', styles.downloadBtn)}
        onClick={download}
        disabled={busy}
        aria-label={`Скачать ${displayName ?? getDocumentDisplayName(doc)}`}
      >
        {busy ? '…' : 'Скачать'}
      </button>
    </div>
  );
};
