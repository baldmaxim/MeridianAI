import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type { ViewSegment } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";
import { speakerLabel } from "@/lib/utils/transcriptionFormat";
import { useMeetingStore, type VoiceSide } from "@/stores/meetingStore";
import { VoiceMenu } from "./VoiceMenu";

interface RefinedSegmentRowProps {
  segment: ViewSegment;
  /** Palette class of the speaker (`speaker-cN`); `null` — neutral. */
  speakerClass: string | null;
}

/**
 * A phrase of the server's refined transcript. A label that is a voice of this
 * meeting ("Голос N") opens the same menu as in the draft; others are plain.
 */
export const RefinedSegmentRow: React.FC<RefinedSegmentRowProps> = ({
  segment,
  speakerClass,
}) => {
  const { t } = useTranslation();
  const label = segment.speaker_label;
  const known = useMeetingStore((s) =>
    label ? s.voices.some((v) => v.label === label) : false,
  );
  const voiceSide = useMeetingStore((s): VoiceSide => {
    const side = s.voices.find((v) => v.label === label)?.side;
    return side === "self" || side === "opponent" ? side : null;
  });
  const setVoiceSide = useMeetingStore((s) => s.setVoiceSide);

  const handleSelect = async (value: VoiceSide) => {
    if (!label) return;
    const error = await setVoiceSide(label, value);
    if (error) {
      toast.error(t("meetings.errors.voiceSideFailed"), { description: error });
    }
  };

  return (
    <div className="flex gap-2">
      <span className="w-12 shrink-0 pt-0.5 text-end font-mono text-xs tabular-nums text-muted">
        {segment.start_time !== null ? formatClock(segment.start_time) : ""}
      </span>
      <span
        className={`w-0.5 shrink-0 rounded-full ${speakerClass ? `speaker-bar ${speakerClass}` : "bg-subtle"}`}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        {label && known ? (
          <VoiceMenu
            caption={
              voiceSide
                ? `${label} · ${t(`meetings.voice.${voiceSide}`)}`
                : label
            }
            voice={label}
            side={voiceSide}
            textClass={
              speakerClass ? `speaker-name ${speakerClass}` : "text-muted"
            }
            onSelect={(value) => void handleSelect(value)}
          />
        ) : (
          <span
            className={`text-xs font-semibold ${speakerClass ? `speaker-name ${speakerClass}` : "text-muted"}`}
          >
            {label
              ? speakerLabel(label, t("meetings.speaker.prefix"))
              : t("meetings.speaker.mixed")}
          </span>
        )}
        <p className="break-words text-sm text-text">{segment.text}</p>
      </div>
    </div>
  );
};
