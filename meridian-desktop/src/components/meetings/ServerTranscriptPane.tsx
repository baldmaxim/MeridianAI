import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ViewSegment } from "@/bindings";
import {
  hasTextSelection,
  useActiveSegment,
  type IAudioPlayer,
} from "@/hooks/useAudioPlayer";
import { formatClock } from "@/lib/utils/meetingFormat";
import {
  buildSpeakerColors,
  speakerColorClass,
} from "@/lib/utils/speakerColors";
import { speakerLabel } from "@/lib/utils/transcriptionFormat";

const NO_PLAYER: IAudioPlayer = {
  audioRef: { current: null },
  url: null,
  seek: () => undefined,
  handleError: () => undefined,
};

interface ServerTranscriptPaneProps {
  segments: ViewSegment[];
  /** Given (and with audio): a click on a phrase plays the recording from it. */
  player?: IAudioPlayer;
}

/** Read-only phrases of a site meeting: time, speaker, text. */
export const ServerTranscriptPane: React.FC<ServerTranscriptPaneProps> = ({
  segments,
  player,
}) => {
  const { t } = useTranslation();
  const starts = useMemo(() => segments.map((s) => s.start_time), [segments]);
  const { active, rowRefs } = useActiveSegment(player ?? NO_PLAYER, starts);
  const seek = player?.url ? player.seek : null;
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
      <div className="flex flex-col gap-1">
        {segments.map((segment, index) => {
          const color = speakerColorClass(colors, segment.speaker_label);
          const start = segment.start_time;
          const playable = seek !== null && start !== null;
          return (
            <div
              key={index}
              ref={(el) => {
                rowRefs.current[index] = el;
              }}
              onClick={
                playable
                  ? (event) => {
                      if (!hasTextSelection(event.currentTarget)) seek(start);
                    }
                  : undefined
              }
              className={`-mx-2 flex gap-3 rounded-lg px-2 py-1 ${
                playable ? "cursor-pointer" : ""
              } ${index === active ? "bg-logo-primary/10" : ""}`}
            >
              {playable ? (
                <button
                  type="button"
                  aria-label={t("audioPlayer.seekTo", {
                    time: formatClock(start),
                  })}
                  className="w-12 shrink-0 cursor-pointer pt-0.5 text-end font-mono text-xs tabular-nums text-logo-primary hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
                >
                  {formatClock(start)}
                </button>
              ) : (
                <span className="w-12 shrink-0 pt-0.5 text-end font-mono text-xs tabular-nums text-muted">
                  {start !== null ? formatClock(start) : ""}
                </span>
              )}
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
