import React from "react";
import { useTranslation } from "react-i18next";
import { useSyncStore } from "@/stores/syncStore";

interface SignInHintProps {
  onOpenAccount: () => void;
}

/** Quiet notice above the list: recording works without an account. */
export const SignInHint: React.FC<SignInHintProps> = ({ onOpenAccount }) => {
  const { t } = useTranslation();
  const accountLoaded = useSyncStore((s) => s.accountLoaded);
  const signedIn = useSyncStore((s) => s.account !== null);
  if (!accountLoaded || signedIn) return null;

  return (
    <div className="mx-auto mb-3 flex max-w-3xl flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-mid-gray/20 bg-card px-3 py-2 text-sm text-muted">
      <p className="min-w-0">{t("account.hint.text")}</p>
      <button
        type="button"
        onClick={onOpenAccount}
        className="shrink-0 cursor-pointer text-amber underline-offset-2 hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
      >
        {t("account.hint.link")}
      </button>
    </div>
  );
};
