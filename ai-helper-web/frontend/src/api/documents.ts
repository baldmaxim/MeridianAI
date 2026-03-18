import api from './client';
import type { DocumentInfo } from '../types';

export async function uploadDocument(file: File, docType: string): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('doc_type', docType);
  const { data } = await api.post<DocumentInfo>('/documents/upload', formData);
  return data;
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const { data } = await api.get<DocumentInfo[]>('/documents');
  return data;
}

export async function removeDocument(filename: string): Promise<void> {
  await api.delete(`/documents/${encodeURIComponent(filename)}`);
}
