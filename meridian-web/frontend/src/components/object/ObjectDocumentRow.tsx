import { useState } from 'react';
import type { FC } from 'react';
import { getDocumentDownloadUrl } from '../../api/documents';
import { apiErrorMessage } from '../../lib/apiError';
import { formatFileSize } from '../../lib/documentFiles';
import { getDocumentDisplayName } from '../../lib/documentName';
import type { DocumentRecord } from '../../types';
import { cx } from '../../utils/cx';
import { Icon } from '../common/Icon';
import { useDocumentPreview } from '../documentPreview/useDocumentPreview';
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
  const name = displayName ?? getDocumentDisplayName(doc);
  const preview = useDocumentPreview({
    documentId: doc.id, name, fileExt: doc.file_ext, fileSize: doc.file_size, status: doc.status,
  });

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

  const info = (
    <>
      <span className={styles.rowName} title={doc.original_name}>{name}</span>
      {meta.length > 0 && <span className={styles.rowMeta}>{meta.join(' · ')}</span>}
      {doc.status !== 'ready' && (
        <span className={cx(styles.rowMeta, styles.status, doc.status === 'error' && styles.statusError)}>
          {STATUS_LABELS[doc.status] ?? doc.status}
        </span>
      )}
    </>
  );

  return (
    <div className={styles.rowWrap}>
      <div className={styles.row}>
        {/* Нажатие по строке открывает предпросмотр; без поддерживаемого формата — просто текст */}
        {preview.canPreview ? (
          <button
            type="button"
            className={cx(styles.rowMain, styles.rowMainBtn)}
            onClick={preview.openPreview}
            aria-label={`Открыть ${name}`}
          >
            {info}
          </button>
        ) : (
          <div className={styles.rowMain}>{info}</div>
        )}
        <button
          type="button"
          className={cx('t-btn', styles.downloadBtn)}
          onClick={download}
          disabled={busy}
          aria-label={`Скачать ${name}`}
          title="Скачать"
        >
          <Icon name="download" size={18} />
        </button>
      </div>
      {error && <div className={styles.rowError}>{error}</div>}
      {preview.modal}
    </div>
  );
};
