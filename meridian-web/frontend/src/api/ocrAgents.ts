import api from './client';

export interface OcrAgentInfo {
  id: number;
  name: string;
  model: string | null;
  agent_version: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  online: boolean;
}

/** Очередь распознавания сканов и подключённые компьютеры с LM Studio. */
export interface OcrQueueStatus {
  pending: number;
  leased: number;
  done: number;
  failed: number;
  agents: OcrAgentInfo[];
}

export async function getOcrQueueStatus(): Promise<OcrQueueStatus> {
  const { data } = await api.get('/admin/ocr-agents');
  return data;
}

/** Подключить компьютер. Токен приходит один раз — в базе только его хэш. */
export async function enrollOcrAgent(name: string): Promise<{ agent: OcrAgentInfo; token: string }> {
  const { data } = await api.post('/admin/ocr-agents', { name });
  return data;
}

export async function revokeOcrAgent(id: number): Promise<void> {
  await api.delete(`/admin/ocr-agents/${id}`);
}
