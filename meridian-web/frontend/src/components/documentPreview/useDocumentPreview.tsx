import { lazy, Suspense, useState } from 'react';
import type { ReactNode } from 'react';
import { getPreviewKind } from '../../lib/documentPreview';
import type { DocumentStatus } from '../../types';

// Модал и все вьюеры (pdfjs/docx/xlsx) — отдельными чанками, в основной бандл не попадают
const DocumentPreviewModal = lazy(() =>
  import('./DocumentPreviewModal').then((m) => ({ default: m.DocumentPreviewModal })),
);

export interface IDocumentPreviewProps {
  documentId: number;
  /** Имя в шапке окна просмотра. */
  name: string;
  fileExt: string | null | undefined;
  fileSize?: number | null;
  status: DocumentStatus;
}

interface IDocumentPreviewState {
  /** Формат поддерживается и файл уже загружен (не pending). */
  canPreview: boolean;
  openPreview: () => void;
  /** Окно предпросмотра — отрисовать рядом с триггером. */
  modal: ReactNode;
}

/** Окно предпросмотра с любым триггером (кнопка, строка списка). */
export const useDocumentPreview = ({
  documentId, name, fileExt, fileSize, status,
}: IDocumentPreviewProps): IDocumentPreviewState => {
  const [mounted, setMounted] = useState(false); // чанк тянем только после первого открытия
  const [open, setOpen] = useState(false);

  const canPreview = getPreviewKind(fileExt) != null && status !== 'pending';
  const modal = canPreview && mounted ? (
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
  ) : null;

  return { canPreview, openPreview: () => { setMounted(true); setOpen(true); }, modal };
};
