import React from "react";
import { useTranslation } from "react-i18next";
import type { EntryStatusKind } from "@/lib/utils/library";

interface EntryStatusBadgeProps {
  kind: EntryStatusKind;
  /** The upload error, shown as a tooltip. */
  detail?: string | null;
}

const BADGE_CLASSES: Record<EntryStatusKind, string> = {
  recording: "border-transparent bg-error/15 text-error",
  interrupted: "border-transparent bg-amber/20 text-amber",
  pending: "border-border text-muted",
  sending: "border-amber/40 text-amber",
  error: "border-error/40 text-error",
  empty: "border-border text-subtle",
  onServer: "border-info/40 text-info",
  protocolReady: "border-transparent bg-success/15 text-success",
};

const LABEL_KEYS: Record<EntryStatusKind, string> = {
  recording: "meetings.status.recording",
  interrupted: "meetings.status.interrupted",
  pending: "meetings.sync.pending",
  sending: "meetings.library.status.sending",
  error: "meetings.sync.error",
  empty: "meetings.sync.empty",
  onServer: "meetings.library.status.onServer",
  protocolReady: "meetings.library.status.protocolReady",
};

/** Status chip of a library card. */
export const EntryStatusBadge: React.FC<EntryStatusBadgeProps> = ({
  kind,
  detail,
}) => {
  const { t } = useTranslation();
  const pulsing = kind === "recording" || kind === "sending";
  return (
    <span
      title={kind === "error" ? (detail ?? undefined) : undefined}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${BADGE_CLASSES[kind]}`}
    >
      {pulsing && (
        <span className="meeting-rec-dot h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {t(LABEL_KEYS[kind])}
    </span>
  );
};
