import React from "react";
import { useTranslation } from "react-i18next";
import { FileAudio, X } from "lucide-react";
import type { TranscriptionItem } from "@/bindings";
import { formatFileSize } from "@/lib/utils/transcriptionFormat";

const CHIP_CLASSES: Record<string, string> = {
  queued: "bg-elevated text-muted",
  uploading: "bg-info/15 text-info",
  processing: "bg-amber/20 text-amber",
  done: "bg-success/15 text-success",
  error: "bg-error/15 text-error",
};

interface TranscriptionRowProps {
  item: TranscriptionItem;
  onOpen: (id: string) => void;
  onRemove: (id: string) => void;
}

/** A file of the list: name, size, time, status chip, remove button. */
export const TranscriptionRow: React.FC<TranscriptionRowProps> = ({
  item,
  onOpen,
  onRemove,
}) => {
  const { t, i18n } = useTranslation();
  const done = item.status === "done";
  const created = new Date(item.created_at);
  const meta = [
    item.size > 0
      ? formatFileSize(
          item.size,
          {
            b: t("transcriptions.units.b"),
            kb: t("transcriptions.units.kb"),
            mb: t("transcriptions.units.mb"),
            gb: t("transcriptions.units.gb"),
          },
          i18n.language,
        )
      : "",
    Number.isNaN(created.getTime())
      ? ""
      : new Intl.DateTimeFormat(i18n.language, {
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }).format(created),
  ]
    .filter(Boolean)
    .join(" · ");
  const chip = (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${CHIP_CLASSES[item.status] ?? CHIP_CLASSES.queued}`}
    >
      {t(`transcriptions.status.${item.status}`)}
    </span>
  );
  const body = (
    <>
      <FileAudio
        className="mt-0.5 h-5 w-5 shrink-0 text-muted"
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1">
        <span
          className="block truncate text-sm font-medium text-text"
          title={item.filename}
        >
          {item.filename}
        </span>
        <span className="mt-0.5 block text-xs text-muted">{meta}</span>
        {item.error && (
          <span
            className={`mt-1 block break-words text-xs ${
              item.status === "error" ? "text-error" : "text-muted"
            }`}
          >
            {item.error}
          </span>
        )}
      </span>
      {chip}
    </>
  );

  return (
    <li className="flex items-start gap-2 rounded-xl border border-border bg-card px-3 py-2.5">
      {done ? (
        <button
          type="button"
          onClick={() => onOpen(item.id)}
          className="flex min-w-0 flex-1 cursor-pointer items-start gap-3 rounded-lg text-start focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
        >
          {body}
        </button>
      ) : (
        <div className="flex min-w-0 flex-1 items-start gap-3">{body}</div>
      )}
      <button
        type="button"
        onClick={() => onRemove(item.id)}
        aria-label={t("transcriptions.remove", { name: item.filename })}
        title={t("transcriptions.removeTitle")}
        className="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </li>
  );
};
