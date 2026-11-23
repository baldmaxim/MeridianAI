import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown } from "../ui/Dropdown";
import { SettingContainer } from "../ui/SettingContainer";
import { ResetButton } from "../ui/ResetButton";
import { useSettings } from "../../hooks/useSettings";
import {
  LANGUAGES,
  recognitionLanguage,
  supportsLanguageCode,
} from "../../lib/constants/languages";

interface LanguageSelectorProps {
  descriptionMode?: "inline" | "tooltip";
  grouped?: boolean;
  supportedLanguages?: string[];
  // Whether the model can auto-detect language. Gates the "Auto" option:
  // must-pick models (no detection) omit it and force a concrete choice.
  supportsLanguageDetection?: boolean;
}

// Mirrors the matching logic of `effective_language` in
// src-tauri/src/managers/model.rs. The Rust function is authoritative for the
// *concrete* code the engine receives (e.g. `nb`); this resolves the canonical
// picker intent (e.g. `no`) so model switches preserve the user's language.
// Model codes such as `en-US` and `nb` resolve to their `en` / `no` entry.
const effectiveLanguage = (
  intent: string,
  supported: string[],
  supportsDetection: boolean,
): string => {
  if (supported.length === 0) return recognitionLanguage(intent);
  if (intent !== "auto" && supportsLanguageCode(supported, intent))
    return recognitionLanguage(intent);
  if (supportsDetection) return "auto";
  if (supportsLanguageCode(supported, "en")) return "en";
  return recognitionLanguage(supported[0]);
};

export const LanguageSelector: React.FC<LanguageSelectorProps> = ({
  descriptionMode = "tooltip",
  grouped = false,
  supportedLanguages,
  supportsLanguageDetection = true,
}) => {
  const { t } = useTranslation();
  const { getSetting, updateSetting, resetSetting, isUpdating } = useSettings();
  // The persisted *intent* (auto | code). What's actually used/shown is the
  // effective value resolved against the current model's capabilities.
  const intent = getSetting("selected_language") || "auto";
  const selectedLanguage = effectiveLanguage(
    intent,
    supportedLanguages ?? [],
    supportsLanguageDetection,
  );

  const availableLanguages = useMemo(() => {
    if (!supportedLanguages || supportedLanguages.length === 0)
      return LANGUAGES;
    return LANGUAGES.filter((lang) =>
      lang.value === "auto"
        ? supportsLanguageDetection
        : supportsLanguageCode(supportedLanguages, lang.value),
    );
  }, [supportedLanguages, supportsLanguageDetection]);

  const languageOptions = useMemo(
    () =>
      availableLanguages.map((language) => ({
        value: language.value,
        label: language.label,
      })),
    [availableLanguages],
  );

  const handleLanguageSelect = async (languageCode: string) => {
    await updateSetting("selected_language", languageCode);
  };

  const handleReset = async () => {
    await resetSetting("selected_language");
  };

  return (
    <SettingContainer
      title={t("settings.general.language.title")}
      description={t("settings.general.language.description")}
      descriptionMode={descriptionMode}
      grouped={grouped}
    >
      <div className="flex items-center gap-1">
        <ResetButton
          onClick={handleReset}
          disabled={isUpdating("selected_language")}
          className="flex h-[32px] w-[32px] shrink-0 items-center justify-center"
        />
        <Dropdown
          options={languageOptions}
          selectedValue={selectedLanguage}
          onSelect={handleLanguageSelect}
          placeholder={t("settings.general.language.auto")}
          disabled={isUpdating("selected_language")}
          searchable
          searchPlaceholder={t("settings.general.language.searchPlaceholder")}
          emptyLabel={t("settings.general.language.noResults")}
          ariaLabel={t("settings.general.language.title")}
        />
      </div>
      {isUpdating("selected_language") && (
        <div className="absolute inset-0 bg-mid-gray/10 rounded flex items-center justify-center">
          <div className="w-4 h-4 border-2 border-logo-primary border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}
    </SettingContainer>
  );
};
