import React from "react";
import { useTranslation } from "react-i18next";
import type { ViewSegment } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";

interface ServerTranscriptPaneProps {
  segments: ViewSegment[];
}

/** Read-only phrases of a site meeting: time, speaker, text. */
export const ServerTranscriptPane: React.FC<ServerTranscriptPaneProps> = ({
  segments,
}) => {
  const { t } = useTranslation();
  if (segments.length === 0) {
    return (
      <p className="px-6 py-8 text-center text-sm text-muted">
        {t("meetings.transcript.empty")}
      </p>
    );
  }
  return (
    <div className="min-h-0 flex-1 select-text overflow-y-auto overscroll-contain px-4 py-3">
      <div className="flex flex-col gap-3">
        {segments.map((segment, index) => (
          <div key={index} className="flex gap-3">
            <span className="w-12 shrink-0 pt-0.5 text-end font-mono text-xs tabular-nums text-muted">
              {segment.start_time !== null
                ? formatClock(segment.start_time)
                : ""}
            </span>
            <span
              className="w-0.5 shrink-0 rounded-full bg-subtle"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <span className="text-xs font-semibold text-muted">
                {segment.speaker_label || t("meetings.speaker.mixed")}
              </span>
              <p className="break-words text-sm text-text">{segment.text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
