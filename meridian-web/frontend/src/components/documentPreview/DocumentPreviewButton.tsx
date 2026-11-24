import { lazy, Suspense, useState } from 'react';
import type { FC } from 'react';
import { getPreviewKind } from '../../lib/documentPreview';
import type { DocumentStatus } from '../../types';
import { cx } from '../../utils/cx';
import styles from './DocumentPreviewButton.module.css';

// Модал и все вьюеры (pdfjs/docx/xlsx) — отдельными чанками, в основной бандл не попадают
const DocumentPreviewModal = lazy(() =>
  import('./DocumentPreviewModal').then((m) => ({ default: m.DocumentPreviewModal })),
);

interface IDocumentPreviewButtonProps {
  documentId: number;
  /** Имя в шапке окна просмотра. */
  name: string;
  fileExt: string | null | undefined;
  fileSize?: number | null;
  status: DocumentStatus;
  className?: string;
}

/** Кнопка «Открыть» + окно предпросмотра. Нет формата или файл ещё не загружен (pending) — не рисуется. */
export const DocumentPreviewButton: FC<IDocumentPreviewButtonProps> = ({
  documentId, name, fileExt, fileSize, status, className,
}) => {
  const [mounted, setMounted] = useState(false); // чанк тянем только после первого клика
  const [open, setOpen] = useState(false);

  if (getPreviewKind(fileExt) == null || status === 'pending') return null;

  return (
    <>
      <button
        type="button"
        className={cx(styles.openBtn, className)}
        onClick={() => { setMounted(true); setOpen(true); }}
        aria-label={`Открыть ${name}`}
      >
        Открыть
      </button>
      {mounted && (
        <Suspense fallback={null}>
          <DocumentPreviewModal
            documentId={documentId}
            name={name}
            fileExt={fileExt ?? null}
            fileSize={fileSize}
            open={open}
            onClose={() => setOpen(false)}
          />
        </Suspense>
      )}
    </>
  );
};
