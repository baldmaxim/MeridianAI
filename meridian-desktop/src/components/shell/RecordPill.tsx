import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useMeetingStore } from "@/stores/meetingStore";
import { MeetingDuration } from "../meetings/MeetingDuration";
import { LevelMeters } from "../meetings/LevelMeters";

interface RecordPillProps {
  onOpenMeeting: (meetingId: string) => void;
}

/** Live recording status in the header: visible on every screen. */
export const RecordPill: React.FC<RecordPillProps> = ({ onOpenMeeting }) => {
  const { t } = useTranslation();
  const active = useMeetingStore((s) => s.active);
  const meeting = useMeetingStore((s) =>
    s.active ? (s.meetings.find((m) => m.id === s.active?.id) ?? null) : null,
  );
  const stopping = useMeetingStore((s) => s.stopping);

  if (!active) return null;

  const handleStop = async () => {
    const error = await useMeetingStore.getState().stopMeeting();
    if (error) {
      toast.error(t("meetings.errors.stopFailed"), { description: error });
    }
  };

  const title = meeting?.title.trim() || t("shell.record.untitled");

  return (
    <div className="flex min-w-0 items-center gap-1 rounded-full border border-error/40 bg-error/10 py-1 ps-1 pe-1">
      <button
        type="button"
        onClick={() => onOpenMeeting(active.id)}
        title={t("shell.record.open")}
        aria-label={t("shell.record.openNamed", { title })}
        className="flex min-w-0 cursor-pointer items-center gap-2.5 rounded-full py-0.5 ps-2.5 pe-2 transition-colors duration-200 hover:bg-error/10 focus:outline-none focus-visible:ring-1 focus-visible:ring-error motion-reduce:transition-none"
      >
        <span className="meeting-rec-dot h-2 w-2 shrink-0 rounded-full bg-error" />
        {meeting && (
          <MeetingDuration
            meeting={meeting}
            className="shrink-0 text-xs font-medium text-text"
          />
        )}
        <span className="max-w-36 truncate text-xs font-medium text-text">
          {title}
        </span>
        {meeting && (
          <span className="hidden min-[1180px]:block">
            <LevelMeters captureMode={meeting.capture_mode} />
          </span>
        )}
      </button>
      <button
        type="button"
        disabled={stopping}
        onClick={() => void handleStop()}
        className="shrink-0 cursor-pointer rounded-full bg-error px-3 py-1 text-xs font-semibold text-background transition-opacity duration-200 hover:opacity-85 focus:outline-none focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
      >
        {stopping ? t("meetings.view.stopping") : t("meetings.view.stop")}
      </button>
    </div>
  );
};
