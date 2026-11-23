interface IDocumentNames {
  display_name?: string | null;
  original_name: string;
}

/** Читаемое имя документа (сервер срезает служебный префикс и OCR-хвост); нет — исходное имя. */
export const getDocumentDisplayName = (doc: IDocumentNames): string =>
  doc.display_name?.trim() || doc.original_name;
