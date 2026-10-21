import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useMeetingStore } from "@/stores/meetingStore";

interface TitleEditorProps {
  meetingId: string;
  title: string;
}

/** Meeting title; a click turns it into an input (Enter/blur saves, Esc cancels). */
export const TitleEditor: React.FC<TitleEditorProps> = ({
  meetingId,
  title,
}) => {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);
  const finished = useRef(false);

  useEffect(() => {
    if (editing) {
      finished.current = false;
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const finish = async (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    setEditing(false);
    const next = draft.trim();
    if (!save || !next || next === title) return;
    const error = await useMeetingStore
      .getState()
      .renameMeeting(meetingId, next);
    if (error)
      toast.error(t("meetings.errors.renameFailed"), { description: error });
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        aria-label={t("meetings.view.titleLabel")}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void finish(true)}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing) return;
          if (e.key === "Enter") void finish(true);
          if (e.key === "Escape") void finish(false);
        }}
        className="min-w-0 flex-1 rounded-md border border-logo-primary bg-surface px-2 py-0.5 text-lg font-semibold text-text focus:outline-none"
      />
    );
  }
  return (
    <button
      type="button"
      title={t("meetings.view.renameHint")}
      onClick={() => {
        setDraft(title);
        setEditing(true);
      }}
      className="min-w-0 cursor-pointer truncate rounded-md px-2 py-0.5 text-start text-lg font-semibold text-text hover:bg-mid-gray/10 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
    >
      {title}
    </button>
  );
};
