import styles from './MarkdownView.module.css';
import { cx } from '../../utils/cx';
import { parseInline, parseMarkdown } from '../../lib/protocolMarkdown';
import type { MdInline } from '../../lib/protocolMarkdown';

/** Узлы инлайн-разметки → React (strong может содержать mark/timecode). */
function renderNodes(nodes: MdInline[]): React.ReactNode {
  return nodes.map((n, k) => {
    if (n.type === 'strong') {
      return <strong key={k} className={styles.strong}>{n.children ? renderNodes(n.children) : n.text}</strong>;
    }
    if (n.type === 'code') return <code key={k} className={styles.code}>{n.text}</code>;
    if (n.type === 'mark') return <mark key={k} className={styles.mark}>{n.text}</mark>;
    if (n.type === 'timecode') return <span key={k} className={styles.timecode}>{n.text}</span>;
    return n.text;
  });
}

/** Инлайн-разметка: **жирный** и `код`; в «Кратком резюме» (summary) — ещё маркер чисел и чип таймкода. */
function inline(text: string, summary = false): React.ReactNode {
  return renderNodes(parseInline(text, { highlight: summary }));
}

/** Лёгкий рендер Markdown протокола: заголовки, списки, таблицы, жирный, абзацы. */
export function MarkdownView({ md }: { md: string }) {
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
                  <tr key={ri}>{r.map((c, ci) => <td key={ci} className={styles.td}>{inline(c)}</td>)}</tr>
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
            {b.items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it, b.summary)}</li>)}
          </ul>
        );
      case 'ol':
        return (
          <ol key={key} start={b.start} className={styles.ul}>
            {b.items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it, b.summary)}</li>)}
          </ol>
        );
      case 'p':
        return <p key={key} className={styles.p}>{inline(b.text, b.summary)}</p>;
    }
  });

  return <div className={styles.doc}>{blocks}</div>;
}
