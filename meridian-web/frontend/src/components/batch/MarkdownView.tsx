import styles from './MarkdownView.module.css';
import { cx } from '../../utils/cx';

/** Инлайн-разметка: **жирный** и `код`. */
function inline(text: string): React.ReactNode {
  const nodes: React.ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let k = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1] != null) {
      nodes.push(<strong key={k++} className={styles.strong}>{m[1]}</strong>);
    } else {
      nodes.push(<code key={k++} className={styles.code}>{m[2]}</code>);
    }
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function splitRow(line: string): string[] {
  return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
}

/** Лёгкий рендер Markdown протокола: заголовки, списки, таблицы, жирный, абзацы. */
export function MarkdownView({ md }: { md: string }) {
  const lines = md.replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Таблица: строка "| … |" + строка-разделитель "|---|---|"
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push(
        <div key={key++} className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>{header.map((h, j) => <th key={j} className={styles.th}>{inline(h)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci} className={styles.td}>{inline(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Заголовок
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const lvl = h[1].length;
      blocks.push(<div key={key++} className={cx(lvl <= 2 ? styles.h2 : styles.h3)}>{inline(h[2])}</div>);
      i++;
      continue;
    }

    // Маркированный список
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''));
        i++;
      }
      blocks.push(
        <ul key={key++} className={styles.ul}>
          {items.map((it, ii) => <li key={ii} className={styles.li}>{inline(it)}</li>)}
        </ul>
      );
      continue;
    }

    // Пустая строка
    if (!line.trim()) { i++; continue; }

    // Абзац
    const para: string[] = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^(#{1,4})\s/.test(lines[i]) && !/^\s*[-*]\s/.test(lines[i]) && !lines[i].trim().startsWith('|')
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={key++} className={styles.p}>{inline(para.join(' '))}</p>);
  }

  return <div className={styles.doc}>{blocks}</div>;
}
