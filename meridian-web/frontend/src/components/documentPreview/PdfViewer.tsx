import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { loadPdfjs, PDFJS_ASSETS } from './pdfjsLoader';
import viewer from './Viewer.module.css';
import styles from './PdfViewer.module.css';

/** Потолок площади canvas: iOS Safari не рисует холсты больше ~16 Мпикс. */
const MAX_CANVAS_PIXELS = 16_000_000;
/** Запас прокрутки (в экранах), в пределах которого страницы остаются отрисованными. */
const VISIBLE_MARGIN = '150% 0px';
/** Сколько страниц опрашиваем за раз при чтении размеров. */
const RATIO_BATCH = 20;

interface IPdfPageProps {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  width: number;
  /** Высота/ширина страницы — по ней резервируется место до отрисовки. */
  ratio: number;
  root: HTMLElement;
}

/** Одна страница: рисуется, пока рядом с экраном; вдали холст освобождается (память на iPhone). */
const PdfPage: FC<IPdfPageProps> = ({ pdf, pageNumber, width, ratio, root }) => {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(
      (entries) => setVisible(entries.some((e) => e.isIntersecting)),
      { root, rootMargin: VISIBLE_MARGIN },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [root]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width <= 0) return undefined;
    if (!visible) {
      canvas.width = 0; // освободить память холста, плейсхолдер остаётся прежней высоты
      canvas.height = 0;
      return undefined;
    }
    let cancelled = false;
    let cancelRender: (() => void) | null = null;
    (async () => {
      const page = await pdf.getPage(pageNumber);
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const cssScale = width / base.width;
      let scale = cssScale * (window.devicePixelRatio || 1);
      const area = base.width * base.height * scale * scale;
      if (area > MAX_CANVAS_PIXELS) scale *= Math.sqrt(MAX_CANVAS_PIXELS / area);
      const viewport = page.getViewport({ scale });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      const task = page.render({ canvas, viewport });
      cancelRender = () => task.cancel();
      try {
        await task.promise;
      } catch {
        // RenderingCancelledException при уходе страницы из зоны видимости — штатно
      }
      page.cleanup();
    })().catch(() => { /* страница не отрисовалась — остаётся плейсхолдер */ });
    return () => {
      cancelled = true;
      cancelRender?.();
    };
  }, [pdf, pageNumber, width, visible]);

  return (
    <div ref={wrapRef} className={styles.page} style={{ width, height: Math.round(width * ratio) }}>
      <canvas ref={canvasRef} className={styles.canvas} />
      <span className={styles.pageNum}>{pageNumber}</span>
    </div>
  );
};

interface IPdfViewerProps {
  data: ArrayBuffer;
  onError: (message: string) => void;
}

const errorMessage = (e: unknown): string =>
  e instanceof Error && e.name === 'PasswordException'
    ? 'PDF защищён паролем — откройте скачанный файл'
    : 'Не удалось открыть PDF';

export const PdfViewer: FC<IPdfViewerProps> = ({ data, onError }) => {
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const pagesRef = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  // пропорции всех страниц (страницы договора бывают разного формата); пока не пришли — как у первой
  const [ratios, setRatios] = useState<number[]>([]);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => Promise<void>) | null = null;
    (async () => {
      const pdfjs = await loadPdfjs();
      // pdf.js забирает буфер себе (transfer) — отдаём копию, чтобы исходные данные пережили повторный запуск эффекта
      const task = pdfjs.getDocument({ data: new Uint8Array(data.slice(0)), ...PDFJS_ASSETS });
      destroy = () => task.destroy();
      const doc = await task.promise;
      if (cancelled) return;
      const first = await doc.getPage(1);
      const vp = first.getViewport({ scale: 1 });
      if (cancelled) return;
      setRatios([vp.height / vp.width]);
      setPdf(doc);
      // размеры остальных страниц — фоном пачками, чтобы плейсхолдеры были нужной высоты
      for (let from = 2; from <= doc.numPages && !cancelled; from += RATIO_BATCH) {
        const nums = Array.from({ length: Math.min(RATIO_BATCH, doc.numPages - from + 1) }, (_, i) => from + i);
        const batch = await Promise.all(nums.map(async (n) => {
          const page = await doc.getPage(n);
          const v = page.getViewport({ scale: 1 });
          page.cleanup();
          return v.height / v.width;
        }));
        if (!cancelled) setRatios((prev) => [...prev, ...batch]);
      }
    })().catch((e: unknown) => {
      if (!cancelled) onError(errorMessage(e));
    });
    return () => {
      cancelled = true;
      setPdf(null);
      setRatios([]);
      void destroy?.();
    };
  }, [data, onError]);

  // ширина страницы = ширине контейнера (пересчёт при повороте/ресайзе)
  useEffect(() => {
    const el = pagesRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={setScroller} className={viewer.scroll}>
      <div ref={pagesRef} className={styles.pages}>
        {pdf && scroller && Array.from({ length: pdf.numPages }, (_, i) => (
          <PdfPage
            key={i + 1}
            pdf={pdf}
            pageNumber={i + 1}
            width={width}
            ratio={ratios[i] ?? ratios[0] ?? Math.SQRT2}
            root={scroller}
          />
        ))}
      </div>
    </div>
  );
};
