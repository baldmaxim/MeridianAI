import React from "react";
import { useTranslation } from "react-i18next";
import { WordCorrectionThreshold } from "./WordCorrectionThreshold";
import { LogLevelSelector } from "./LogLevelSelector";
import { LiveLogViewer } from "./LiveLogViewer";
import { RecordingBuffer } from "./RecordingBuffer";
import { SettingsGroup } from "../../ui/SettingsGroup";
import { AlwaysOnMicrophone } from "../AlwaysOnMicrophone";
import { ClamshellMicrophoneSelector } from "../ClamshellMicrophoneSelector";
import {
  OnboardingPreview,
  type OnboardingPreviewStep,
} from "./OnboardingPreview";

interface DebugSettingsProps {
  onPreviewOnboarding?: (step: OnboardingPreviewStep) => void;
}

export const DebugSettings: React.FC<DebugSettingsProps> = ({
  onPreviewOnboarding,
}) => {
  const { t } = useTranslation();

  return (
    <div className="max-w-3xl w-full mx-auto space-y-6">
      <SettingsGroup title={t("settings.debug.title")}>
        <LogLevelSelector grouped={true} />
        {onPreviewOnboarding && (
          <OnboardingPreview
            onPreview={onPreviewOnboarding}
            descriptionMode="tooltip"
            grouped={true}
          />
        )}
        <WordCorrectionThreshold descriptionMode="tooltip" grouped={true} />
        <RecordingBuffer descriptionMode="tooltip" grouped={true} />
        <AlwaysOnMicrophone descriptionMode="tooltip" grouped={true} />
        <ClamshellMicrophoneSelector descriptionMode="tooltip" grouped={true} />
        <LiveLogViewer descriptionMode="tooltip" grouped={true} />
      </SettingsGroup>
    </div>
  );
};
