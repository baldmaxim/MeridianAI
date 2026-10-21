import React from "react";
import type { MeetingInfo } from "@/bindings";
import { useElapsedSeconds } from "@/hooks/useElapsedSeconds";
import { useMeetingStore } from "@/stores/meetingStore";
import { formatClock } from "@/lib/utils/meetingFormat";

interface MeetingDurationProps {
  meeting: MeetingInfo;
  className?: string;
}

/** Ticking clock for the recording meeting, stored duration otherwise. */
export const MeetingDuration: React.FC<MeetingDurationProps> = ({
  meeting,
  className = "",
}) => {
  const since = useMeetingStore((s) =>
    s.active?.id === meeting.id ? s.active.since : null,
  );
  const elapsed = useElapsedSeconds(since);
  const seconds = since === null ? meeting.duration_seconds : elapsed;
  return (
    <span className={`font-mono tabular-nums ${className}`}>
      {formatClock(seconds)}
    </span>
  );
};
