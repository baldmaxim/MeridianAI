import styles from './MarkdownView.module.css';
import { cx } from '../../utils/cx';
import { parseInline, parseMarkdown, splitTimecodes } from '../../lib/protocolMarkdown';
import type { MdInline } from '../../lib/protocolMarkdown';
import { parseHighlighted } from './protocolHighlight';

interface IRenderCtx {
  onTimecode?: (seconds: number) => void;
  /** Раздел «Краткое резюме»: таймкод — приглушённый чип. */
  summary: boolean;
}

/** Таймкод → кликабельные кнопки (диапазон — каждое время отдельно); текст между ними остаётся. */
function timecodeButtons(text: string, onTimecode: (seconds: number) => void): React.ReactNode {
  return splitTimecodes(text).map((p, k) =>
    p.seconds == null ? (
      p.text
    ) : (
      <button
        key={k}
        type="button"
        className={styles.tcBtn}
        aria-label={`Перейти к ${p.text}`}
        onClick={() => onTimecode(p.seconds as number)}
      >
        {p.text}
      </button>
    )
  );
}

/** Узлы инлайн-разметки → React (strong может содержать mark/timecode). */
function renderNodes(nodes: MdInline[], ctx: IRenderCtx): React.ReactNode {
  return nodes.map((n, k) => {
    if (n.type === 'strong') {
      return <strong key={k} className={styles.strong}>{n.children ? renderNodes(n.children, ctx) : n.text}</strong>;
    }
    if (n.type === 'code') return <code key={k} className={styles.code}>{n.text}</code>;
    if (n.type === 'mark') return <mark key={k} className={styles.mark}>{n.text}</mark>;
    if (n.type === 'timecode') {
      const { onTimecode, summary } = ctx;
      if (!onTimecode) return <span key={k} className={styles.timecode}>{n.text}</span>;
      // в резюме — чип (внутри кнопки), вне резюме — просто кнопка-ссылка
      return summary
        ? <span key={k} className={cx(styles.timecode, styles.timecodeActive)}>{timecodeButtons(n.text, onTimecode)}</span>
        : <span key={k}>{timecodeButtons(n.text, onTimecode)}</span>;
    }
    return n.text;
  });
}

interface IMarkdownViewProps {
  md: string;
  onTimecode?: (seconds: number) => void;
  /** Выделять числа, суммы, %, сроки и даты во всём тексте, а не только в «Кратком резюме» (протокол встречи). */
  highlight?: boolean;
}

/**
 * Лёгкий рендер Markdown протокола: заголовки, списки, таблицы, жирный, абзацы.
 * onTimecode — если задан, таймкоды во всём протоколе кликабельны (перемотка плеера).
 */
export function MarkdownView({ md, onTimecode, highlight = false }: IMarkdownViewProps) {
  /**
   * Инлайн-разметка: **жирный** и `код`; в «Кратком резюме» (summary) — ещё маркер чисел и чип таймкода.
   * accent при highlight — то же выделение вне резюме (абзацы, списки, ячейки таблиц; заголовки таблиц и разделов — без).
   */
  const inline = (text: string, summary = false, accent = false): React.ReactNode => {
    const nodes = highlight && accent
      ? parseHighlighted(text, { timecodes: !!onTimecode })
      : parseInline(text, { highlight: summary, timecodes: !!onTimecode });
    return renderNodes(nodes, { onTimecode, summary });
  };

  const blocks = parseMarkdown(md).map((b, key) => {
    switch (b.type) {
      case 'table':
        return (
          <div key={key} className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>{b.header.map((h, j) => <th key={j} className={styles.th}>{inline(h)}</th>)}</tr>
              </thead>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri}>{r.map((c, ci) => <td key={ci} className={styles.td}>{inline(c, false, true)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case 'heading':
        return <div key={key} className={cx(b.level <= 2 ? styles.h2 : styles.h3)}>{inline(b.text)}</div>;
      case 'ul':
        return (
          <ul key={key} className={styles.ul}>
            {b.items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it, b.summary, true)}</li>)}
          </ul>
        );
      case 'ol':
        return (
          <ol key={key} start={b.start} className={styles.ul}>
            {b.items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it, b.summary, true)}</li>)}
          </ol>
        );
      case 'p':
        return <p key={key} className={styles.p}>{inline(b.text, b.summary, true)}</p>;
    }
  });

  return <div className={styles.doc}>{blocks}</div>;
}
