import React from "react";
import { useTranslation } from "react-i18next";
import { Settings, User, Users } from "lucide-react";
import type { AccountInfo } from "@/bindings";
import { useSyncStore } from "@/stores/syncStore";
import { useUpdateStore } from "@/stores/updateStore";
import type { AppSection, SettingsSection } from "./settingsSections";

interface RailItemProps {
  active: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}

const RailItem: React.FC<RailItemProps> = ({
  active,
  label,
  onClick,
  children,
}) => (
  <button
    type="button"
    onClick={onClick}
    aria-current={active ? "page" : undefined}
    className={`flex w-14 cursor-pointer flex-col items-center gap-1 rounded-xl px-1 py-2 transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
      active
        ? "bg-logo-primary/15 text-logo-primary"
        : "text-muted hover:bg-elevated hover:text-text"
    }`}
  >
    {children}
    <span className="text-[10px] font-medium leading-none">{label}</span>
  </button>
);

/** Up to two initials from the display name, else from the e-mail. */
export const getAccountInitials = (account: AccountInfo): string => {
  const name = account.user.display_name?.trim();
  if (name) {
    const words = name.split(/\s+/).filter(Boolean);
    const letters =
      words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2);
    return letters.toUpperCase();
  }
  return account.user.email.slice(0, 2).toUpperCase();
};

interface IconRailProps {
  section: AppSection;
  settingsTab: SettingsSection;
  onOpenMeetings: () => void;
  onOpenSettings: () => void;
  onOpenAccount: () => void;
}

/** Narrow left rail: meetings on top, settings and account at the bottom. */
export const IconRail: React.FC<IconRailProps> = ({
  section,
  settingsTab,
  onOpenMeetings,
  onOpenSettings,
  onOpenAccount,
}) => {
  const { t } = useTranslation();
  const account = useSyncStore((s) => s.account);
  const updateAvailable = useUpdateStore((s) => s.status === "available");
  const inSettings = section === "settings";
  const accountActive = inSettings && settingsTab === "account";
  const accountLabel = account
    ? t("shell.nav.accountOf", { email: account.user.email })
    : t("shell.nav.account");

  return (
    <nav
      aria-label={t("shell.nav.label")}
      className="flex w-16 shrink-0 flex-col items-center justify-between border-e border-border bg-deep py-3"
    >
      <RailItem
        active={section === "meetings"}
        label={t("shell.nav.meetings")}
        onClick={onOpenMeetings}
      >
        <Users className="h-[22px] w-[22px]" strokeWidth={1.8} />
      </RailItem>
      <div className="flex flex-col items-center gap-2">
        <RailItem
          active={inSettings && !accountActive}
          label={t("shell.nav.settings")}
          onClick={onOpenSettings}
        >
          <span className="relative">
            <Settings className="h-[22px] w-[22px]" strokeWidth={1.8} />
            {updateAvailable && (
              <span
                role="img"
                title={t("shell.update.dot")}
                aria-label={t("shell.update.dot")}
                className="absolute -end-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-deep bg-amber"
              />
            )}
          </span>
        </RailItem>
        <button
          type="button"
          onClick={onOpenAccount}
          title={accountLabel}
          aria-label={accountLabel}
          aria-current={accountActive ? "page" : undefined}
          className={`flex h-10 w-10 cursor-pointer items-center justify-center rounded-full border text-xs font-semibold transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
            accountActive
              ? "border-logo-primary bg-logo-primary/15 text-logo-primary"
              : "border-border bg-elevated text-text hover:border-logo-primary"
          }`}
        >
          {account ? (
            getAccountInitials(account)
          ) : (
            <User className="h-[18px] w-[18px]" strokeWidth={1.8} />
          )}
        </button>
      </div>
    </nav>
  );
};
