import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import type { Note } from "@/bindings";
import { useMeetingStore } from "@/stores/meetingStore";
import { formatClock } from "@/lib/utils/meetingFormat";

interface NoteItemProps {
  note: Note;
}

/** One note: click to edit (Enter/blur saves, Esc cancels), trash deletes. */
export const NoteItem: React.FC<NoteItemProps> = ({ note }) => {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.text);
  const inputRef = useRef<HTMLInputElement>(null);
  const finished = useRef(false);

  useEffect(() => {
    if (editing) {
      finished.current = false;
      inputRef.current?.focus();
    }
  }, [editing]);

  const finish = async (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    setEditing(false);
    const next = draft.trim();
    if (!save || !next || next === note.text) return;
    const error = await useMeetingStore
      .getState()
      .saveNote(note.id, note.at_seconds, next);
    if (error)
      toast.error(t("meetings.errors.noteFailed"), { description: error });
  };

  const handleDelete = async () => {
    const error = await useMeetingStore.getState().deleteNote(note.id);
    if (error)
      toast.error(t("meetings.errors.noteFailed"), { description: error });
  };

  return (
    <li className="group flex items-start gap-2 rounded-lg bg-card px-3 py-2">
      <span className="w-12 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-muted">
        {formatClock(note.at_seconds)}
      </span>
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          aria-label={t("meetings.notes.edit")}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void finish(true)}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter") void finish(true);
            if (e.key === "Escape") void finish(false);
          }}
          className="min-w-0 flex-1 rounded-md border border-logo-primary bg-surface px-2 py-0.5 text-sm text-text focus:outline-none"
        />
      ) : (
        <button
          type="button"
          title={t("meetings.notes.edit")}
          onClick={() => {
            setDraft(note.text);
            setEditing(true);
          }}
          className="min-w-0 flex-1 cursor-pointer whitespace-pre-wrap break-words text-start text-sm text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
        >
          {note.text}
        </button>
      )}
      <button
        type="button"
        aria-label={t("meetings.notes.delete")}
        title={t("meetings.notes.delete")}
        // mousedown keeps the edit input from blur-saving before the delete.
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => void handleDelete()}
        className="shrink-0 cursor-pointer text-muted opacity-60 transition-opacity duration-150 hover:text-error hover:opacity-100 focus:opacity-100 motion-reduce:transition-none"
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
      </button>
    </li>
  );
};
