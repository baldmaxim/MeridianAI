import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type { Segment } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";
import { useMeetingStore, type VoiceSide } from "@/stores/meetingStore";
import { VoiceMenu } from "./VoiceMenu";

interface SegmentRowProps {
  segment: Segment;
  animate: boolean;
}

interface SideStyle {
  label: string;
  text: string;
  bar: string;
}

const SIDE_CLASSES: Record<string, SideStyle> = {
  mic: { label: "mic", text: "text-amber", bar: "bg-amber" },
  system: { label: "system", text: "text-info", bar: "bg-info" },
  mixed: { label: "mixed", text: "text-muted", bar: "bg-subtle" },
};

/** Style of a phrase whose side comes from its voice; `null` is neutral. */
const VOICE_SIDE_CLASSES: Record<"self" | "opponent", SideStyle> = {
  self: SIDE_CLASSES.mic,
  opponent: SIDE_CLASSES.system,
};

export const SegmentRow: React.FC<SegmentRowProps> = ({ segment, animate }) => {
  const { t } = useTranslation();
  const voice = segment.voice;
  const voiceSide = useMeetingStore((s): VoiceSide => {
    const side = s.voices.find((v) => v.label === voice)?.side;
    return side === "self" || side === "opponent" ? side : null;
  });
  const setVoiceSide = useMeetingStore((s) => s.setVoiceSide);

  const side = voice
    ? voiceSide
      ? VOICE_SIDE_CLASSES[voiceSide]
      : SIDE_CLASSES.mixed
    : (SIDE_CLASSES[segment.channel] ?? SIDE_CLASSES.mixed);

  const handleSelect = async (value: VoiceSide) => {
    if (!voice) return;
    const error = await setVoiceSide(voice, value);
    if (error) {
      toast.error(t("meetings.errors.voiceSideFailed"), { description: error });
    }
  };

  return (
    <div className={`flex gap-3 ${animate ? "meeting-enter" : ""}`}>
      <span className="w-12 shrink-0 pt-0.5 text-end font-mono text-xs tabular-nums text-muted">
        {formatClock(segment.start_time)}
      </span>
      <span
        className={`w-0.5 shrink-0 rounded-full ${side.bar}`}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        {voice ? (
          <VoiceMenu
            caption={
              voiceSide
                ? `${voice} · ${t(`meetings.voice.${voiceSide}`)}`
                : voice
            }
            voice={voice}
            side={voiceSide}
            textClass={side.text}
            onSelect={(value) => void handleSelect(value)}
          />
        ) : (
          <span className={`text-xs font-semibold ${side.text}`}>
            {t(`meetings.speaker.${side.label}`)}
          </span>
        )}
        <p className="break-words text-sm text-text">{segment.text}</p>
      </div>
    </div>
  );
};
