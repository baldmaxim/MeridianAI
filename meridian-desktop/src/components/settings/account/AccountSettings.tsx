import React from "react";
import { useTranslation } from "react-i18next";
import { SettingsGroup } from "@/components/ui/SettingsGroup";
import { ToggleSwitch } from "@/components/ui/ToggleSwitch";
import { useSettings } from "@/hooks/useSettings";
import { useSyncStore } from "@/stores/syncStore";
import { AccountCard } from "./AccountCard";
import { LoginForm } from "./LoginForm";

export const AccountSettings: React.FC = () => {
  const { t } = useTranslation();
  const { getSetting, updateSetting, isUpdating } = useSettings();
  const account = useSyncStore((s) => s.account);
  const accountLoaded = useSyncStore((s) => s.accountLoaded);

  return (
    <div className="max-w-3xl w-full mx-auto space-y-6">
      {accountLoaded &&
        (account ? <AccountCard account={account} /> : <LoginForm />)}
      <SettingsGroup title={t("account.upload.title")}>
        <ToggleSwitch
          checked={getSetting("upload_audio") ?? true}
          onChange={(enabled) => updateSetting("upload_audio", enabled)}
          isUpdating={isUpdating("upload_audio")}
          label={t("account.upload.audio")}
          description={t("account.upload.audioDescription")}
          descriptionMode="inline"
          grouped={true}
        />
      </SettingsGroup>
    </div>
  );
};
