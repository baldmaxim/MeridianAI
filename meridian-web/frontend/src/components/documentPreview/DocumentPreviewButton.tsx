import type { FC } from 'react';
import { cx } from '../../utils/cx';
import styles from './DocumentPreviewButton.module.css';
import { useDocumentPreview } from './useDocumentPreview';
import type { IDocumentPreviewProps } from './useDocumentPreview';

interface IDocumentPreviewButtonProps extends IDocumentPreviewProps {
  className?: string;
}

/** Кнопка «Открыть» + окно предпросмотра. Нет формата или файл ещё не загружен (pending) — не рисуется. */
export const DocumentPreviewButton: FC<IDocumentPreviewButtonProps> = ({ className, ...props }) => {
  const { canPreview, openPreview, modal } = useDocumentPreview(props);
  if (!canPreview) return null;

  return (
    <>
      <button
        type="button"
        className={cx(styles.openBtn, className)}
        onClick={openPreview}
        aria-label={`Открыть ${props.name}`}
      >
        Открыть
      </button>
      {modal}
    </>
  );
};
