import { describe, expect, it } from 'vitest';
import { parseHighlighted } from './protocolHighlight';

const marks = (t: string): string[] => parseHighlighted(t).flatMap((n) => {
  if (n.type === 'mark') return [n.text];
  if (n.type === 'strong') return (n.children ?? []).filter((c) => c.type === 'mark').map((c) => c.text);
  return [];
});

describe('parseHighlighted — акценты протокола встречи', () => {
  it('суммы с валютой и множителями', () => {
    expect(marks('Цена 5 млн ₸ и 150 000 руб./м², доплата 12 тыс. $')).toEqual(['5 млн ₸', '150 000 руб./м²', '12 тыс. $']);
    expect(marks('Аванс 500 ₽, остаток 2,5 млрд руб.')).toEqual(['500 ₽', '2,5 млрд руб.']);
  });

  it('проценты: знак и слово «процентов»', () => {
    expect(marks('скидка 30%, аванс 5 %, штраф 20 процентов')).toEqual(['30%', '5 %', '20 процентов']);
  });

  it('даты и сроки', () => {
    expect(marks('сдать до 15.12, выплатить до 15.12.2026')).toEqual(['15.12', '15.12.2026']);
    expect(marks('срок 47 месяцев, ещё 2 недели, 12 октября')).toEqual(['47 месяцев', '2 недели', '12 октября']);
  });

  it('числа с единицами: м², м³, т, шт', () => {
    expect(marks('площадь 1 200 м², бетон 85 м³, арматура 5 т, 3 шт')).toEqual(['1 200 м²', '85 м³', '5 т', '3 шт']);
  });

  it('в жирном тексте метка попадает в children', () => {
    const [n] = parseHighlighted('**аванс 7 ₽**');
    expect(n).toEqual({
      type: 'strong',
      text: 'аванс 7 ₽',
      children: [{ type: 'text', text: 'аванс ' }, { type: 'mark', text: '7 ₽' }],
    });
  });

  it('обычный текст, «Спикер 1» и слова с числом-1 — без меток', () => {
    expect(marks('Обсудили условия договора и порядок работ')).toEqual([]);
    expect(marks('Спикер 1 согласился, пункт 5, т.к. нужно')).toEqual([]);
    expect(parseHighlighted('Просто текст')).toEqual([{ type: 'text', text: 'Просто текст' }]);
  });
});
