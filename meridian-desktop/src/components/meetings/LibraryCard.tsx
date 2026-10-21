import React from "react";
import { useTranslation } from "react-i18next";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { getEntryStatus, type LibraryEntry } from "@/lib/utils/library";
import {
  formatClock,
  formatTimeOfDay,
  isResumable,
} from "@/lib/utils/meetingFormat";
import { EntryStatusBadge } from "./EntryStatusBadge";
import { MeetingDuration } from "./MeetingDuration";
import { ProjectChip } from "./ProjectChip";
import { SourceMark } from "./SourceMark";

interface LibraryCardProps {
  entry: LibraryEntry;
  syncingId: string | null;
  resuming: boolean;
  onOpen: (entry: LibraryEntry) => void;
  onResume: (id: string) => void;
}

/** One meeting of the library: title, time, project, status, summary. */
export const LibraryCard: React.FC<LibraryCardProps> = ({
  entry,
  syncingId,
  resuming,
  onOpen,
  onResume,
}) => {
  const { t, i18n } = useTranslation();
  const { local } = entry;
  const status = getEntryStatus(entry, syncingId);
  const time = formatTimeOfDay(entry.startedAt, i18n.language);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(entry);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(entry)}
      onKeyDown={handleKeyDown}
      className={`flex cursor-pointer flex-col gap-1.5 rounded-xl border bg-card px-4 py-3 text-start transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
        status === "interrupted"
          ? "border-amber/60"
          : "border-border hover:border-logo-primary/60"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-words text-sm font-semibold text-text">
          {entry.title || t("meetings.library.untitled")}
        </h3>
        <EntryStatusBadge kind={status} detail={local?.sync_error} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        {time && <span className="font-mono tabular-nums">{time}</span>}
        {local ? (
          <MeetingDuration meeting={local} className="text-text" />
        ) : (
          entry.durationSeconds !== null && (
            <span className="font-mono tabular-nums text-text">
              {formatClock(entry.durationSeconds)}
            </span>
          )
        )}
        <ProjectChip
          customerName={entry.customerName}
          objectName={entry.objectName}
        />
        <SourceMark source={entry.source} />
      </div>
      {entry.summary && (
        <p className="line-clamp-2 break-words text-xs text-muted">
          {entry.summary}
        </p>
      )}
      {local && status === "interrupted" && isResumable(local) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="min-w-0 text-xs text-amber">
            {t("meetings.interrupted.hint")}
          </p>
          <Button
            size="sm"
            variant="primary"
            disabled={resuming}
            onClick={(event) => {
              event.stopPropagation();
              onResume(local.id);
            }}
            className="flex items-center gap-1.5"
          >
            <Play className="h-3 w-3" aria-hidden="true" />
            {resuming
              ? t("meetings.actions.resuming")
              : t("meetings.actions.resume")}
          </Button>
        </div>
      )}
    </div>
  );
};
