import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { RecognitionMode } from "@/bindings";
import { useSettings } from "@/hooks/useSettings";
import { Dropdown, type DropdownOption } from "@/components/ui/Dropdown";
import { SettingContainer } from "@/components/ui/SettingContainer";

interface RecognitionModeSelectorProps {
  descriptionMode?: "tooltip" | "inline";
  grouped?: boolean;
}

/** Where the live text of a meeting comes from: the server or the local model. */
export const RecognitionModeSelector: React.FC<
  RecognitionModeSelectorProps
> = ({ descriptionMode = "tooltip", grouped = false }) => {
  const { t } = useTranslation();
  const { getSetting, updateSetting, isUpdating } = useSettings();
  const mode = getSetting("recognition_mode") ?? "online";

  const options = useMemo<DropdownOption[]>(
    () => [
      { value: "online", label: t("settings.recognition.options.online") },
      { value: "local", label: t("settings.recognition.options.local") },
    ],
    [t],
  );

  return (
    <SettingContainer
      title={t("settings.recognition.title")}
      description={t("settings.recognition.description")}
      descriptionMode={descriptionMode}
      grouped={grouped}
      layout="horizontal"
    >
      <Dropdown
        options={options}
        selectedValue={mode}
        onSelect={(value) =>
          updateSetting("recognition_mode", value as RecognitionMode)
        }
        disabled={isUpdating("recognition_mode")}
      />
    </SettingContainer>
  );
};
