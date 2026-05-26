import api from './client';

export interface BatchJob {
  id: number;
  status: string;
  original_filename: string;
  original_size: number;
  compressed_size: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface BatchJobDetail extends BatchJob {
  transcription_text: string | null;
  protocol_markdown: string | null;
  protocol_json: string | null;
}

export async function uploadBatchAudio(file: File): Promise<BatchJob> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/batch/upload', form);
  return data;
}

export async function getBatchJobs(): Promise<BatchJob[]> {
  const { data } = await api.get('/batch/jobs');
  return data;
}

export async function getBatchJob(id: number): Promise<BatchJobDetail> {
  const { data } = await api.get(`/batch/jobs/${id}`);
  return data;
}

export async function deleteBatchJob(id: number): Promise<void> {
  await api.delete(`/batch/jobs/${id}`);
}

export async function downloadBatchResult(id: number, type: string): Promise<void> {
  const { data, headers } = await api.get(`/batch/jobs/${id}/download/${type}`, {
    responseType: 'blob',
  });
  const blob = new Blob([data]);
  const disposition = headers['content-disposition'] || '';
  const match = disposition.match(/filename="(.+?)"/);
  const filename = match ? match[1] : `download_${type}`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
