import type React from "react";
import type { AppSettings } from "@/bindings";
import {
  GeneralSettings,
  AdvancedSettings,
  AccountSettings,
  DebugSettings,
  AboutSettings,
  PostProcessingSettings,
  ModelsSettings,
} from "../settings";

interface SectionConfig {
  labelKey: string;
  component: React.ComponentType;
  enabled: (settings: AppSettings | null) => boolean;
}

/** Tabs of the settings screen, in display order. */
export const SECTIONS_CONFIG = {
  account: {
    labelKey: "shell.tabs.account",
    component: AccountSettings,
    enabled: () => true,
  },
  general: {
    labelKey: "shell.tabs.general",
    component: GeneralSettings,
    enabled: () => true,
  },
  models: {
    labelKey: "shell.tabs.models",
    component: ModelsSettings,
    enabled: () => true,
  },
  advanced: {
    labelKey: "shell.tabs.advanced",
    component: AdvancedSettings,
    enabled: () => true,
  },
  postprocessing: {
    labelKey: "shell.tabs.postProcessing",
    component: PostProcessingSettings,
    enabled: (settings) => settings?.post_process_enabled ?? false,
  },
  debug: {
    labelKey: "shell.tabs.debug",
    component: DebugSettings,
    enabled: (settings) => settings?.debug_mode ?? false,
  },
  about: {
    labelKey: "shell.tabs.about",
    component: AboutSettings,
    enabled: () => true,
  },
} as const satisfies Record<string, SectionConfig>;

export type SettingsSection = keyof typeof SECTIONS_CONFIG;
export type AppSection = "meetings" | "settings";
