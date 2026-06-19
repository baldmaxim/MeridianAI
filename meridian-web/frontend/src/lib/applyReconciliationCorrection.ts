import type { MultiChannelReconciliationEntry, SpeakerSegmentCorrection } from '../types';
import type { SpeakerSegmentCorrectionBulkItem } from '../api/speakerCorrections';

// Этап 9.7: построение segment-correction из reconciliation-entry.
// Меняем ТОЛЬКО сторону. corrected_speaker_label и note существующей коррекции сохраняем.
// Никаких pseudo speaker label из channel index.

export function buildCorrectionFromReconciliation(args: {
  entry: MultiChannelReconciliationEntry;
  existing?: SpeakerSegmentCorrection;
}): SpeakerSegmentCorrectionBulkItem {
  const { entry, existing } = args;
  if (!entry.primary_segment_key) throw new Error('entry has no primary_segment_key');
  if (entry.channel_side !== 'self' && entry.channel_side !== 'opponent') {
    throw new Error('entry has no applicable channel_side');
  }
  return {
    segment_key: entry.primary_segment_key,
    side: entry.channel_side,
    // сохраняем существующие поля, не перезаписываем
    corrected_speaker_label: existing?.corrected_speaker_label ?? null,
    note: existing?.note ?? null,
    original_speaker_label:
      existing?.original_speaker_label ?? entry.original_speaker_label ?? null,
  };
}

export function buildBulkReconciliationCorrections(args: {
  entries: MultiChannelReconciliationEntry[];
  selected: Record<string, true>;
  dismissed: Record<string, true>;
  existingByKey: Record<string, SpeakerSegmentCorrection>;
  includeConflicts: boolean;
}): SpeakerSegmentCorrectionBulkItem[] {
  const { entries, selected, dismissed, existingByKey, includeConflicts } = args;
  const items: SpeakerSegmentCorrectionBulkItem[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    if (!selected[entry.entry_id] || dismissed[entry.entry_id]) continue;
    if (!entry.can_apply_side || !entry.primary_segment_key) continue;
    if (entry.channel_side !== 'self' && entry.channel_side !== 'opponent') continue;
    if (entry.requires_conflict_confirmation && !includeConflicts) continue;
    if (seen.has(entry.primary_segment_key)) continue;   // уникальные segment keys
    seen.add(entry.primary_segment_key);
    items.push(buildCorrectionFromReconciliation({
      entry, existing: existingByKey[entry.primary_segment_key],
    }));
  }
  return items;
}
