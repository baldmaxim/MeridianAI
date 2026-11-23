import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { PanelLeftClose, Users } from "lucide-react";
import type { MeetingInfo, MeetingVoice } from "@/bindings";
import { useSidePanelCollapsed } from "@/hooks/useSidePanelCollapsed";
import { useMeetingStore, type VoiceSide } from "@/stores/meetingStore";
import { MAX_PARTICIPANTS, MIN_PARTICIPANTS } from "./ParticipantsSelect";

const STORAGE_KEY = "meridian.meetingSpeakersCollapsed";
/** In a narrower window the panel starts collapsed. */
const NARROW_WINDOW_PX = 1100;

const COUNTS = Array.from(
  { length: MAX_PARTICIPANTS - MIN_PARTICIPANTS + 1 },
  (_, i) => MIN_PARTICIPANTS + i,
);

const SIDES: { side: VoiceSide; key: string; short: string }[] = [
  { side: "self", key: "self", short: "" },
  { side: "opponent", key: "opponent", short: "" },
  { side: null, key: "unknown", short: "?" },
];

const ICON_BUTTON =
  "flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none";

const sideOf = (voice: MeetingVoice): VoiceSide =>
  voice.side === "self" || voice.side === "opponent" ? voice.side : null;

interface SpeakersPanelProps {
  meeting: MeetingInfo;
}

/**
 * Column of a local meeting: how many people speak and whose each recognized
 * voice is (us / opponent / not sure). Collapses to a narrow strip.
 */
export const SpeakersPanel: React.FC<SpeakersPanelProps> = ({ meeting }) => {
  const { t } = useTranslation();
  const [collapsed, toggle] = useSidePanelCollapsed(
    STORAGE_KEY,
    window.innerWidth < NARROW_WINDOW_PX,
  );
  const voices = useMeetingStore((s) => s.voices);
  const setVoiceSide = useMeetingStore((s) => s.setVoiceSide);
  const setMaxSpeakers = useMeetingStore((s) => s.setMaxSpeakers);
  const isActive = useMeetingStore((s) => s.active?.id === meeting.id);
  const unassigned = voices.filter((v) => sideOf(v) === null).length;

  const handleSide = async (label: string, side: VoiceSide) => {
    const error = await setVoiceSide(label, side);
    if (error) {
      toast.error(t("meetings.errors.voiceSideFailed"), { description: error });
    }
  };

  const handleCount = async (value: string) => {
    if (value === "") return;
    const error = await setMaxSpeakers(meeting.id, Number(value));
    if (error) {
      toast.error(t("meetings.errors.maxSpeakersFailed"), {
        description: error,
      });
    }
  };

  if (collapsed) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-s border-mid-gray/40 bg-deep py-2">
        <button
          type="button"
          onClick={toggle}
          aria-label={t("meetings.speakers.expand")}
          title={t("meetings.speakers.expand")}
          className={`${ICON_BUTTON} relative`}
        >
          <Users className="h-[18px] w-[18px]" aria-hidden="true" />
          {unassigned > 0 && (
            <span
              aria-label={t("meetings.speakers.unassigned", {
                count: unassigned,
              })}
              className="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-logo-primary px-1 font-mono text-[10px] font-semibold leading-none text-on-accent"
            >
              {unassigned}
            </span>
          )}
        </button>
      </aside>
    );
  }

  const status =
    voices.length === 0
      ? null
      : unassigned === 0
        ? t("meetings.speakers.allAssigned")
        : t("meetings.speakers.unassigned", { count: unassigned });

  return (
    <aside
      aria-label={t("meetings.speakers.title")}
      className="flex min-h-0 w-60 shrink-0 flex-col border-s border-mid-gray/40 bg-deep"
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-2.5 py-1.5">
        <div className="min-w-0 flex-1">
          <h2 className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
            {t("meetings.speakers.title")}
          </h2>
          {status && (
            <p
              role="status"
              className={`truncate text-xs ${unassigned === 0 ? "text-success" : "text-muted"}`}
            >
              {status}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-label={t("meetings.speakers.collapse")}
          title={t("meetings.speakers.collapse")}
          className={ICON_BUTTON}
        >
          <PanelLeftClose
            className="h-[18px] w-[18px] rtl:rotate-180"
            aria-hidden="true"
          />
        </button>
      </div>
      <div className="shrink-0 border-b border-border px-2.5 py-2">
        <label className="flex items-center justify-between gap-2 text-sm">
          <span className="text-muted">
            {t("meetings.speakers.participants")}
          </span>
          <select
            value={meeting.max_speakers ?? ""}
            onChange={(e) => void handleCount(e.target.value)}
            className="min-h-8 rounded-md border border-mid-gray/60 bg-surface px-2 py-0.5 text-sm text-text focus:border-logo-primary focus:outline-none"
          >
            <option value="" disabled>
              {t("meetings.speakers.participantsNotSet")}
            </option>
            {COUNTS.map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
        </label>
        <p className="mt-1 text-[11px] leading-snug text-muted">
          {isActive
            ? t("meetings.speakers.applyHint")
            : t("meetings.speakers.applyHintStopped")}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2.5 py-2">
        {voices.length === 0 ? (
          <p className="mt-4 text-center text-xs text-muted">
            {t("meetings.speakers.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {voices.map((voice) => {
              const side = sideOf(voice);
              return (
                <li key={voice.label} className="meeting-enter">
                  <p className="truncate text-xs font-semibold text-text">
                    {voice.label}
                  </p>
                  <div
                    role="radiogroup"
                    aria-label={t("meetings.speakers.sideLabel", {
                      voice: voice.label,
                    })}
                    className="mt-0.5 flex rounded-md border border-border bg-elevated p-0.5"
                  >
                    {SIDES.map((option) => (
                      <button
                        key={option.key}
                        type="button"
                        role="radio"
                        aria-checked={side === option.side}
                        title={t(`meetings.voice.${option.key}`)}
                        onClick={() => {
                          if (side !== option.side) {
                            void handleSide(voice.label, option.side);
                          }
                        }}
                        className={`min-h-7 cursor-pointer rounded px-2 text-xs font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
                          option.side === null ? "w-8" : "flex-1"
                        } ${
                          side === option.side
                            ? "bg-logo-primary text-on-accent"
                            : "text-muted hover:text-text"
                        }`}
                      >
                        {option.short || t(`meetings.voice.${option.key}`)}
                      </button>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
};
