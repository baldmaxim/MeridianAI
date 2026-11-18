import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ViewSegment } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";
import {
  buildSpeakerColors,
  speakerColorClass,
} from "@/lib/utils/speakerColors";
import { speakerLabel } from "@/lib/utils/transcriptionFormat";

interface ServerTranscriptPaneProps {
  segments: ViewSegment[];
}

/** Read-only phrases of a site meeting: time, speaker, text. */
export const ServerTranscriptPane: React.FC<ServerTranscriptPaneProps> = ({
  segments,
}) => {
  const { t } = useTranslation();
  const prefix = t("meetings.speaker.prefix");
  const colors = useMemo(
    () => buildSpeakerColors(segments.map((s) => s.speaker_label)),
    [segments],
  );
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
        {segments.map((segment, index) => {
          const color = speakerColorClass(colors, segment.speaker_label);
          return (
            <div key={index} className="flex gap-3">
              <span className="w-12 shrink-0 pt-0.5 text-end font-mono text-xs tabular-nums text-muted">
                {segment.start_time !== null
                  ? formatClock(segment.start_time)
                  : ""}
              </span>
              <span
                className={`w-0.5 shrink-0 rounded-full ${color ? `speaker-bar ${color}` : "bg-subtle"}`}
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <span
                  className={`text-xs font-semibold ${color ? `speaker-name ${color}` : "text-muted"}`}
                >
                  {segment.speaker_label
                    ? speakerLabel(segment.speaker_label, prefix)
                    : t("meetings.speaker.mixed")}
                </span>
                <p className="break-words text-sm text-text">{segment.text}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
