import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type { Segment } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";
import {
  foreignLanguageBadge,
  formatDiarizedSpeaker,
} from "@/lib/utils/liveSegment";
import { useMeetingStore, type VoiceSide } from "@/stores/meetingStore";
import { VoiceMenu } from "./VoiceMenu";

interface SegmentRowProps {
  segment: Segment;
  animate: boolean;
  /** Palette class of the voice (`speaker-cN`); `null` — by side/channel. */
  speakerClass: string | null;
}

export interface SideStyle {
  label: string;
  text: string;
  bar: string;
}

export const SIDE_CLASSES: Record<string, SideStyle> = {
  mic: { label: "mic", text: "text-amber", bar: "bg-amber" },
  system: { label: "system", text: "text-info", bar: "bg-info" },
  mixed: { label: "mixed", text: "text-muted", bar: "bg-subtle" },
};

/** Style of a phrase whose side comes from its voice; `null` is neutral. */
export const VOICE_SIDE_CLASSES: Record<"self" | "opponent", SideStyle> = {
  self: SIDE_CLASSES.mic,
  opponent: SIDE_CLASSES.system,
};

export const SegmentRow: React.FC<SegmentRowProps> = ({
  segment,
  animate,
  speakerClass,
}) => {
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

  // The speaker the server told apart (online recognition) colors the phrase
  // like a voice does; its side stays in the caption.
  const serverSpeaker = voice ? null : segment.speaker;
  const colored = (voice ?? serverSpeaker) && speakerClass;
  // A diarized voice takes its speaker color (its side stays in the chip
  // caption); a phrase without a voice keeps the colors of its channel.
  const barClass = colored ? `speaker-bar ${speakerClass}` : side.bar;
  const nameClass = colored ? `speaker-name ${speakerClass}` : side.text;

  // A foreign phrase: the Russian translation is the main text, the original
  // goes under it, muted, with the language.
  const badge = foreignLanguageBadge(segment.language);
  const translation = segment.translation?.trim() || null;
  const mainText = translation ?? segment.text;
  const sideCaption =
    segment.channel === "mic" || segment.channel === "system"
      ? t(`meetings.speaker.${side.label}`)
      : null;
  const serverCaption = serverSpeaker
    ? [
        formatDiarizedSpeaker(
          serverSpeaker,
          t("meetings.speaker.prefix"),
          (count) => t("meetings.speaker.session", { count }),
        ),
        sideCaption,
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

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
        className={`w-0.5 shrink-0 rounded-full ${barClass}`}
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
            textClass={nameClass}
            onSelect={(value) => void handleSelect(value)}
          />
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <span className={`text-xs font-semibold ${nameClass}`}>
              {serverCaption ?? t(`meetings.speaker.${side.label}`)}
            </span>
            {badge && (
              <span className="rounded border border-border px-1 font-mono text-[10px] leading-4 text-muted">
                {badge}
              </span>
            )}
          </span>
        )}
        <p className="break-words text-sm text-text">{mainText}</p>
        {translation && translation !== segment.text && (
          <p className="break-words text-xs text-muted">
            <span className="font-mono">
              {badge
                ? t("meetings.transcript.original", { lang: badge })
                : t("meetings.transcript.originalNoLang")}
              :
            </span>{" "}
            {segment.text}
          </p>
        )}
      </div>
    </div>
  );
};
