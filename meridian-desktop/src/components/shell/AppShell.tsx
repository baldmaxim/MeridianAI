import React from "react";
import type { OnboardingPreviewStep } from "../settings";
import { MeetingsScreen } from "../meetings/MeetingsScreen";
import { AppHeader } from "./AppHeader";
import { IconRail } from "./IconRail";
import { SettingsScreen } from "./SettingsScreen";
import type { AppSection, SettingsSection } from "./settingsSections";

interface AppShellProps {
  section: AppSection;
  settingsTab: SettingsSection;
  onSectionChange: (section: AppSection) => void;
  onSettingsTabChange: (tab: SettingsSection) => void;
  /** Opens the settings screen on the given tab. */
  onOpenSettingsTab: (tab: SettingsSection) => void;
  /** Shows the meetings screen with this meeting open. */
  onOpenMeeting: (meetingId: string) => void;
  onPreviewOnboarding: (step: OnboardingPreviewStep) => void;
}

/** Window frame: icon rail on the left, header on top, the active screen. */
export const AppShell: React.FC<AppShellProps> = ({
  section,
  settingsTab,
  onSectionChange,
  onSettingsTabChange,
  onOpenSettingsTab,
  onOpenMeeting,
  onPreviewOnboarding,
}) => (
  <div className="flex h-screen select-none cursor-default bg-background">
    <IconRail
      section={section}
      settingsTab={settingsTab}
      onOpenMeetings={() => onSectionChange("meetings")}
      onOpenSettings={() =>
        onOpenSettingsTab(settingsTab === "account" ? "general" : settingsTab)
      }
      onOpenAccount={() => onOpenSettingsTab("account")}
    />
    <div className="flex min-w-0 flex-1 flex-col">
      <AppHeader
        onOpenAccount={() => onOpenSettingsTab("account")}
        onOpenMeeting={onOpenMeeting}
      />
      <main className="min-h-0 flex-1 overflow-hidden">
        {section === "meetings" ? (
          <MeetingsScreen
            onOpenModelSettings={() => onOpenSettingsTab("models")}
            onOpenAccount={() => onOpenSettingsTab("account")}
          />
        ) : (
          <SettingsScreen
            tab={settingsTab}
            onTabChange={onSettingsTabChange}
            onPreviewOnboarding={onPreviewOnboarding}
          />
        )}
      </main>
    </div>
  </div>
);
