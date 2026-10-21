import type { StateCreator } from 'zustand';
import type { IMeetingStore, IContextSlice } from './types';

// Дефолт вида встречи: диктофон (Задача 2) — и на мобильном, и на десктопе. Десктоп
// открывает встроенный простой диктофон (кнопка «Начать» → таймер); полный интерфейс
// доступен переключателем. Явный выбор пользователя сохраняется в meridian_ui_mode_v2.
const storedUiMode = typeof localStorage !== 'undefined' ? localStorage.getItem('meridian_ui_mode_v2') : null;
const initialUiMode: 'simple' | 'full' =
  storedUiMode === 'simple' || storedUiMode === 'full' ? storedUiMode : 'simple';

export const createContextSlice: StateCreator<IMeetingStore, [], [], IContextSlice> = (set) => ({
  documents: [],
  addDocument: (doc) => set((s) => ({ documents: [...s.documents, doc] })),
  removeDocument: (filename) =>
    set((s) => ({ documents: s.documents.filter((d) => d.filename !== filename) })),
  setDocuments: (docs) => set({ documents: docs }),

  meetingName: '',
  meetingStartedAt: null,
  setMeetingStartedAt: (v) => set({ meetingStartedAt: v }),
  contextEditedAt: 0,
  meetingTopic: '',
  meetingNotes: '',
  negotiationType: 'sale',
  meetingRole: '',
  opponentWeaknesses: '',
  setMeetingName: (n) => set({ meetingName: n }),
  markContextEdited: () => set({ contextEditedAt: Date.now() }),
  setMeetingTopic: (t) => set({ meetingTopic: t }),
  setMeetingNotes: (n) => set({ meetingNotes: n }),
  setNegotiationType: (t) => set({ negotiationType: t }),
  setMeetingRole: (r) => set({ meetingRole: r }),
  setOpponentWeaknesses: (w) => set({ opponentWeaknesses: w }),

  uiMode: initialUiMode,
  setUiMode: (m) => {
    try { localStorage.setItem('meridian_ui_mode_v2', m); } catch { /* ignore */ }
    set({ uiMode: m });
  },

  activeRoleName: null,
  setActiveRoleName: (name) => set({ activeRoleName: name }),

  meetingSavedId: null,
  setMeetingSavedId: (id) => set({ meetingSavedId: id }),

  selectedCustomerId: null,
  selectedObjectId: null,
  selectedCustomerName: null,
  selectedObjectName: null,
  draftMeetingId: null,
  setSelectedCustomerId: (id) => set({ selectedCustomerId: id }),
  setSelectedObjectId: (id) => set({ selectedObjectId: id }),
  setSelectedCustomerName: (n) => set({ selectedCustomerName: n }),
  setSelectedObjectName: (n) => set({ selectedObjectName: n }),
  setDraftMeetingId: (id) => set({ draftMeetingId: id }),

  objectHeader: null,
  setObjectHeader: (v) => set({ objectHeader: v }),
});
