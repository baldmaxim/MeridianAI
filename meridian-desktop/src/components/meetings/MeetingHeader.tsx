import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronLeft, Play, Square, Trash2 } from "lucide-react";
import type { MeetingInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { useMeetingStore } from "@/stores/meetingStore";
import { isResumable } from "@/lib/utils/meetingFormat";
import { AudioStateNote } from "./AudioStateNote";
import { LevelMeters } from "./LevelMeters";
import { MeetingDuration } from "./MeetingDuration";
import { MeetingStatusBadge } from "./MeetingStatusBadge";
import { MeetingSyncActions } from "./MeetingSyncActions";
import { SyncBadge } from "./SyncBadge";
import { TitleEditor } from "./TitleEditor";

interface MeetingHeaderProps {
  meeting: MeetingInfo;
  resuming: boolean;
  onResume: (id: string) => void;
  onDelete: () => void;
}

export const MeetingHeader: React.FC<MeetingHeaderProps> = ({
  meeting,
  resuming,
  onResume,
  onDelete,
}) => {
  const { t } = useTranslation();
  const isActive = useMeetingStore((s) => s.active?.id === meeting.id);
  const stopping = useMeetingStore((s) => s.stopping);
  const queueLen = useMeetingStore((s) => s.queueLen);
  const closeMeeting = useMeetingStore((s) => s.closeMeeting);

  const handleStop = async () => {
    const error = await useMeetingStore.getState().stopMeeting();
    if (error)
      toast.error(t("meetings.errors.stopFailed"), { description: error });
  };

  return (
    <div className="shrink-0 border-b border-mid-gray/20 bg-deep px-4 py-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label={t("meetings.actions.back")}
          title={t("meetings.actions.back")}
          onClick={closeMeeting}
          className="shrink-0 cursor-pointer rounded-md p-1 text-muted hover:bg-mid-gray/10 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
        >
          <ChevronLeft className="h-5 w-5" aria-hidden="true" />
        </button>
        <TitleEditor meetingId={meeting.id} title={meeting.title} />
        <MeetingDuration
          meeting={meeting}
          className="ms-auto shrink-0 text-lg text-text"
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <MeetingStatusBadge status={meeting.status} />
          <SyncBadge
            syncState={meeting.sync_state}
            syncError={meeting.sync_error}
          />
          <AudioStateNote audioState={meeting.audio_state} />
          {isActive && <LevelMeters captureMode={meeting.capture_mode} />}
          {isActive && queueLen > 0 && (
            <span className="text-xs text-muted">
              {t("meetings.view.queue", { count: queueLen })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isActive ? (
            <Button
              variant="danger"
              disabled={stopping}
              onClick={() => void handleStop()}
              className="flex items-center gap-1.5"
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              {stopping ? t("meetings.view.stopping") : t("meetings.view.stop")}
            </Button>
          ) : (
            <>
              <MeetingSyncActions meeting={meeting} />
              {isResumable(meeting) && (
                <Button
                  variant="primary"
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
                onClick={onDelete}
                className="flex items-center gap-1.5"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                {t("meetings.actions.delete")}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
