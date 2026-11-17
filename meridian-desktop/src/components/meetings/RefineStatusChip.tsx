import React from "react";
import { useTranslation } from "react-i18next";

interface RefineStatusChipProps {
  /** `null`/`skipped`: the draft from this computer is all there is. */
  status: string | null | undefined;
  error?: string | null;
}

type RefineKind = "draft" | "running" | "done" | "failed";

const toKind = (status: string | null | undefined): RefineKind => {
  switch (status) {
    case "pending":
    case "running":
      return "running";
    case "done":
      return "done";
    case "failed":
      return "failed";
    default:
      return "draft";
  }
};

const CHIP_CLASSES: Record<RefineKind, string> = {
  draft: "border-mid-gray/30 text-muted",
  running: "border-amber/40 text-amber",
  done: "border-success/40 text-success",
  failed: "border-error/40 text-error",
};

/** What became of the server's re-transcription of a meeting. */
export const RefineStatusChip: React.FC<RefineStatusChipProps> = ({
  status,
  error,
}) => {
  const { t } = useTranslation();
  const kind = toKind(status);
  return (
    <span
      title={kind === "failed" ? (error ?? undefined) : undefined}
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${CHIP_CLASSES[kind]}`}
    >
      {t(`meetings.refine.${kind}`)}
    </span>
  );
};
