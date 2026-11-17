import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown } from './protocolMarkdown';

describe('parseMarkdown', () => {
  it('заголовок, список, таблица, абзац', () => {
    const blocks = parseMarkdown('## Итоги\n- а\n- б\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\nТекст');
    expect(blocks.map((b) => b.type)).toEqual(['heading', 'ul', 'table', 'p']);
    expect(blocks[2]).toEqual({ type: 'table', header: ['x', 'y'], rows: [['1', '2']] });
  });

  it('«1. … 2. …» одной строкой делится на пункты', () => {
    const [b] = parseMarkdown('1. А (01:00). 2. Б (02:00).');
    expect(b).toEqual({ type: 'ol', start: 1, items: ['А (01:00).', 'Б (02:00).'] });
  });
});

describe('parseInline', () => {
  it('жирный и код', () => {
    expect(parseInline('a **b** `c`')).toEqual([
      { type: 'text', text: 'a ' },
      { type: 'strong', text: 'b' },
      { type: 'text', text: ' ' },
      { type: 'code', text: 'c' },
    ]);
  });
});
