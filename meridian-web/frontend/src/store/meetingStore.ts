import { create } from 'zustand';
import type { IMeetingStore } from './meeting/types';
import { createTranscriptSlice } from './meeting/transcriptSlice';
import { createSuggestionSlice } from './meeting/suggestionSlice';
import { createSessionSlice } from './meeting/sessionSlice';
import { createContextSlice } from './meeting/contextSlice';
import { createSpeakerSlice } from './meeting/speakerSlice';
import { createRoomSlice } from './meeting/roomSlice';
import { createMultiChannelSlice } from './meeting/multiChannelSlice';

export const useMeetingStore = create<IMeetingStore>()((...a) => ({
  ...createSessionSlice(...a),
  ...createTranscriptSlice(...a),
  ...createSuggestionSlice(...a),
  ...createContextSlice(...a),
  ...createSpeakerSlice(...a),
  ...createRoomSlice(...a),
  ...createMultiChannelSlice(...a),
}));
