import React, { useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Moon, Sun } from "lucide-react";
import { useSettings } from "@/hooks/useSettings";
import { applyTheme, getEffectiveTheme } from "@/lib/utils/theme";

/** `data-theme` on <html> is the effective theme; watch it so the icon stays in sync. */
const subscribeToTheme = (onChange: () => void): (() => void) => {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
};

/** Header button: flips the effective theme and stores the explicit choice. */
export const ThemeToggle: React.FC = () => {
  const { t } = useTranslation();
  const { updateSetting } = useSettings();
  const effective = useSyncExternalStore(subscribeToTheme, getEffectiveTheme);
  const isDark = effective === "dark";

  const label = isDark ? t("shell.theme.toLight") : t("shell.theme.toDark");

  const handleClick = () => {
    const next = isDark ? "light" : "dark";
    applyTheme(next);
    void updateSetting("theme", next);
  };

  const iconClass =
    "absolute inset-0 m-auto h-[18px] w-[18px] transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none";

  return (
    <button
      type="button"
      onClick={handleClick}
      title={label}
      aria-label={label}
      className="relative h-8 w-8 shrink-0 cursor-pointer rounded-full text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
    >
      <Sun
        aria-hidden="true"
        strokeWidth={1.8}
        className={`${iconClass} ${isDark ? "scale-100 rotate-0 opacity-100" : "scale-50 -rotate-90 opacity-0"}`}
      />
      <Moon
        aria-hidden="true"
        strokeWidth={1.8}
        className={`${iconClass} ${isDark ? "scale-50 rotate-90 opacity-0" : "scale-100 rotate-0 opacity-100"}`}
      />
    </button>
  );
};
