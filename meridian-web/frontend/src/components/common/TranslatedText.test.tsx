import { afterEach, describe, it, expect } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { TranslatedText } from './TranslatedText';

describe('TranslatedText', () => {
  afterEach(cleanup);

  it('без перевода показывает только оригинал', () => {
    render(<TranslatedText text="Merhaba" language="tr" />);
    expect(screen.getByText('Merhaba')).toBeTruthy();
    expect(screen.queryByText(/оригинал/)).toBeNull();
  });

  it('с переводом: перевод первым, оригинал вторым с меткой языка', () => {
    render(<TranslatedText text="Merhaba" translation="Здравствуйте" language="tr" />);
    const translation = screen.getByText('Здравствуйте');
    const original = screen.getByText('Merhaba');
    expect(screen.getByText('TR · оригинал')).toBeTruthy();
    expect(translation.compareDocumentPosition(original) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('язык не задан — метка «оригинал»', () => {
    render(<TranslatedText text="Merhaba" translation="Здравствуйте" />);
    expect(screen.getByText('оригинал')).toBeTruthy();
  });
});
