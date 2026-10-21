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
    <section
      aria-label={t("meetings.notes.title")}
      className={`flex min-h-0 flex-1 flex-col rounded-2xl border border-border bg-surface ${className}`}
    >
      <h2 className="shrink-0 px-5 pt-4 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
        {t("meetings.notes.title")}
      </h2>
      <div className="shrink-0 px-5 py-3">
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
          className="w-full rounded-xl border border-border bg-background px-4 py-3 text-base text-text placeholder:text-subtle focus:border-logo-primary focus:outline-none"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-4">
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
    </section>
  );
};
