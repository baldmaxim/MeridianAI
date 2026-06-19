import api from './client';

export interface LetterHit {
  chunkId: string;
  letterId: string | null;
  subject: string | null;
  regNumber: string | null;
  number: string | null;
  customerNumber: string | null;
  direction: string | null;
  letterDate: string | null;
  projectId: number | null;
  pageFrom: number | null;
  pageTo: number | null;
  text: string;
  score: number;
}

export interface LetterSearchParams {
  query: string;
  k?: number;
  projectId?: number | null;
}

/** Прямой семантический поиск по письмам PayHub (вектор+FTS). */
export async function searchLetters(params: LetterSearchParams): Promise<LetterHit[]> {
  const { data } = await api.post<LetterHit[]>('/letters/search', {
    query: params.query,
    k: params.k ?? 8,
    project_id: params.projectId ?? null,
  });
  return data;
}
