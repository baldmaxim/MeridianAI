import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { MarkdownView } from './MarkdownView';

const MD = '## Решения\n- Аванс 30% до 15.12\n\nСумма 5 млн ₸ за 47 месяцев.\n\nОбычный текст без цифр.';

describe('MarkdownView highlight', () => {
  afterEach(cleanup);

  it('highlight: выделяет суммы, проценты и сроки вне «Краткого резюме»', () => {
    const { container } = render(<MarkdownView md={MD} highlight />);
    expect([...container.querySelectorAll('mark')].map((m) => m.textContent)).toEqual(['30%', '15.12', '5 млн ₸', '47 месяцев']);
  });

  it('без highlight (как у записи) вне резюме меток нет; в резюме есть', () => {
    const { container } = render(<MarkdownView md={MD} />);
    expect(container.querySelectorAll('mark').length).toBe(0);
    cleanup();
    const { container: c2 } = render(<MarkdownView md={'## Краткое резюме\n1. Аванс 30%.'} />);
    expect(c2.querySelectorAll('mark').length).toBe(1);
  });
});
