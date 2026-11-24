import { useCallback, useEffect, useState } from 'react';
import type { FC } from 'react';
import { getDocumentDownloadUrl } from '../../api/documents';
import { fetchBlob } from '../../api/download';
import { apiErrorMessage } from '../../lib/apiError';
import { getPreviewKind, isTooLargeForPreview, PREVIEW_MAX_BYTES } from '../../lib/documentPreview';
import { Icon } from '../common/Icon';
import { Modal } from '../common/Modal';
import { DocxViewer } from './DocxViewer';
import { PdfViewer } from './PdfViewer';
import { SheetViewer } from './SheetViewer';
import { TextViewer } from './TextViewer';
import viewer from './Viewer.module.css';
import styles from './DocumentPreviewModal.module.css';

export interface IDocumentPreviewModalProps {
  documentId: number;
  name: string;
  fileExt: string | null;
  fileSize?: number | null;
  open: boolean;
  onClose: () => void;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; data: ArrayBuffer }
  | { status: 'error'; message: string }
  | { status: 'tooLarge' }
  | { status: 'empty' };

interface IBodyProps {
  documentId: number;
  fileExt: string | null;
  fileSize?: number | null;
  onDownload: () => void;
}

/** Тело: загрузка байтов по свежей presigned-ссылке (URL не логируем и не храним) и нужный вьюер. */
const PreviewBody: FC<IBodyProps> = ({ documentId, fileExt, fileSize, onDownload }) => {
  const kind = getPreviewKind(fileExt);
  const [state, setState] = useState<LoadState>(
    isTooLargeForPreview(fileSize) ? { status: 'tooLarge' } : { status: 'loading' },
  );
  // ошибка вьюера (битый файл) подменяет содержимое сообщением
  const [viewerError, setViewerError] = useState('');
  const onViewerError = useCallback((message: string) => setViewerError(message), []);

  useEffect(() => {
    if (isTooLargeForPreview(fileSize)) return undefined;
    let cancelled = false;
    (async () => {
      const url = await getDocumentDownloadUrl(documentId);
      const blob = await fetchBlob(url);
      if (cancelled) return;
      if (blob.size === 0) setState({ status: 'empty' });
      else if (blob.size > PREVIEW_MAX_BYTES) setState({ status: 'tooLarge' });
      else setState({ status: 'ready', data: await blob.arrayBuffer() });
    })().catch((e: unknown) => {
      if (!cancelled) setState({ status: 'error', message: apiErrorMessage(e, 'Не удалось загрузить файл') });
    });
    return () => { cancelled = true; };
  }, [documentId, fileSize]);

  const message = (text: string, isError = false) => (
    <div className={`${viewer.centerMsg} ${isError ? viewer.centerMsgError : ''}`.trim()} role={isError ? 'alert' : undefined}>
      <div>{text}</div>
      <button type="button" className={styles.btn} onClick={onDownload}>Скачать</button>
    </div>
  );

  if (state.status === 'loading') {
    return <div className={viewer.centerMsg} role="status">Загрузка…</div>;
  }
  if (state.status === 'tooLarge') return message('Файл слишком большой для просмотра');
  if (state.status === 'empty') return message('Файл пуст');
  if (state.status === 'error') return message(state.message, true);
  if (viewerError) return message(viewerError, true);

  switch (kind) {
    case 'pdf': return <PdfViewer data={state.data} onError={onViewerError} />;
    case 'docx': return <DocxViewer data={state.data} onError={onViewerError} />;
    case 'xlsx': return <SheetViewer data={state.data} kind="xlsx" onError={onViewerError} />;
    case 'csv': return <SheetViewer data={state.data} kind="csv" onError={onViewerError} />;
    case 'text': return <TextViewer data={state.data} />;
    default: return message('Просмотр этого формата недоступен');
  }
};

export const DocumentPreviewModal: FC<IDocumentPreviewModalProps> = ({
  documentId, name, fileExt, fileSize, open, onClose,
}) => {
  // Монтируем закрытым и открываем следующим тиком — иначе модал, пришедший из lazy-чанка, без анимации входа
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setReady(true), 0);
    return () => clearTimeout(t);
  }, []);

  const [downloadError, setDownloadError] = useState('');
  const download = useCallback(async () => {
    setDownloadError('');
    try {
      const url = await getDocumentDownloadUrl(documentId);
      // Content-Disposition: attachment — скачивание без ухода со страницы
      window.location.assign(url);
    } catch (e) {
      setDownloadError(apiErrorMessage(e, 'Не удалось получить ссылку на файл'));
    }
  }, [documentId]);

  return (
    <Modal open={open && ready} onClose={onClose} wide>
      <div className={styles.header}>
        <div className={styles.title} title={name}>{name}</div>
        <button type="button" className={styles.btn} onClick={() => { void download(); }}>Скачать</button>
        <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Закрыть просмотр">
          <Icon name="close" size={20} />
        </button>
      </div>
      {downloadError && <div className={styles.dlError} role="alert">{downloadError}</div>}
      <div className={styles.body}>
        <PreviewBody
          documentId={documentId}
          fileExt={fileExt}
          fileSize={fileSize}
          onDownload={() => { void download(); }}
        />
      </div>
    </Modal>
  );
};
