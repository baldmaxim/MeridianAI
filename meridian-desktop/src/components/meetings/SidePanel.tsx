import React from "react";
import { useTranslation } from "react-i18next";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useSidePanelCollapsed } from "@/hooks/useSidePanelCollapsed";

export interface SidePanelTab<T extends string> {
  id: T;
  label: string;
}

interface SidePanelProps<T extends string> {
  tabs: SidePanelTab<T>[];
  active: T;
  onChange: (id: T) => void;
  children: React.ReactNode;
}

const ICON_BUTTON =
  "flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none";

/** Collapsible right panel of a meeting screen with pill tabs. */
export const SidePanel = <T extends string>({
  tabs,
  active,
  onChange,
  children,
}: SidePanelProps<T>) => {
  const { t } = useTranslation();
  const [collapsed, toggle] = useSidePanelCollapsed();

  if (collapsed) {
    return (
      <aside className="flex w-12 shrink-0 flex-col items-center border-s border-border bg-deep py-3">
        <button
          type="button"
          onClick={toggle}
          aria-label={t("meetings.view.expandPanel")}
          title={t("meetings.view.expandPanel")}
          className={ICON_BUTTON}
        >
          <PanelRightOpen className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </aside>
    );
  }

  return (
    <aside className="flex min-h-0 w-[340px] shrink-0 flex-col border-s border-border bg-deep min-[1000px]:w-[400px]">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2.5">
        <div
          role="tablist"
          aria-label={t("meetings.view.panelLabel")}
          className="shell-tabs flex min-w-0 flex-1 gap-1.5 overflow-x-auto"
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active === tab.id}
              onClick={() => onChange(tab.id)}
              className={`shrink-0 cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
                active === tab.id
                  ? "border-transparent bg-logo-primary text-on-accent"
                  : "border-border text-muted hover:bg-elevated hover:text-text"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-label={t("meetings.view.collapsePanel")}
          title={t("meetings.view.collapsePanel")}
          className={ICON_BUTTON}
        >
          <PanelRightClose className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </div>
      <div
        key={active}
        role="tabpanel"
        className="meeting-enter flex min-h-0 flex-1 flex-col"
      >
        {children}
      </div>
    </aside>
  );
};
