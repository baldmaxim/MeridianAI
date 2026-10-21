import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type { Note, Segment } from "@/bindings";
import { useMeetingStore } from "@/stores/meetingStore";
import { NoteItem } from "./NoteItem";

interface NotesPaneProps {
  notes: Note[];
  segments: Segment[];
  className?: string;
}

export const NotesPane: React.FC<NotesPaneProps> = ({
  notes,
  segments,
  className = "",
}) => {
  const { t } = useTranslation();
  const [text, setText] = useState("");

  /** Live meeting: current meeting time. Finished one: end of the last phrase. */
  const currentMeetingSeconds = (): number => {
    const active = useMeetingStore.getState().active;
    const openId = useMeetingStore.getState().openId;
    if (active && active.id === openId) {
      return Math.max(0, (Date.now() - active.since) / 1000);
    }
    return segments.reduce((max, s) => Math.max(max, s.end_time), 0);
  };

  const handleAdd = async () => {
    const value = text.trim();
    if (!value) return;
    setText("");
    const error = await useMeetingStore
      .getState()
      .saveNote(null, currentMeetingSeconds(), value);
    if (error) {
      setText(value);
      toast.error(t("meetings.errors.noteFailed"), { description: error });
    }
  };

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${className}`}>
      <div className="shrink-0 px-4 py-3">
        <input
          type="text"
          value={text}
          placeholder={t("meetings.notes.placeholder")}
          aria-label={t("meetings.notes.add")}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void handleAdd();
            }
          }}
          className="w-full rounded-md border border-mid-gray/60 bg-surface px-3 py-2 text-sm text-text placeholder:text-subtle focus:border-logo-primary focus:outline-none"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3">
        {notes.length === 0 ? (
          <p className="mt-6 text-center text-sm text-muted">
            {t("meetings.notes.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {notes.map((note) => (
              <NoteItem key={note.id} note={note} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};
