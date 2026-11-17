import styles from './MarkdownView.module.css';
import { cx } from '../../utils/cx';
import { parseInline, parseMarkdown } from '../../lib/protocolMarkdown';

/** Инлайн-разметка: **жирный** и `код`. */
function inline(text: string): React.ReactNode {
  return parseInline(text).map((n, k) => {
    if (n.type === 'strong') return <strong key={k} className={styles.strong}>{n.text}</strong>;
    if (n.type === 'code') return <code key={k} className={styles.code}>{n.text}</code>;
    return n.text;
  });
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
            {b.items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it)}</li>)}
          </ul>
        );
      case 'ol':
        return (
          <ol key={key} start={b.start} className={styles.ul}>
            {b.items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it)}</li>)}
          </ol>
        );
      case 'p':
        return <p key={key} className={styles.p}>{inline(b.text)}</p>;
    }
  });

  return <div className={styles.doc}>{blocks}</div>;
}
