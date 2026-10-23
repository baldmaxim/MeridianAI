import React from "react";
import { useTranslation } from "react-i18next";
import { FileText, Loader2, X } from "lucide-react";
import type { QueuedDocument } from "@/bindings";

interface QueuedSourceRowProps {
  item: QueuedDocument;
  onRemove: (queueId: number) => void;
}

/** A file that has not reached the server: waiting, uploading, or refused. */
export const QueuedSourceRow: React.FC<QueuedSourceRowProps> = ({
  item,
  onRemove,
}) => {
  const { t } = useTranslation();
  const uploading = item.state === "uploading";
  const failed = item.state === "error";

  return (
    <li className="flex items-start gap-2.5 rounded-xl border border-dashed border-border bg-card px-2.5 py-2">
      {uploading ? (
        <Loader2
          className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-logo-primary motion-reduce:animate-none"
          aria-hidden="true"
        />
      ) : (
        <FileText
          className="mt-0.5 h-4 w-4 shrink-0 text-muted"
          aria-hidden="true"
        />
      )}
      <div className="min-w-0 flex-1">
        <p
          className="truncate text-sm font-medium text-text"
          title={item.original_name}
        >
          {item.original_name}
        </p>
        {failed ? (
          <p className="mt-0.5 break-words text-xs text-error">{item.error}</p>
        ) : (
          <p className="mt-0.5 text-xs text-muted">
            {uploading
              ? t("meetings.sources.queue.uploading")
              : t("meetings.sources.queue.waiting")}
          </p>
        )}
      </div>
      {!uploading && (
        <button
          type="button"
          onClick={() => onRemove(item.id)}
          aria-label={t("meetings.sources.queue.remove")}
          title={t("meetings.sources.queue.remove")}
          className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
    </li>
  );
};
