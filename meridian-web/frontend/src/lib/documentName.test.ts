import { describe, expect, it } from 'vitest';
import { getDocumentDisplayName } from './documentName';

describe('getDocumentDisplayName', () => {
  it('берёт display_name', () => {
    expect(getDocumentDisplayName({ display_name: 'Смета.docx', original_name: 'КП 1 · 2026-01-01 · Смета.docx' }))
      .toBe('Смета.docx');
  });

  it('без display_name — original_name', () => {
    expect(getDocumentDisplayName({ original_name: 'Договор.pdf' })).toBe('Договор.pdf');
    expect(getDocumentDisplayName({ display_name: '  ', original_name: 'Договор.pdf' })).toBe('Договор.pdf');
    expect(getDocumentDisplayName({ display_name: null, original_name: 'Договор.pdf' })).toBe('Договор.pdf');
  });
});
