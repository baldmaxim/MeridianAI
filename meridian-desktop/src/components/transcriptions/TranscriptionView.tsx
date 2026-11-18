import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ArrowLeft, Copy } from "lucide-react";
import { commands, type TranscriptionDetail } from "@/bindings";
import { Button } from "@/components/ui/Button";
import {
  buildSpeakerColors,
  speakerColorClass,
} from "@/lib/utils/speakerColors";
import {
  formatTimestamp,
  speakerLabel,
  transcriptToText,
} from "@/lib/utils/transcriptionFormat";

interface TranscriptionViewProps {
  id: string;
  onBack: () => void;
}

/** The transcript of a finished file: phrases with speaker and time. */
export const TranscriptionView: React.FC<TranscriptionViewProps> = ({
  id,
  onBack,
}) => {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<TranscriptionDetail | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    setDetail(null);
    setFailed(null);
    void commands.transcriptionGet(id).then((result) => {
      if (disposed) return;
      if (result.status === "ok") setDetail(result.data);
      else setFailed(result.error);
    });
    return () => {
      disposed = true;
    };
  }, [id]);

  const speaker = t("transcriptions.speaker");
  const colors = useMemo(
    () => buildSpeakerColors(detail?.segments.map((s) => s.speaker) ?? []),
    [detail],
  );

  const copy = async () => {
    if (!detail) return;
    try {
      await navigator.clipboard.writeText(
        transcriptToText(detail.segments, detail.text, speaker),
      );
      toast.success(t("transcriptions.copied"));
    } catch (e) {
      console.error("Failed to copy the transcript:", e);
      toast.error(t("transcriptions.copyFailed"));
    }
  };

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
          disabled={!detail}
          onClick={() => void copy()}
        >
          <span className="inline-flex items-center gap-1.5">
            <Copy className="h-4 w-4" aria-hidden="true" />
            {t("transcriptions.copy")}
          </span>
        </Button>
      </div>
      <div className="min-h-0 flex-1 select-text overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
        {failed !== null && (
          <p className="break-words text-sm text-error">{failed}</p>
        )}
        {detail && detail.segments.length === 0 && (
          <p className="whitespace-pre-wrap break-words text-sm text-text">
            {detail.text || t("transcriptions.emptyTranscript")}
          </p>
        )}
        {detail && detail.segments.length > 0 && (
          <ul className="mx-auto flex max-w-3xl flex-col gap-3">
            {detail.segments.map((segment, index) => {
              const color = speakerColorClass(colors, segment.speaker);
              return (
                <li
                  key={index}
                  className={`border-s-2 ps-3 ${color ? `speaker-border ${color}` : "border-border"}`}
                >
                  <p className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                    <span
                      className={color ? `speaker-name ${color}` : undefined}
                    >
                      {speakerLabel(segment.speaker, speaker)}
                    </span>{" "}
                    · {formatTimestamp(segment.start)}
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap break-words text-sm text-text">
                    {segment.text}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};
