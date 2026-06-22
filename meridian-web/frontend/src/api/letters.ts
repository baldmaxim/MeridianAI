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

export interface PayhubProject {
  projectId: number;
  name: string;
  letterCount: number | null;
}

/** Проекты PayHub (реальные названия) для экрана связки с нашими объектами.
 *  Пустой список = таблица проектов PayHub не настроена на бэкенде. */
export async function listPayhubProjects(): Promise<PayhubProject[]> {
  const { data } = await api.get<PayhubProject[]>('/letters/projects');
  return data;
}

// ── прикреплённые к встрече письма (ручной выбор в контекст) ───────────────────

/** Письмо, прикреплённое к встрече (снапшот + флаги). */
export interface MeetingLetter {
  sourceId: number;
  included: boolean;
  priority: number;
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
}

export async function listMeetingLetters(meetingId: number): Promise<MeetingLetter[]> {
  const { data } = await api.get<MeetingLetter[]>(`/meetings/${meetingId}/letters`);
  return data;
}

/** Прикрепить найденное письмо к встрече. Лишние поля (score) бэкенд игнорирует. */
export async function attachMeetingLetter(
  meetingId: number,
  hit: LetterHit,
  body?: { included?: boolean; priority?: number },
): Promise<MeetingLetter> {
  const { data } = await api.post<MeetingLetter>(`/meetings/${meetingId}/letters`, {
    ...hit,
    ...(body ?? {}),
  });
  return data;
}

export async function updateMeetingLetter(
  meetingId: number,
  sourceId: number,
  body: { included?: boolean; priority?: number },
): Promise<MeetingLetter> {
  const { data } = await api.patch<MeetingLetter>(`/meetings/${meetingId}/letters/${sourceId}`, body);
  return data;
}

export async function detachMeetingLetter(meetingId: number, sourceId: number): Promise<void> {
  await api.delete(`/meetings/${meetingId}/letters/${sourceId}`);
}
