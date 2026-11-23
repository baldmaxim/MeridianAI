import React from "react";
import { useTranslation } from "react-i18next";
import { Dropdown } from "../ui/Dropdown";
import { SettingContainer } from "../ui/SettingContainer";
import { ResetButton } from "../ui/ResetButton";
import { useSettings } from "../../hooks/useSettings";

// Reset sits left of the field so every row's field shares one right edge.
const RESET_BUTTON_CLASS =
  "flex h-[32px] w-[32px] shrink-0 items-center justify-center";

interface MicrophoneSelectorProps {
  descriptionMode?: "inline" | "tooltip";
  grouped?: boolean;
}

export const MicrophoneSelector: React.FC<MicrophoneSelectorProps> = React.memo(
  ({ descriptionMode = "tooltip", grouped = false }) => {
    const { t } = useTranslation();
    const {
      getSetting,
      updateSetting,
      resetSetting,
      isUpdating,
      isLoading,
      audioDevices,
      refreshAudioDevices,
    } = useSettings();

    const selectedMicrophone =
      getSetting("selected_microphone") === "default"
        ? "Default"
        : getSetting("selected_microphone") || "Default";

    const handleMicrophoneSelect = async (deviceName: string) => {
      await updateSetting("selected_microphone", deviceName);
    };

    const handleReset = async () => {
      await resetSetting("selected_microphone");
    };

    const microphoneOptions = audioDevices.map((device) => ({
      value: device.name,
      label: device.name,
    }));

    return (
      <SettingContainer
        title={t("settings.sound.microphone.title")}
        description={t("settings.sound.microphone.description")}
        descriptionMode={descriptionMode}
        grouped={grouped}
      >
        <div className="flex items-center gap-1">
          <ResetButton
            onClick={handleReset}
            disabled={isUpdating("selected_microphone") || isLoading}
            className={RESET_BUTTON_CLASS}
          />
          <Dropdown
            options={microphoneOptions}
            selectedValue={selectedMicrophone}
            onSelect={handleMicrophoneSelect}
            placeholder={
              isLoading || audioDevices.length === 0
                ? t("settings.sound.microphone.loading")
                : t("settings.sound.microphone.placeholder")
            }
            disabled={
              isUpdating("selected_microphone") ||
              isLoading ||
              audioDevices.length === 0
            }
            onOpen={refreshAudioDevices}
          />
        </div>
      </SettingContainer>
    );
  },
);
