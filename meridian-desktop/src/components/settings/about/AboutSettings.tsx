import React, { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { getVersion } from "@tauri-apps/api/app";
import { toast } from "sonner";
import { Button } from "../../ui/Button";
import { useMeetingStore } from "@/stores/meetingStore";
import { useUpdateStore } from "@/stores/updateStore";
import { SettingsGroup } from "../../ui/SettingsGroup";
import { SettingContainer } from "../../ui/SettingContainer";
import { AppDataDirectory } from "../AppDataDirectory";
import { AppLanguageSelector } from "../AppLanguageSelector";
import { ThemeSelector } from "../ThemeSelector";
import { AccentColorSelector } from "../AccentColorSelector";
import { LogDirectory } from "../debug";

export const AboutSettings: React.FC = () => {
  const { t } = useTranslation();
  const [version, setVersion] = useState("");
  const checking = useUpdateStore((s) => s.status === "checking");
  const checkForUpdates = useUpdateStore((s) => s.checkForUpdates);
  const pendingUpdate = useUpdateStore((s) =>
    s.status === "available" || s.status === "installing" ? s.update : null,
  );
  const installing = useUpdateStore((s) => s.status === "installing");
  const installUpdate = useUpdateStore((s) => s.installUpdate);
  const recording = useMeetingStore((s) => s.active !== null);

  const handleCheckUpdates = async () => {
    await checkForUpdates(false);
    const { status, error } = useUpdateStore.getState();
    if (status === "upToDate") {
      toast.success(t("update.check.upToDate"));
    } else if (error) {
      toast.error(t("update.check.failed"), {
        description: error ?? undefined,
      });
    }
  };

  useEffect(() => {
    const fetchVersion = async () => {
      try {
        const appVersion = await getVersion();
        setVersion(appVersion);
      } catch (error) {
        console.error("Failed to get app version:", error);
        setVersion("0.1.0");
      }
    };

    fetchVersion();
  }, []);

  return (
    <div className="max-w-3xl w-full mx-auto space-y-6">
      <SettingsGroup title={t("settings.about.title")}>
        <AppLanguageSelector descriptionMode="tooltip" grouped={true} />
        <ThemeSelector descriptionMode="tooltip" grouped={true} />
        <AccentColorSelector descriptionMode="tooltip" grouped={true} />
        <SettingContainer
          title={t("settings.about.version.title")}
          description={t("settings.about.version.description")}
          grouped={true}
        >
          {/* eslint-disable-next-line i18next/no-literal-string */}
          <span className="text-sm font-mono">v{version}</span>
        </SettingContainer>

        <SettingContainer
          title={t("update.check.title")}
          description={t("update.check.description")}
          grouped={true}
        >
          <Button
            variant="secondary"
            size="sm"
            disabled={checking}
            onClick={() => void handleCheckUpdates()}
          >
            {checking ? t("update.check.checking") : t("update.check.button")}
          </Button>
        </SettingContainer>

        {pendingUpdate && (
          <SettingContainer
            title={t("update.about.available", {
              version: pendingUpdate.version,
            })}
            description={
              recording
                ? t("update.recordingHint")
                : t("update.about.description")
            }
            grouped={true}
          >
            <Button
              size="sm"
              disabled={installing || recording}
              onClick={() => void installUpdate()}
            >
              {installing ? t("update.installing") : t("update.about.install")}
            </Button>
          </SettingContainer>
        )}

        <AppDataDirectory descriptionMode="tooltip" grouped={true} />
        <LogDirectory grouped={true} />
      </SettingsGroup>

      <SettingsGroup title={t("settings.about.acknowledgments.title")}>
        <SettingContainer
          title={t("settings.about.acknowledgments.ggml.title")}
          description={t("settings.about.acknowledgments.ggml.description")}
          grouped={true}
          layout="stacked"
        >
          <div className="text-sm text-mid-gray">
            {t("settings.about.acknowledgments.ggml.details")}
          </div>
        </SettingContainer>
      </SettingsGroup>
    </div>
  );
};
