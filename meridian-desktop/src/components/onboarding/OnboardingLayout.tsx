import React from "react";
import { useTranslation } from "react-i18next";
import { BrandWordmark } from "../shell/BrandMark";

interface OnboardingLayoutProps {
  children: React.ReactNode;
}

/** Step on the left, explanatory brand card on the right. */
export const OnboardingLayout: React.FC<OnboardingLayoutProps> = ({
  children,
}) => {
  const { t } = useTranslation();
  return (
    <div className="flex h-screen w-full bg-background">
      <div className="h-full min-w-0 flex-1 overflow-y-auto">{children}</div>
      <aside className="flex w-[300px] shrink-0 items-center justify-center border-s border-border bg-deep p-6">
        <div className="flex w-full flex-col items-start gap-4 rounded-xl border border-border bg-surface p-6">
          <BrandWordmark />
          <h2 className="font-display text-lg font-extrabold leading-snug text-text">
            {t("onboarding.aside.title")}
          </h2>
          <p className="text-sm leading-relaxed text-muted">
            {t("onboarding.aside.text")}
          </p>
        </div>
      </aside>
    </div>
  );
};
