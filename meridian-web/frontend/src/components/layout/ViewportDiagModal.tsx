import { useCallback, useEffect, useState } from 'react';
import type { FC } from 'react';
import { Modal } from '../common/Modal';
import styles from './ViewportDiagModal.module.css';

interface IViewportDiagModalProps {
  open: boolean;
  onClose: () => void;
}

type DiagRow = [key: string, value: string] | [section: string];

const fmt = (n: number): string => String(Math.round(n * 100) / 100);

const rectOf = (el: Element | null): string => {
  if (!el) return 'нет';
  const r = el.getBoundingClientRect();
  return `top ${fmt(r.top)} / h ${fmt(r.height)} / bottom ${fmt(r.bottom)}`;
};

/** Высота невидимой пробы с заданным CSS-набором. */
const probeHeight = (css: string): string => {
  const el = document.createElement('div');
  el.style.cssText = `position:fixed;visibility:hidden;width:1px;pointer-events:none;${css}`;
  document.body.appendChild(el);
  const h = el.getBoundingClientRect().height;
  el.remove();
  return fmt(h);
};

/** Значения env(safe-area-inset-*) через пробу с padding. */
const safeAreaInsets = (): string => {
  const el = document.createElement('div');
  el.style.cssText =
    'position:fixed;visibility:hidden;width:1px;pointer-events:none;top:0;left:0;' +
    'padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);';
  document.body.appendChild(el);
  const cs = getComputedStyle(el);
  const res = `T ${cs.paddingTop} R ${cs.paddingRight} B ${cs.paddingBottom} L ${cs.paddingLeft}`;
  el.remove();
  return res;
};

const metaContent = (selector: string): string =>
  document.querySelector(selector)?.getAttribute('content') ?? 'нет';

const collect = (): DiagRow[] => {
  const vv = window.visualViewport;
  const root = document.getElementById('root');
  return [
    ['Окно / экран'],
    ['innerHeight', fmt(window.innerHeight)],
    ['outerHeight', fmt(window.outerHeight)],
    ['screen.height', fmt(window.screen.height)],
    ['screen.availHeight', fmt(window.screen.availHeight)],
    ['devicePixelRatio', fmt(window.devicePixelRatio)],
    ['visualViewport.height', vv ? fmt(vv.height) : 'нет'],
    ['visualViewport.offsetTop', vv ? fmt(vv.offsetTop) : 'нет'],
    ['visualViewport.pageTop', vv ? fmt(vv.pageTop) : 'нет'],
    ['Элементы'],
    ['documentElement.clientHeight', fmt(document.documentElement.clientHeight)],
    ['body.clientHeight', fmt(document.body.clientHeight)],
    ['#root height', root ? fmt(root.getBoundingClientRect().height) : 'нет'],
    ['app-container', rectOf(document.querySelector('[data-diag="app-container"]'))],
    ['.mobile-nav', rectOf(document.querySelector('.mobile-nav'))],
    ['header', rectOf(document.querySelector('header'))],
    ['Пробы высоты (fixed)'],
    ['100vh', probeHeight('height:100vh')],
    ['100svh', probeHeight('height:100svh')],
    ['100lvh', probeHeight('height:100lvh')],
    ['100dvh', probeHeight('height:100dvh')],
    ['100%', probeHeight('height:100%')],
    ['top:0; bottom:0', probeHeight('top:0;bottom:0')],
    ['safe-area-inset'],
    ['env()', safeAreaInsets()],
    ['Режим'],
    ['display-mode: standalone', String(window.matchMedia('(display-mode: standalone)').matches)],
    [
      'navigator.standalone',
      'standalone' in navigator ? String((navigator as Navigator & { standalone?: boolean }).standalone) : 'нет',
    ],
    ['userAgent', navigator.userAgent.slice(0, 120)],
    ['meta status-bar-style', metaContent('meta[name="apple-mobile-web-app-status-bar-style"]')],
    ['meta viewport', metaContent('meta[name="viewport"]')],
  ];
};

const toText = (rows: DiagRow[]): string =>
  rows.map((r) => (r.length === 1 ? `\n[${r[0]}]` : `${r[0]}: ${r[1]}`)).join('\n').trim();

/** ВРЕМЕННАЯ модалка диагностики размеров вьюпорта (пустая полоса снизу на iPhone). */
export const ViewportDiagModal: FC<IViewportDiagModalProps> = ({ open, onClose }) => {
  const [rows, setRows] = useState<DiagRow[]>([]);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(() => setRows(collect()), []);

  useEffect(() => {
    if (!open) return;
    // первый замер — после отрисовки модалки (не синхронно в эффекте)
    const raf = window.requestAnimationFrame(refresh);
    const vv = window.visualViewport;
    window.addEventListener('resize', refresh);
    window.addEventListener('orientationchange', refresh);
    vv?.addEventListener('resize', refresh);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', refresh);
      window.removeEventListener('orientationchange', refresh);
      vv?.removeEventListener('resize', refresh);
    };
  }, [open, refresh]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toText(rows));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} maxWidth={520}>
      <h2 className={styles.title}>Диагностика экрана</h2>
      <div className={styles.table}>
        {rows.map((r) =>
          r.length === 1 ? (
            <div key={r[0]} className={styles.section}>{r[0]}</div>
          ) : (
            <div key={r[0]} className={styles.pair}>
              <div className={styles.key}>{r[0]}</div>
              <div className={styles.val}>{r[1]}</div>
            </div>
          ),
        )}
      </div>
      <div className={styles.actions}>
        <button type="button" className={styles.btn} onClick={refresh}>Обновить</button>
        <button type="button" className={styles.btn} onClick={copy}>{copied ? 'Скопировано' : 'Скопировать'}</button>
        <button type="button" className={styles.btn} onClick={onClose}>Закрыть</button>
      </div>
    </Modal>
  );
};
