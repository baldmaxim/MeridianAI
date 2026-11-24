import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getVersion } from "@tauri-apps/api/app";
import { BUNDLED_RELEASES } from "@/lib/changelog";
import { SettingsGroup } from "../../ui/SettingsGroup";

export const ChangelogSettings: React.FC = () => {
  const { t } = useTranslation();
  const [installed, setInstalled] = useState("");

  useEffect(() => {
    getVersion()
      .then(setInstalled)
      .catch((error) => console.error("Failed to get app version:", error));
  }, []);

  return (
    <div className="max-w-3xl w-full mx-auto space-y-6">
      <SettingsGroup title={t("settings.changelog.title")}>
        {BUNDLED_RELEASES.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">
            {t("settings.changelog.empty")}
          </p>
        ) : (
          BUNDLED_RELEASES.map((release) => (
            <div key={release.version} className="px-4 py-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                {/* eslint-disable-next-line i18next/no-literal-string */}
                <span className="text-sm font-mono font-medium">
                  v{release.version}
                </span>
                <span className="text-xs font-mono text-muted">
                  {release.date}
                </span>
                {release.version === installed && (
                  <span className="inline-flex items-center rounded-full bg-success/20 px-2 py-0.5 text-xs font-medium text-success">
                    {t("settings.changelog.installed")}
                  </span>
                )}
              </div>
              <ul className="list-disc space-y-1 pl-5 text-sm text-text">
                {release.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ))
        )}
      </SettingsGroup>
    </div>
  );
};
