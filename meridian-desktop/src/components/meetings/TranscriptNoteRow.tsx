import React from "react";
import { useTranslation } from "react-i18next";
import { StickyNote } from "lucide-react";
import type { Note } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";

interface TranscriptNoteRowProps {
  note: Note;
}

/** A note shown inline in the transcript, styled apart from spoken phrases. */
export const TranscriptNoteRow: React.FC<TranscriptNoteRowProps> = ({
  note,
}) => {
  const { t } = useTranslation();
  return (
    <div className="flex gap-3">
      <span className="w-12 shrink-0 pt-1 text-end font-mono text-xs tabular-nums text-muted">
        {formatClock(note.at_seconds)}
      </span>
      <div className="min-w-0 flex-1 rounded-lg border border-dashed border-amber/50 bg-amber/10 px-3 py-1.5">
        <span className="flex items-center gap-1 text-xs font-semibold text-amber">
          <StickyNote className="h-3 w-3" aria-hidden="true" />
          {t("meetings.transcript.note")}
        </span>
        <p className="whitespace-pre-wrap break-words text-sm text-text">
          {note.text}
        </p>
      </div>
    </div>
  );
};
