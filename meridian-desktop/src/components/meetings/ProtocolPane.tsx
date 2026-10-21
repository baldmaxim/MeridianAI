import React from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MarkdownBody } from "./MarkdownBody";

interface ProtocolPaneProps {
  markdown: string | null;
  /** The server's `finalization_status`. */
  status: string | null;
  loading: boolean;
  error: string | null;
  onReload: () => void;
  className?: string;
}

const STATUS_KEYS: Record<string, string> = {
  queued: "queued",
  running: "running",
  error: "error",
  disabled: "disabled",
  completed: "empty",
  partial: "empty",
  done: "empty",
};

/** The protocol as markdown, or the reason it is not there yet. */
export const ProtocolPane: React.FC<ProtocolPaneProps> = ({
  markdown,
  status,
  loading,
  error,
  onReload,
  className = "",
}) => {
  const { t } = useTranslation();

  if (markdown && markdown.trim()) {
    return (
      <div
        className={`min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3 ${className}`}
      >
        <MarkdownBody markdown={markdown} />
      </div>
    );
  }

  let message: string;
  if (loading) {
    message = t("meetings.protocol.loading");
  } else if (error) {
    message = `${t("meetings.errors.protocolFailed")}: ${error}`;
  } else {
    const key = STATUS_KEYS[status ?? ""] ?? "notStarted";
    message = t(`meetings.protocol.status.${key}`);
  }

  return (
    <div
      className={`flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 py-8 text-center ${className}`}
    >
      <p className={`text-sm ${error ? "text-error" : "text-muted"}`}>
        {message}
      </p>
      {!loading && (
        <Button
          size="sm"
          variant="secondary"
          onClick={onReload}
          className="flex items-center gap-1.5"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
          {t("meetings.protocol.reload")}
        </Button>
      )}
    </div>
  );
};
