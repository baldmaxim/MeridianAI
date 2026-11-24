import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import viewer from './Viewer.module.css';
import styles from './DocxViewer.module.css';

interface IDocxViewerProps {
  data: ArrayBuffer;
  onError: (message: string) => void;
}

/** .docx через docx-preview: страницы как в Word, вписываются в ширину экрана через CSS zoom. */
export const DocxViewer: FC<IDocxViewerProps> = ({ data, onError }) => {
  const hostRef = useRef<HTMLDivElement>(null);
  const renderRef = useRef<HTMLDivElement>(null);
  const [pageWidth, setPageWidth] = useState(0); // естественная ширина самой широкой страницы, px
  const [hostWidth, setHostWidth] = useState(0);

  useEffect(() => {
    const target = renderRef.current;
    if (!target) return undefined;
    let cancelled = false;
    (async () => {
      const { renderAsync } = await import('docx-preview');
      if (cancelled) return;
      await renderAsync(data, target, undefined, {
        inWrapper: true,
        ignoreFonts: true,
        useBase64URL: true,
        breakPages: true,
        renderHeaders: true,
        renderFooters: true,
      });
      if (cancelled) return;
      // измеряем до применения zoom (он ещё 1) — иначе offsetWidth зависит от масштаба
      const widths = Array.from(target.querySelectorAll<HTMLElement>('section'), (el) => el.offsetWidth);
      setPageWidth(Math.max(0, ...widths));
    })().catch(() => {
      if (!cancelled) onError('Не удалось открыть документ Word');
    });
    return () => {
      cancelled = true;
      setPageWidth(0);
      target.replaceChildren();
    };
  }, [data, onError]);

  // ширина контейнера (пересчёт при повороте/ресайзе)
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const ro = new ResizeObserver(([entry]) => setHostWidth(entry.contentRect.width));
    ro.observe(host);
    return () => ro.disconnect();
  }, []);

  // вписать страницу в ширину контейнера (только уменьшаем)
  const zoom = pageWidth > 0 && hostWidth > 0 ? Math.min(1, hostWidth / pageWidth) : 1;

  return (
    <div ref={hostRef} className={`${viewer.scroll} ${styles.host}`}>
      <div className={styles.zoomBox} style={{ zoom }}>
        <div ref={renderRef} />
      </div>
    </div>
  );
};
