import React from "react";
import { useTranslation } from "react-i18next";
import {
  Cog,
  Cpu,
  FlaskConical,
  Info,
  Mic,
  Sparkles,
  User,
  Users,
} from "lucide-react";
import AppTextLogo from "./icons/AppTextLogo";
import { useSettings } from "../hooks/useSettings";
import { useMeetingStore } from "../stores/meetingStore";
import {
  GeneralSettings,
  AdvancedSettings,
  AccountSettings,
  DebugSettings,
  AboutSettings,
  PostProcessingSettings,
  ModelsSettings,
} from "./settings";

export type SettingsSection = keyof typeof SECTIONS_CONFIG;
export type SidebarSection = "meetings" | SettingsSection;

interface IconProps {
  width?: number | string;
  height?: number | string;
  size?: number | string;
  className?: string;
  [key: string]: any;
}

interface SectionConfig {
  labelKey: string;
  icon: React.ComponentType<IconProps>;
  component: React.ComponentType;
  enabled: (settings: any) => boolean;
}

export const SECTIONS_CONFIG = {
  account: {
    labelKey: "sidebar.account",
    icon: User,
    component: AccountSettings,
    enabled: () => true,
  },
  general: {
    labelKey: "sidebar.general",
    icon: Mic,
    component: GeneralSettings,
    enabled: () => true,
  },
  models: {
    labelKey: "sidebar.models",
    icon: Cpu,
    component: ModelsSettings,
    enabled: () => true,
  },
  advanced: {
    labelKey: "sidebar.advanced",
    icon: Cog,
    component: AdvancedSettings,
    enabled: () => true,
  },
  postprocessing: {
    labelKey: "sidebar.postProcessing",
    icon: Sparkles,
    component: PostProcessingSettings,
    enabled: (settings) => settings?.post_process_enabled ?? false,
  },
  debug: {
    labelKey: "sidebar.debug",
    icon: FlaskConical,
    component: DebugSettings,
    enabled: (settings) => settings?.debug_mode ?? false,
  },
  about: {
    labelKey: "sidebar.about",
    icon: Info,
    component: AboutSettings,
    enabled: () => true,
  },
} as const satisfies Record<string, SectionConfig>;

interface SidebarProps {
  activeSection: SidebarSection;
  onSectionChange: (section: SidebarSection) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeSection,
  onSectionChange,
}) => {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const isRecording = useMeetingStore((state) => state.active !== null);

  const availableSections = Object.entries(SECTIONS_CONFIG)
    .filter(([_, config]) => config.enabled(settings))
    .map(([id, config]) => ({ id: id as SettingsSection, ...config }));

  const itemClass = (isActive: boolean) =>
    `flex gap-2 items-center p-2 w-full rounded-lg cursor-pointer transition-colors ${
      isActive
        ? "bg-logo-primary/80"
        : "hover:bg-mid-gray/20 hover:opacity-100 opacity-85"
    }`;

  return (
    <div className="flex flex-col w-48 h-full border-e border-mid-gray/20 items-center px-2">
      <AppTextLogo width={120} className="m-4" />
      <div className="flex flex-col w-full items-center gap-1 pt-2 border-t border-mid-gray/20">
        <div
          className={itemClass(activeSection === "meetings")}
          onClick={() => onSectionChange("meetings")}
        >
          <Users width={24} height={24} className="shrink-0" />
          <p
            className="text-sm font-medium truncate"
            title={t("sidebar.meetings")}
          >
            {t("sidebar.meetings")}
          </p>
          {isRecording && (
            <span className="meeting-rec-dot ms-auto h-2 w-2 shrink-0 rounded-full bg-error" />
          )}
        </div>
      </div>
      <p className="w-full px-2 pt-4 pb-1 text-xs font-medium uppercase tracking-wide text-mid-gray">
        {t("sidebar.settingsGroup")}
      </p>
      <div className="flex flex-col w-full items-center gap-1 overflow-y-auto">
        {availableSections.map((section) => {
          const Icon = section.icon;

          return (
            <div
              key={section.id}
              className={itemClass(activeSection === section.id)}
              onClick={() => onSectionChange(section.id)}
            >
              <Icon width={24} height={24} className="shrink-0" />
              <p
                className="text-sm font-medium truncate"
                title={t(section.labelKey)}
              >
                {t(section.labelKey)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
};
