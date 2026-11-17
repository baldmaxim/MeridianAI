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

describe('«Краткое резюме»', () => {
  const SUMMARY = '1. Цена 150 000 руб./м² при 30% аванса (24:50–25:41).';

  it('блоки раздела получают summary до следующего заголовка', () => {
    const blocks = parseMarkdown(`## 2. Участники\n- а\n\n## 3. КРАТКОЕ РЕЗЮМЕ\n${SUMMARY}\n\n## 4. Вопросы\n- б`);
    expect(blocks.map((b) => ('summary' in b ? b.summary : undefined))).toEqual([undefined, undefined, undefined, true, undefined, undefined]);
  });

  it('highlight: mark для сумм и процентов, таймкод — timecode, а не mark', () => {
    const nodes = parseInline(SUMMARY.replace(/^1\.\s+/, ''), { highlight: true });
    const marks = nodes.filter((n) => n.type === 'mark').map((n) => n.text);
    expect(marks).toEqual(['150 000 руб./м²', '30%']);
    expect(nodes.filter((n) => n.type === 'timecode').map((n) => n.text)).toEqual(['(24:50–25:41)']);
  });

  it('без highlight mark и timecode нет', () => {
    const nodes = parseInline('Цена 150 000 руб./м² (24:50–25:41)');
    expect(nodes).toEqual([{ type: 'text', text: 'Цена 150 000 руб./м² (24:50–25:41)' }]);
  });

  it('сроки, диапазоны, даты, количества', () => {
    const marks = (t: string) => parseInline(t, { highlight: true }).filter((n) => n.type === 'mark').map((n) => n.text);
    expect(marks('с 47 до примерно 35 месяцев')).toEqual(['47', '35 месяцев']);
    expect(marks('(18% против целевых 8–10%)')).toEqual(['18%', '8–10%']);
    expect(marks('армирования (175 против 155)')).toEqual(['175', '155']);
    expect(marks('не выше 116–117 тыс. руб. (31:33–31:57).')).toEqual(['116–117 тыс. руб.']);
    expect(marks('12 октября и январь–февраль, 5 млн ₸, 12 недель')).toEqual(['12 октября', 'январь–февраль', '5 млн ₸', '12 недель']);
    expect(marks('Спикер 1 и пункт 5')).toEqual([]);
  });

  it('жирный: strong с вложенным mark, без поломки разметки', () => {
    const [n] = parseInline('**цена 30%**', { highlight: true });
    expect(n).toEqual({
      type: 'strong',
      text: 'цена 30%',
      children: [{ type: 'text', text: 'цена ' }, { type: 'mark', text: '30%' }],
    });
    expect(parseInline('**суть**', { highlight: true })).toEqual([{ type: 'strong', text: 'суть' }]);
  });
});
