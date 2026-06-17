import api from './client';

export type ContextPreviewMode = 'auto' | 'manual' | 'strengthen' | 'preview';

export interface ContextBlockPreview {
  kind: string;
  title: string;
  enabled: boolean;
  reason: string | null;
  chars: number;
  estimated_tokens: number;
  source_count: number;
  max_chars: number | null;
  truncated: boolean;
  content_preview: string;
  meta: Record<string, unknown>;
}

export interface ContextPackPreview {
  meeting_id: number;
  mode: ContextPreviewMode;
  query_text: string;
  total_chars: number;
  estimated_tokens: number;
  max_chars: number | null;
  truncated: boolean;
  blocks: ContextBlockPreview[];
}

export async function getMeetingContextPreview(
  meetingId: number,
  params?: {
    mode?: ContextPreviewMode;
    q?: string;
    preview_chars_per_block?: number;
  },
): Promise<ContextPackPreview> {
  const query: Record<string, string | number> = {};
  if (params?.mode) query.mode = params.mode;
  if (params?.q) query.q = params.q;
  if (params?.preview_chars_per_block != null) query.preview_chars_per_block = params.preview_chars_per_block;
  const { data } = await api.get<ContextPackPreview>(`/meetings/${meetingId}/context-preview`, { params: query });
  return data;
}
