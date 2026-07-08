import { theme } from '../../styles/theme';

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
      nodes.push(<strong key={k++} style={{ color: theme.text.primary, fontWeight: 700 }}>{m[1]}</strong>);
    } else {
      nodes.push(<code key={k++} style={styles.code}>{m[2]}</code>);
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
        <div key={key++} style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>{header.map((h, j) => <th key={j} style={styles.th}>{inline(h)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci} style={styles.td}>{inline(c)}</td>)}</tr>
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
      blocks.push(<div key={key++} style={lvl <= 2 ? styles.h2 : styles.h3}>{inline(h[2])}</div>);
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
        <ul key={key++} style={styles.ul}>
          {items.map((it, ii) => <li key={ii} style={styles.li}>{inline(it)}</li>)}
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
    blocks.push(<p key={key++} style={styles.p}>{inline(para.join(' '))}</p>);
  }

  return <div style={styles.doc}>{blocks}</div>;
}

const styles: Record<string, React.CSSProperties> = {
  doc: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontFamily: theme.font.body,
    color: theme.text.primary,
  },
  h2: {
    fontFamily: theme.font.heading,
    fontSize: 15,
    fontWeight: 800,
    color: theme.accent.amber,
    letterSpacing: '0.02em',
    marginTop: 12,
    paddingBottom: 4,
    borderBottom: `1px solid ${theme.border.amber}`,
  },
  h3: {
    fontFamily: theme.font.body,
    fontSize: 13,
    fontWeight: 700,
    color: theme.text.primary,
    marginTop: 8,
  },
  p: {
    fontSize: 13,
    lineHeight: 1.65,
    color: theme.text.secondary,
    margin: 0,
  },
  ul: {
    margin: '2px 0',
    paddingLeft: 18,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  li: {
    fontSize: 13,
    lineHeight: 1.55,
    color: theme.text.secondary,
  },
  tableWrap: {
    overflowX: 'auto',
    margin: '6px 0',
  },
  table: {
    borderCollapse: 'collapse',
    width: '100%',
    fontSize: 12.5,
  },
  th: {
    textAlign: 'left',
    padding: '7px 10px',
    background: theme.bg.elevated,
    color: theme.text.primary,
    fontWeight: 700,
    border: `1px solid ${theme.border.default}`,
    whiteSpace: 'nowrap',
  },
  td: {
    padding: '7px 10px',
    color: theme.text.secondary,
    border: `1px solid ${theme.border.default}`,
    verticalAlign: 'top',
  },
  code: {
    fontFamily: theme.font.mono,
    fontSize: 12,
    background: theme.bg.tertiary,
    padding: '1px 5px',
    borderRadius: 4,
    color: theme.accent.amber,
  },
};
