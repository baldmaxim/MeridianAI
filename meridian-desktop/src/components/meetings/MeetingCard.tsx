import React from "react";
import { useTranslation } from "react-i18next";
import { Play } from "lucide-react";
import type { MeetingInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { formatStartedAt, isResumable } from "@/lib/utils/meetingFormat";
import { MeetingDuration } from "./MeetingDuration";
import { MeetingStatusBadge } from "./MeetingStatusBadge";
import { SyncBadge } from "./SyncBadge";

interface MeetingCardProps {
  meeting: MeetingInfo;
  resuming: boolean;
  onOpen: (id: string) => void;
  onResume: (id: string) => void;
}

export const MeetingCard: React.FC<MeetingCardProps> = ({
  meeting,
  resuming,
  onOpen,
  onResume,
}) => {
  const { t, i18n } = useTranslation();
  const interrupted = meeting.status === "interrupted";

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(meeting.id);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(meeting.id)}
      onKeyDown={handleKeyDown}
      className={`cursor-pointer rounded-lg border bg-card p-3 text-start focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary ${
        interrupted
          ? "border-amber/60"
          : "border-mid-gray/20 hover:border-logo-primary/60"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 break-words text-sm font-semibold text-text">
          {meeting.title}
        </h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <MeetingStatusBadge status={meeting.status} />
          <SyncBadge
            syncState={meeting.sync_state}
            syncError={meeting.sync_error}
          />
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
        <span>{formatStartedAt(meeting.started_at, i18n.language)}</span>
        <MeetingDuration meeting={meeting} className="text-text" />
        <span>
          {meeting.capture_mode === "online"
            ? t("meetings.list.modeOnline")
            : t("meetings.list.modeInPerson")}
        </span>
      </div>
      {interrupted && isResumable(meeting) && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="min-w-0 text-xs text-amber">
            {t("meetings.interrupted.hint")}
          </p>
          <Button
            size="sm"
            variant="primary"
            disabled={resuming}
            onClick={(event) => {
              event.stopPropagation();
              onResume(meeting.id);
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
