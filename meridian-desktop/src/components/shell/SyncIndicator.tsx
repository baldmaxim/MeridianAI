import React from "react";
import { useTranslation } from "react-i18next";
import { useSyncStore } from "@/stores/syncStore";

type IndicatorKind = "signedOut" | "offline" | "queued" | "sent";

const DOT_CLASSES: Record<IndicatorKind, string> = {
  signedOut: "bg-subtle",
  offline: "bg-error",
  queued: "bg-amber animate-pulse motion-reduce:animate-none",
  sent: "bg-success",
};

interface SyncIndicatorProps {
  /** Opens the account settings; used when nobody is signed in. */
  onOpenAccount: () => void;
}

/** Header status of the upload to the server; a click starts a pass now. */
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
      className="flex min-w-0 cursor-pointer items-center gap-2 rounded-full border border-border px-3 py-1 text-xs text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
    >
      <span
        className={`h-2 w-2 shrink-0 rounded-full transition-colors duration-200 ${DOT_CLASSES[kind]}`}
      />
      <span className="hidden max-w-36 truncate min-[900px]:inline">
        {label}
      </span>
    </button>
  );
};
