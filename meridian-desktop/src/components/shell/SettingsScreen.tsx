import React, { useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useSettings } from "@/hooks/useSettings";
import { DebugSettings, type OnboardingPreviewStep } from "../settings";
import { SECTIONS_CONFIG, type SettingsSection } from "./settingsSections";

interface SettingsScreenProps {
  tab: SettingsSection;
  onTabChange: (tab: SettingsSection) => void;
  onPreviewOnboarding: (step: OnboardingPreviewStep) => void;
}

const renderSettingsContent = (
  tab: SettingsSection,
  onPreviewOnboarding: (step: OnboardingPreviewStep) => void,
) => {
  if (tab === "debug") {
    return <DebugSettings onPreviewOnboarding={onPreviewOnboarding} />;
  }
  const ActiveComponent =
    SECTIONS_CONFIG[tab]?.component || SECTIONS_CONFIG.general.component;
  return <ActiveComponent />;
};

/** One settings screen behind the gear: title, pill tabs, centered content. */
export const SettingsScreen: React.FC<SettingsScreenProps> = ({
  tab,
  onTabChange,
  onPreviewOnboarding,
}) => {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const scrollRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [tab]);

  const tabs = (Object.keys(SECTIONS_CONFIG) as SettingsSection[]).filter(
    (id) => SECTIONS_CONFIG[id].enabled(settings),
  );

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[760px] flex-col gap-5 px-5 py-6">
        <h1 className="font-display text-2xl font-extrabold text-text">
          {t("shell.settingsTitle")}
        </h1>
        <div
          role="tablist"
          aria-label={t("shell.settingsTitle")}
          className="shell-tabs -mx-1 flex gap-2 overflow-x-auto px-1 py-1"
        >
          {tabs.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => onTabChange(id)}
              className={`shrink-0 cursor-pointer rounded-full border px-4 py-1.5 text-sm font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
                tab === id
                  ? "border-transparent bg-logo-primary text-on-accent"
                  : "border-border text-muted hover:bg-elevated hover:text-text"
              }`}
            >
              {t(SECTIONS_CONFIG[id].labelKey)}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-4">
          {renderSettingsContent(tab, onPreviewOnboarding)}
        </div>
      </div>
    </div>
  );
};
