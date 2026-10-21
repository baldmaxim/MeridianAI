import React from "react";
import { useTranslation } from "react-i18next";
import { toSyncKind, type SyncKind } from "@/lib/utils/meetingFormat";

interface SyncBadgeProps {
  syncState: string;
  syncError?: string | null;
}

const BADGE_CLASSES: Record<SyncKind, string> = {
  pending: "border-mid-gray/30 text-muted",
  synced: "border-success/40 text-success",
  error: "border-error/40 text-error",
  empty: "border-mid-gray/30 text-subtle",
};

/** Upload state badge; unknown backend states render nothing. */
export const SyncBadge: React.FC<SyncBadgeProps> = ({
  syncState,
  syncError,
}) => {
  const { t } = useTranslation();
  const kind = toSyncKind(syncState);
  if (!kind) return null;
  return (
    <span
      title={
        kind === "error" || kind === "pending"
          ? (syncError ?? undefined)
          : undefined
      }
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${BADGE_CLASSES[kind]}`}
    >
      {t(`meetings.sync.${kind}`)}
    </span>
  );
};
