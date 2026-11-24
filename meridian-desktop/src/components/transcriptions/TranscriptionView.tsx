import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ArrowLeft, Copy } from "lucide-react";
import {
  commands,
  type TranscriptionDetail,
  type TranscriptSegment,
} from "@/bindings";
import { MarkdownBody } from "@/components/meetings/MarkdownBody";
import { AudioPlayerBar } from "@/components/shared/AudioPlayerBar";
import { Button } from "@/components/ui/Button";
import {
  hasTextSelection,
  useActiveSegment,
  useAudioPlayer,
  type IAudioPlayer,
} from "@/hooks/useAudioPlayer";
import {
  buildSpeakerColors,
  speakerColorClass,
} from "@/lib/utils/speakerColors";
import {
  formatTimestamp,
  speakerLabel,
  transcriptToText,
} from "@/lib/utils/transcriptionFormat";

type ViewTab = "protocol" | "transcript";

interface TranscriptListProps {
  segments: TranscriptSegment[];
  player: IAudioPlayer;
}

/** The phrases of the file; a click plays the recording from the phrase. */
const TranscriptList: React.FC<TranscriptListProps> = ({
  segments,
  player,
}) => {
  const { t } = useTranslation();
  const speaker = t("transcriptions.speaker");
  const colors = useMemo(
    () => buildSpeakerColors(segments.map((s) => s.speaker)),
    [segments],
  );
  const starts = useMemo(() => segments.map((s) => s.start), [segments]);
  const { active, rowRefs } = useActiveSegment(player, starts);
  const playable = player.url !== null;

  return (
    <ul className="mx-auto flex max-w-3xl flex-col gap-1">
      {segments.map((segment, index) => {
        const color = speakerColorClass(colors, segment.speaker);
        return (
          <li
            key={index}
            ref={(el) => {
              rowRefs.current[index] = el;
            }}
            onClick={
              playable
                ? (event) => {
                    if (!hasTextSelection(event.currentTarget))
                      player.seek(segment.start);
                  }
                : undefined
            }
            className={`rounded-e-lg border-s-2 py-1 ps-3 pe-2 ${
              color ? `speaker-border ${color}` : "border-border"
            } ${playable ? "cursor-pointer" : ""} ${
              index === active ? "bg-logo-primary/10" : ""
            }`}
          >
            <p className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
              <span className={color ? `speaker-name ${color}` : undefined}>
                {speakerLabel(segment.speaker, speaker)}
              </span>{" "}
              ·{" "}
              {playable ? (
                <button
                  type="button"
                  aria-label={t("audioPlayer.seekTo", {
                    time: formatTimestamp(segment.start),
                  })}
                  className="cursor-pointer text-logo-primary hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
                >
                  {formatTimestamp(segment.start)}
                </button>
              ) : (
                formatTimestamp(segment.start)
              )}
            </p>
            <p className="mt-0.5 whitespace-pre-wrap break-words text-sm text-text">
              {segment.text}
            </p>
          </li>
        );
      })}
    </ul>
  );
};

interface TranscriptionViewProps {
  id: string;
  onBack: () => void;
}

/** A finished file: the protocol and the transcript, with the recording to play. */
export const TranscriptionView: React.FC<TranscriptionViewProps> = ({
  id,
  onBack,
}) => {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<TranscriptionDetail | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  // `null`: the user has not chosen, the default applies.
  const [chosenTab, setChosenTab] = useState<ViewTab | null>(null);
  const player = useAudioPlayer(id, commands.transcriptionAudioUrl);

  useEffect(() => {
    let disposed = false;
    setDetail(null);
    setFailed(null);
    setChosenTab(null);
    void commands.transcriptionGet(id).then((result) => {
      if (disposed) return;
      if (result.status === "ok") setDetail(result.data);
      else setFailed(result.error);
    });
    return () => {
      disposed = true;
    };
  }, [id]);

  const protocol = detail?.protocol_markdown?.trim()
    ? detail.protocol_markdown
    : null;
  const tab: ViewTab = chosenTab ?? (protocol ? "protocol" : "transcript");
  const speaker = t("transcriptions.speaker");

  const copy = async () => {
    if (!detail) return;
    const text =
      tab === "protocol"
        ? (protocol ?? "")
        : transcriptToText(detail.segments, detail.text, speaker);
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t("transcriptions.copied"));
    } catch (e) {
      console.error("Failed to copy the text:", e);
      toast.error(t("transcriptions.copyFailed"));
    }
  };

  const tabs: { id: ViewTab; label: string }[] = [
    { id: "protocol", label: t("transcriptions.tabProtocol") },
    { id: "transcript", label: t("transcriptions.tabTranscript") },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-background px-4 py-3 sm:px-5">
        <Button variant="secondary" size="sm" onClick={onBack}>
          <span className="inline-flex items-center gap-1.5">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {t("transcriptions.back")}
          </span>
        </Button>
        <h1
          className="min-w-0 flex-1 truncate text-base font-semibold text-text"
          title={detail?.item.filename}
        >
          {detail?.item.filename ?? ""}
        </h1>
        <Button
          variant="primary"
          size="sm"
          disabled={!detail || (tab === "protocol" && !protocol)}
          onClick={() => void copy()}
        >
          <span className="inline-flex items-center gap-1.5">
            <Copy className="h-4 w-4" aria-hidden="true" />
            {t("transcriptions.copy")}
          </span>
        </Button>
      </div>
      <AudioPlayerBar player={player} />
      {detail && (
        <div
          role="tablist"
          aria-label={t("transcriptions.tabsLabel")}
          className="flex shrink-0 gap-1 border-b border-border bg-background px-4 sm:px-5"
        >
          {tabs.map((option) => (
            <button
              key={option.id}
              type="button"
              role="tab"
              aria-selected={tab === option.id}
              onClick={() => setChosenTab(option.id)}
              className={`min-h-11 min-w-24 cursor-pointer border-b-2 px-3 text-sm font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
                tab === option.id
                  ? "border-logo-primary text-text"
                  : "border-transparent text-muted hover:text-text"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1 select-text overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
        {failed !== null && (
          <p className="break-words text-sm text-error">{failed}</p>
        )}
        {detail && tab === "protocol" && (
          <div className="mx-auto max-w-3xl">
            {protocol ? (
              <MarkdownBody
                markdown={protocol}
                onTimecode={player.url ? player.seek : undefined}
                highlight
              />
            ) : (
              <p className="text-sm text-muted">
                {t("transcriptions.protocolEmpty")}
              </p>
            )}
          </div>
        )}
        {detail && tab === "transcript" && detail.segments.length === 0 && (
          <p className="whitespace-pre-wrap break-words text-sm text-text">
            {detail.text || t("transcriptions.emptyTranscript")}
          </p>
        )}
        {detail && tab === "transcript" && detail.segments.length > 0 && (
          <TranscriptList segments={detail.segments} player={player} />
        )}
      </div>
    </div>
  );
};
