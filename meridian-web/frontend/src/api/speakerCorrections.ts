import api from './client';
import type { SpeakerSegmentCorrection, PublicSpeakerSide } from '../types';

export interface SpeakerSegmentCorrectionPutBody {
  original_speaker_label?: string | null;
  corrected_speaker_label?: string | null;
  side?: PublicSpeakerSide | '' | null;
  note?: string | null;
}

export interface SpeakerSegmentCorrectionBulkItem extends SpeakerSegmentCorrectionPutBody {
  segment_key: string;
}

export async function listSpeakerCorrections(meetingId: number): Promise<SpeakerSegmentCorrection[]> {
  const { data } = await api.get<SpeakerSegmentCorrection[]>(`/meetings/${meetingId}/speaker-corrections`);
  return data;
}

export async function putSpeakerCorrection(
  meetingId: number, segmentKey: string, body: SpeakerSegmentCorrectionPutBody,
): Promise<SpeakerSegmentCorrection[]> {
  const { data } = await api.put<SpeakerSegmentCorrection[]>(
    `/meetings/${meetingId}/speaker-corrections/${encodeURIComponent(segmentKey)}`, body,
  );
  return data;
}

export async function deleteSpeakerCorrection(meetingId: number, segmentKey: string): Promise<void> {
  await api.delete(`/meetings/${meetingId}/speaker-corrections/${encodeURIComponent(segmentKey)}`);
}

export async function bulkPutSpeakerCorrections(
  meetingId: number, items: SpeakerSegmentCorrectionBulkItem[],
): Promise<SpeakerSegmentCorrection[]> {
  const { data } = await api.post<SpeakerSegmentCorrection[]>(
    `/meetings/${meetingId}/speaker-corrections/bulk`, { items },
  );
  return data;
}
