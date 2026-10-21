import type { StateCreator } from 'zustand';
import type { IMeetingStore, IRoomSlice } from './types';

export const createRoomSlice: StateCreator<IMeetingStore, [], [], IRoomSlice> = (set) => ({
  currentMeetingId: null,
  roomConnected: false,
  connectionId: null,
  deviceRole: null,
  canSendAudio: false,
  activeAudioSource: null,
  recording: false,
  setCurrentMeetingId: (id) => set({ currentMeetingId: id }),
  setRoomConnected: (v) => set({ roomConnected: v }),
  setRoomJoined: (p) => set({
    roomConnected: true,
    connectionId: p.connectionId,
    deviceRole: p.deviceRole,
    canSendAudio: p.canSendAudio,
    activeAudioSource: p.activeAudioSource,
  }),
  setActiveAudioSource: (id) => set({ activeAudioSource: id }),
  setRecording: (v) => set({ recording: v }),
  activeAudioUserLabel: null,
  recordingStartedAtMs: null,
  setRecordingMeta: (p) => set({ activeAudioUserLabel: p.userLabel, recordingStartedAtMs: p.startedAtMs }),

  participants: [],
  setParticipants: (p) => set({ participants: p }),

  recordPermissionDenied: false,
  phoneRecording: false,
  setRecordPermissionDenied: (v) => set({ recordPermissionDenied: v }),
  setPhoneRecording: (v) => set({ phoneRecording: v }),

  deviceSync: null,
  setDeviceSync: (s) => set({ deviceSync: s }),

  shadowTracks: [],
  setShadowTracks: (tracks) => set({ shadowTracks: tracks }),

  ingestAlignment: null,
  setIngestAlignment: (a) => set({ ingestAlignment: a }),
});
