// Ленивая загрузка pdf.js (legacy-сборка — ради старых iOS Safari) и воркера.
// Воркер собирается Vite как отдельный чанк (?worker), CSP прода: worker-src 'self' blob:.
type PdfjsModule = typeof import('pdfjs-dist/legacy/build/pdf.mjs');

let pdfjsPromise: Promise<PdfjsModule> | null = null;

export const loadPdfjs = (): Promise<PdfjsModule> => {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const [lib, worker] = await Promise.all([
        import('pdfjs-dist/legacy/build/pdf.mjs'),
        import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?worker'),
      ]);
      lib.GlobalWorkerOptions.workerPort = new worker.default();
      return lib;
    })();
    // при сбое загрузки чанка даём повторить попытку при следующем открытии
    pdfjsPromise.catch(() => { pdfjsPromise = null; });
  }
  return pdfjsPromise;
};

/** Ассеты pdf.js на своём origin (копируются scripts/copy-pdfjs-assets.mjs в public/pdfjs/). */
export const PDFJS_ASSETS = {
  cMapUrl: '/pdfjs/cmaps/',
  cMapPacked: true,
  standardFontDataUrl: '/pdfjs/standard_fonts/',
  wasmUrl: '/pdfjs/wasm/',
} as const;
