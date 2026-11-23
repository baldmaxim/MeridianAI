import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronLeft, Play, Square, Trash2 } from "lucide-react";
import type { MeetingInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { useMeetingStore } from "@/stores/meetingStore";
import {
  formatDateChip,
  formatTimeRange,
  isResumable,
} from "@/lib/utils/meetingFormat";
import { AudioStateNote } from "./AudioStateNote";
import { ChangeProjectDialog } from "./ChangeProjectDialog";
import { DateTimeChips } from "./DateTimeChips";
import { LevelMeters } from "./LevelMeters";
import { LiveStatusChip } from "./LiveStatusChip";
import { MeetingDuration } from "./MeetingDuration";
import { MeetingStatusBadge } from "./MeetingStatusBadge";
import { MeetingSyncActions } from "./MeetingSyncActions";
import { ProjectChip } from "./ProjectChip";
import { RefineStatusChip } from "./RefineStatusChip";
import { SyncBadge } from "./SyncBadge";
import { TitleEditor } from "./TitleEditor";

interface LocalMeetingHeaderProps {
  meeting: MeetingInfo;
  resuming: boolean;
  onResume: (id: string) => void;
  onDelete: () => void;
  /** Server re-transcription state; `null`: not known (not synced, view not loaded). */
  refine: { status: string | null; error: string | null } | null;
}

/** Header of a local meeting: title, chips, status, record/sync actions. */
export const LocalMeetingHeader: React.FC<LocalMeetingHeaderProps> = ({
  meeting,
  resuming,
  onResume,
  onDelete,
  refine,
}) => {
  const { t, i18n } = useTranslation();
  const isActive = useMeetingStore((s) => s.active?.id === meeting.id);
  const stopping = useMeetingStore((s) => s.stopping);
  const queueLen = useMeetingStore((s) => s.queueLen);
  const closeMeeting = useMeetingStore((s) => s.closeMeeting);
  const [projectOpen, setProjectOpen] = useState(false);

  const handleStop = async () => {
    const error = await useMeetingStore.getState().stopMeeting();
    if (error)
      toast.error(t("meetings.errors.stopFailed"), { description: error });
  };

  // On the site the project is the site's: it changes there.
  const onSite = meeting.server_meeting_id !== null;

  return (
    <div className="shrink-0 border-b border-border bg-background px-4 py-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label={t("meetings.actions.back")}
          title={t("meetings.actions.back")}
          onClick={closeMeeting}
          className="shrink-0 cursor-pointer rounded-lg p-1 text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
        >
          <ChevronLeft className="h-5 w-5" aria-hidden="true" />
        </button>
        <TitleEditor meetingId={meeting.id} title={meeting.title} />
        <div className="flex shrink-0 items-center gap-1.5">
          {isActive ? (
            <Button
              variant="danger"
              size="sm"
              disabled={stopping}
              onClick={() => void handleStop()}
              className="flex items-center gap-1.5"
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              {stopping ? t("meetings.view.stopping") : t("meetings.view.stop")}
            </Button>
          ) : (
            <>
              {isResumable(meeting) && meeting.status !== "interrupted" && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={resuming}
                  onClick={() => onResume(meeting.id)}
                  className="flex items-center gap-1.5"
                >
                  <Play className="h-3.5 w-3.5" aria-hidden="true" />
                  {resuming
                    ? t("meetings.actions.resuming")
                    : t("meetings.actions.resume")}
                </Button>
              )}
              <Button
                variant="danger-ghost"
                size="sm"
                onClick={onDelete}
                className="flex items-center gap-1.5"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                {t("meetings.actions.delete")}
              </Button>
            </>
          )}
        </div>
        <MeetingDuration
          meeting={meeting}
          className="ms-auto shrink-0 text-lg text-text"
        />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
          <DateTimeChips
            date={formatDateChip(meeting.started_at, i18n.language)}
            time={formatTimeRange(
              meeting.started_at,
              meeting.ended_at,
              i18n.language,
            )}
          />
          <ProjectChip
            showEmpty
            customerName={meeting.customer_name}
            objectName={meeting.object_name}
            onClick={onSite ? undefined : () => setProjectOpen(true)}
            title={
              onSite
                ? t("meetings.project.lockedHint")
                : t("meetings.project.change")
            }
          />
          <MeetingStatusBadge status={meeting.status} />
          <SyncBadge
            syncState={meeting.sync_state}
            syncError={meeting.sync_error}
          />
          {refine && meeting.status === "stopped" && (
            <RefineStatusChip status={refine.status} error={refine.error} />
          )}
          <AudioStateNote audioState={meeting.audio_state} />
          {isActive && <LiveStatusChip />}
          {isActive && <LevelMeters captureMode={meeting.capture_mode} />}
          {isActive && queueLen > 0 && (
            <span className="text-xs text-muted">
              {t("meetings.view.queue", { count: queueLen })}
            </span>
          )}
        </div>
        {!isActive && (
          <div className="flex items-center gap-1.5">
            <MeetingSyncActions meeting={meeting} />
          </div>
        )}
      </div>
      <ChangeProjectDialog
        meeting={meeting}
        open={projectOpen}
        onOpenChange={setProjectOpen}
      />
    </div>
  );
};
