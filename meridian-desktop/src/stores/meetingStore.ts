import { create } from "zustand";
import {
  commands,
  type MeetingDetails,
  type MeetingInfo,
  type MeetingLevels,
  type MeetingState,
  type Note,
  type Segment,
  type StartMeetingRequest,
} from "@/bindings";
import { sortMeetings } from "@/lib/utils/meetingFormat";

export interface ActiveSession {
  id: string;
  /** Wall-clock ms at which the meeting timeline was 0; elapsed = now - since. */
  since: number;
}

export interface DeviceError {
  key: string;
  meetingId: string;
  channel: string | null;
  message: string;
}

const NO_LEVELS: MeetingLevels = { mic: 0, system: 0 };

/** Action result: `null` on success, otherwise the backend's error message. */
type ActionError = string | null;

interface MeetingStore {
  meetings: MeetingInfo[];
  listLoaded: boolean;
  listError: string | null;
  openId: string | null;
  details: MeetingDetails | null;
  detailsLoading: boolean;
  detailsError: string | null;
  active: ActiveSession | null;
  queueLen: number;
  levels: MeetingLevels;
  stopping: boolean;
  deviceErrors: DeviceError[];

  loadList: () => Promise<void>;
  syncActive: () => Promise<void>;
  openMeeting: (id: string) => Promise<void>;
  closeMeeting: () => void;
  startMeeting: (request: StartMeetingRequest) => Promise<ActionError>;
  resumeMeeting: (id: string) => Promise<ActionError>;
  stopMeeting: () => Promise<ActionError>;
  deleteMeeting: (id: string) => Promise<ActionError>;
  renameMeeting: (id: string, title: string) => Promise<ActionError>;
  saveNote: (
    noteId: string | null,
    atSeconds: number,
    text: string,
  ) => Promise<ActionError>;
  deleteNote: (noteId: string) => Promise<ActionError>;
  saveContext: (
    id: string,
    negotiationType: string | null,
    keyTerms: string | null,
    opponentWeaknesses: string | null,
  ) => Promise<ActionError>;
  dismissDeviceError: (key: string) => void;

  // Backend event handlers
  applyState: (state: MeetingState) => void;
  applySegment: (segment: Segment) => void;
  applyLevels: (levels: MeetingLevels) => void;
}

const upsertMeeting = (
  meetings: MeetingInfo[],
  meeting: MeetingInfo,
): MeetingInfo[] =>
  sortMeetings([...meetings.filter((m) => m.id !== meeting.id), meeting]);

const sortSegments = (segments: Segment[]): Segment[] =>
  [...segments].sort((a, b) => a.start_time - b.start_time);

const sortNotes = (notes: Note[]): Note[] =>
  [...notes].sort((a, b) => a.at_seconds - b.at_seconds);

const mergeSegments = (a: Segment[], b: Segment[]): Segment[] => {
  const byId = new Map<string, Segment>();
  for (const segment of [...a, ...b]) byId.set(segment.id, segment);
  return sortSegments([...byId.values()]);
};

export const useMeetingStore = create<MeetingStore>()((set, get) => {
  /** Drops the live-recording state once the backend closed the meeting. */
  const finishActive = (id: string) => {
    if (get().active?.id !== id) return;
    set({
      active: null,
      stopping: false,
      queueLen: 0,
      levels: NO_LEVELS,
    });
    void get().loadList();
    if (get().openId === id) void get().openMeeting(id);
  };

  return {
    meetings: [],
    listLoaded: false,
    listError: null,
    openId: null,
    details: null,
    detailsLoading: false,
    detailsError: null,
    active: null,
    queueLen: 0,
    levels: NO_LEVELS,
    stopping: false,
    deviceErrors: [],

    loadList: async () => {
      const result = await commands.listMeetings();
      if (result.status === "ok") {
        set({
          meetings: sortMeetings(result.data),
          listLoaded: true,
          listError: null,
        });
      } else {
        set({ listLoaded: true, listError: result.error });
      }
    },

    syncActive: async () => {
      const result = await commands.getActiveMeeting();
      if (result.status !== "ok") return;
      const state = result.data;
      if (!state) {
        set({ active: null, stopping: false, queueLen: 0, levels: NO_LEVELS });
        return;
      }
      set((s) => ({
        active: {
          id: state.meeting.id,
          since: Date.now() - state.elapsed_seconds * 1000,
        },
        queueLen: state.queue_len,
        levels: state.levels,
        meetings: upsertMeeting(s.meetings, state.meeting),
      }));
    },

    openMeeting: async (id) => {
      const switching = get().openId !== id;
      set((s) => ({
        openId: id,
        details: switching ? null : s.details,
        detailsLoading: switching || s.details === null,
        detailsError: null,
      }));
      const result = await commands.getMeeting(id);
      if (get().openId !== id) return;
      if (result.status === "ok") {
        set((s) => {
          const previous = s.details?.meeting.id === id ? s.details : null;
          return {
            details: {
              meeting: result.data.meeting,
              // Segments pushed by events while the request was in flight
              // are kept (deduplicated by id).
              segments: mergeSegments(
                previous?.segments ?? [],
                result.data.segments,
              ),
              notes: sortNotes(result.data.notes),
            },
            detailsLoading: false,
            meetings: upsertMeeting(s.meetings, result.data.meeting),
          };
        });
      } else {
        set({ detailsLoading: false, detailsError: result.error });
      }
    },

    closeMeeting: () =>
      set({ openId: null, details: null, detailsError: null }),

    startMeeting: async (request) => {
      const result = await commands.startMeeting(request);
      if (result.status === "error") return result.error;
      await get().syncActive();
      void get().loadList();
      await get().openMeeting(result.data.id);
      return null;
    },

    resumeMeeting: async (id) => {
      const result = await commands.resumeMeeting(id);
      if (result.status === "error") return result.error;
      await get().syncActive();
      void get().loadList();
      await get().openMeeting(id);
      return null;
    },

    stopMeeting: async () => {
      if (!get().active) return null;
      set({ stopping: true });
      const result = await commands.stopMeeting();
      if (result.status === "error") {
        set({ stopping: false });
        return result.error;
      }
      const info = result.data;
      set((s) => ({
        meetings: upsertMeeting(s.meetings, info),
        details:
          s.details?.meeting.id === info.id
            ? { ...s.details, meeting: info }
            : s.details,
      }));
      finishActive(info.id);
      return null;
    },

    deleteMeeting: async (id) => {
      const result = await commands.deleteMeeting(id);
      if (result.status === "error") return result.error;
      set((s) => ({ meetings: s.meetings.filter((m) => m.id !== id) }));
      if (get().openId === id) get().closeMeeting();
      return null;
    },

    renameMeeting: async (id, title) => {
      const result = await commands.renameMeeting(id, title);
      if (result.status === "error") return result.error;
      const trimmed = title.trim();
      set((s) => ({
        meetings: s.meetings.map((m) =>
          m.id === id ? { ...m, title: trimmed } : m,
        ),
        details:
          s.details?.meeting.id === id
            ? {
                ...s.details,
                meeting: { ...s.details.meeting, title: trimmed },
              }
            : s.details,
      }));
      return null;
    },

    saveNote: async (noteId, atSeconds, text) => {
      const meetingId = get().openId;
      if (!meetingId) return null;
      const result = await commands.upsertNote({
        id: noteId,
        meeting_id: meetingId,
        at_seconds: atSeconds,
        text,
      });
      if (result.status === "error") return result.error;
      const note = result.data;
      set((s) =>
        s.details?.meeting.id === meetingId
          ? {
              details: {
                ...s.details,
                notes: sortNotes([
                  ...s.details.notes.filter((n) => n.id !== note.id),
                  note,
                ]),
              },
            }
          : {},
      );
      return null;
    },

    deleteNote: async (noteId) => {
      const result = await commands.deleteNote(noteId);
      if (result.status === "error") return result.error;
      set((s) =>
        s.details
          ? {
              details: {
                ...s.details,
                notes: s.details.notes.filter((n) => n.id !== noteId),
              },
            }
          : {},
      );
      return null;
    },

    saveContext: async (id, negotiationType, keyTerms, opponentWeaknesses) => {
      const result = await commands.setMeetingContext(
        id,
        negotiationType,
        keyTerms,
        opponentWeaknesses,
      );
      if (result.status === "error") return result.error;
      const info = result.data;
      set((s) => ({
        meetings: upsertMeeting(s.meetings, info),
        details:
          s.details?.meeting.id === info.id
            ? { ...s.details, meeting: info }
            : s.details,
      }));
      return null;
    },

    dismissDeviceError: (key) =>
      set((s) => ({
        deviceErrors: s.deviceErrors.filter((e) => e.key !== key),
      })),

    applyState: (state) => {
      switch (state.kind) {
        case "started":
          set((s) => ({
            deviceErrors: s.deviceErrors.filter(
              (e) => e.meetingId !== state.meeting_id,
            ),
          }));
          void get().syncActive();
          void get().loadList();
          break;
        case "stopping":
          if (get().active?.id === state.meeting_id) set({ stopping: true });
          break;
        case "stopped":
          finishActive(state.meeting_id);
          break;
        case "queue":
          if (get().active?.id === state.meeting_id) {
            set({ queueLen: state.queue_len });
          }
          break;
        case "device_error": {
          const message = state.message ?? "";
          const key = `${state.meeting_id}:${state.channel ?? ""}:${message}`;
          set((s) =>
            s.deviceErrors.some((e) => e.key === key)
              ? {}
              : {
                  deviceErrors: [
                    ...s.deviceErrors,
                    {
                      key,
                      meetingId: state.meeting_id,
                      channel: state.channel,
                      message,
                    },
                  ],
                },
          );
          break;
        }
        default:
          break;
      }
    },

    applySegment: (segment) =>
      set((s) =>
        s.details?.meeting.id === segment.meeting_id
          ? {
              details: {
                ...s.details,
                segments: mergeSegments(s.details.segments, [segment]),
              },
            }
          : {},
      ),

    applyLevels: (levels) => {
      if (get().active) set({ levels });
    },
  };
});
