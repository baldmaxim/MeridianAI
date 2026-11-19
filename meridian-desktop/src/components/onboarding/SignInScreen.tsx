import React from "react";
import { useTranslation } from "react-i18next";
import { commands } from "@/bindings";
import { BrowserLogin } from "@/components/settings/account/BrowserLogin";
import { BrandWordmark } from "../shell/BrandMark";

interface SignInScreenProps {
  onSkip: () => void;
}

/** First screen of a signed-out start: browser sign-in or continue without it. */
export const SignInScreen: React.FC<SignInScreenProps> = ({ onSkip }) => {
  const { t } = useTranslation();

  const handleSkip = () => {
    // A browser sign-in may be waiting for the user: drop it before leaving.
    void commands.accountBrowserLoginCancel();
    onSkip();
  };

  return (
    <div className="flex h-screen w-full items-center justify-center overflow-y-auto bg-background p-6">
      <div className="flex w-full max-w-md flex-col gap-6 rounded-xl border border-border bg-surface p-8">
        <BrandWordmark />
        <div className="flex flex-col gap-2">
          <h1 className="font-display text-xl font-extrabold leading-snug text-text">
            {t("signIn.title")}
          </h1>
          <p className="text-sm leading-relaxed text-muted">
            {t("signIn.text")}
          </p>
        </div>
        <BrowserLogin variant="plain" />
        <div className="flex flex-col items-start gap-1 border-t border-border pt-4">
          <button
            type="button"
            onClick={handleSkip}
            className="min-h-11 cursor-pointer text-sm font-medium text-text underline-offset-2 hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
          >
            {t("signIn.skip")}
          </button>
          <p className="text-xs text-muted">{t("signIn.skipHint")}</p>
        </div>
      </div>
    </div>
  );
};
