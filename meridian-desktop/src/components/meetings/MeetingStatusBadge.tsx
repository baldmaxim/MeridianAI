import React from "react";
import { useTranslation } from "react-i18next";
import type { MeetingStatus } from "@/bindings";

interface MeetingStatusBadgeProps {
  status: MeetingStatus;
}

const BADGE_CLASSES: Record<MeetingStatus, string> = {
  recording: "bg-error/15 text-error",
  interrupted: "bg-amber/20 text-amber",
  stopped: "bg-elevated text-muted",
};

export const MeetingStatusBadge: React.FC<MeetingStatusBadgeProps> = ({
  status,
}) => {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${BADGE_CLASSES[status]}`}
    >
      {status === "recording" && (
        <span className="meeting-rec-dot h-1.5 w-1.5 rounded-full bg-error" />
      )}
      {t(`meetings.status.${status}`)}
    </span>
  );
};
