import React from "react";
import { useTranslation } from "react-i18next";
import { useSyncStore } from "@/stores/syncStore";

type IndicatorKind = "signedOut" | "offline" | "queued" | "sent";

const DOT_CLASSES: Record<IndicatorKind, string> = {
  signedOut: "bg-mid-gray/60",
  offline: "bg-error",
  queued: "bg-amber animate-pulse motion-reduce:animate-none",
  sent: "bg-success",
};

interface SyncIndicatorProps {
  /** Opens the account settings; used when nobody is signed in. */
  onOpenAccount: () => void;
}

/** Footer status of the upload to the server; a click starts a pass now. */
export const SyncIndicator: React.FC<SyncIndicatorProps> = ({
  onOpenAccount,
}) => {
  const { t } = useTranslation();
  const account = useSyncStore((s) => s.account);
  const accountLoaded = useSyncStore((s) => s.accountLoaded);
  const status = useSyncStore((s) => s.status);
  const syncNow = useSyncStore((s) => s.syncNow);

  if (!accountLoaded || !status) return null;

  const pending = status.pending_count;
  let kind: IndicatorKind;
  if (!account) kind = "signedOut";
  else if (!status.online && status.last_error) kind = "offline";
  else if (pending > 0 || status.running) kind = "queued";
  else kind = "sent";

  const label =
    kind === "queued"
      ? t("sync.indicator.queued", { count: pending })
      : t(`sync.indicator.${kind}`);
  const title =
    kind === "offline" && status.last_error ? status.last_error : label;

  return (
    <button
      type="button"
      title={title}
      onClick={() => (account ? void syncNow() : onOpenAccount())}
      className="flex cursor-pointer items-center gap-2 transition-colors hover:text-text/80 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
    >
      <span
        className={`h-2 w-2 shrink-0 rounded-full transition-colors duration-200 ${DOT_CLASSES[kind]}`}
      />
      <span className="max-w-48 truncate">{label}</span>
    </button>
  );
};
