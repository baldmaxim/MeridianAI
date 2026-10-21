import type { StateCreator } from 'zustand';
import type { MultiChannelLiveSegment } from '../../types';
import type { IMeetingStore, IMultiChannelSlice } from './types';

const MAX_LIVE_FINALS = 2000;
// Этап 9.6: dedupe по segment_id + sort (start_server_ms, channel_index) + bounded.
function mergeLiveFinal(list: MultiChannelLiveSegment[], seg: MultiChannelLiveSegment): MultiChannelLiveSegment[] {
  if (list.some((s) => s.segment_id === seg.segment_id)) return list;
  const next = [...list, seg].sort(
    (a, b) => a.start_server_ms - b.start_server_ms || a.channel_index - b.channel_index);
  return next.length > MAX_LIVE_FINALS ? next.slice(next.length - MAX_LIVE_FINALS) : next;
}

export const createMultiChannelSlice: StateCreator<IMeetingStore, [], [], IMultiChannelSlice> = (set) => ({
  multiChannelLiveState: null,
  multiChannelLiveFinalSegments: [],
  multiChannelLiveInterimByChannel: {},
  setMultiChannelLiveState: (s) => set({ multiChannelLiveState: s }),
  upsertMultiChannelLiveResult: (seg) =>
    set((st) => {
      if (seg.is_final) {
        const interim = { ...st.multiChannelLiveInterimByChannel };
        delete interim[seg.channel_index];
        return {
          multiChannelLiveFinalSegments: mergeLiveFinal(st.multiChannelLiveFinalSegments, seg),
          multiChannelLiveInterimByChannel: interim,
        };
      }
      const interim = { ...st.multiChannelLiveInterimByChannel };
      if (!seg.transcript.trim()) delete interim[seg.channel_index];
      else interim[seg.channel_index] = seg;
      return { multiChannelLiveInterimByChannel: interim };
    }),
  setMultiChannelLiveSnapshot: (snap) =>
    set(() => {
      const interim: Record<number, MultiChannelLiveSegment> = {};
      for (const [k, v] of Object.entries(snap.latest_interim_by_channel || {})) {
        interim[Number(k)] = v;
      }
      const finals = [...(snap.final_segments || [])].sort(
        (a, b) => a.start_server_ms - b.start_server_ms || a.channel_index - b.channel_index);
      return {
        multiChannelLiveState: snap.state,
        multiChannelLiveFinalSegments: finals,
        multiChannelLiveInterimByChannel: interim,
      };
    }),
  clearMultiChannelLive: () =>
    set({ multiChannelLiveFinalSegments: [], multiChannelLiveInterimByChannel: {} }),

  multiChannelReconciliation: null,
  dismissedReconciliationEntries: {},
  selectedReconciliationEntries: {},
  setMultiChannelReconciliation: (s) =>
    set((st) => {
      if (s == null) {
        return { multiChannelReconciliation: null,
                 dismissedReconciliationEntries: {}, selectedReconciliationEntries: {} };
      }
      // игнорировать устаревшую ревизию
      const cur = st.multiChannelReconciliation;
      if (cur && s.revision < cur.revision) return {};
      // dismiss/select сохраняем только для всё ещё существующих entry id
      const ids = new Set(s.entries.map((e) => e.entry_id));
      const prune = (m: Record<string, true>) => {
        const out: Record<string, true> = {};
        for (const k of Object.keys(m)) if (ids.has(k)) out[k] = true;
        return out;
      };
      return {
        multiChannelReconciliation: s,
        dismissedReconciliationEntries: prune(st.dismissedReconciliationEntries),
        selectedReconciliationEntries: prune(st.selectedReconciliationEntries),
      };
    }),
  dismissReconciliationEntry: (entryId) =>
    set((st) => {
      const sel = { ...st.selectedReconciliationEntries };
      delete sel[entryId];
      return {
        dismissedReconciliationEntries: { ...st.dismissedReconciliationEntries, [entryId]: true },
        selectedReconciliationEntries: sel,
      };
    }),
  selectReconciliationEntry: (entryId, selected) =>
    set((st) => {
      const sel = { ...st.selectedReconciliationEntries };
      if (selected) sel[entryId] = true; else delete sel[entryId];
      return { selectedReconciliationEntries: sel };
    }),
  clearReconciliationSelection: () => set({ selectedReconciliationEntries: {} }),
  clearMultiChannelReconciliation: () =>
    set({ multiChannelReconciliation: null, dismissedReconciliationEntries: {},
          selectedReconciliationEntries: {} }),

  transcriptionAuthority: null,
  transcriptionAuthorityError: null,
  setTranscriptionAuthority: (s) =>
    set((st) => {
      // игнорировать устаревшую ревизию (state приходит и из join, и из broadcast)
      const cur = st.transcriptionAuthority;
      if (s && cur && cur.meeting_id === s.meeting_id && s.revision < cur.revision) return {};
      return { transcriptionAuthority: s, transcriptionAuthorityError: null };
    }),
  setTranscriptionAuthorityError: (e) => set({ transcriptionAuthorityError: e }),
});
