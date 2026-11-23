import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useSidePanelCollapsed } from "@/hooks/useSidePanelCollapsed";
import {
  SIDE_PANEL_MIN_WIDTH,
  useSidePanelWidth,
} from "@/hooks/useSidePanelWidth";

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

/** A step of the arrow keys on the resize handle. */
const KEY_STEP = 16;

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
  const { width, maxWidth, setWidth, reset } = useSidePanelWidth();
  const [drag, setDrag] = useState<{ x: number; width: number } | null>(null);

  // The handle sits on the panel's start edge: going toward the start widens it.
  const direction = () => (document.documentElement.dir === "rtl" ? -1 : 1);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ x: e.clientX, width });
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag) return;
    setWidth(drag.width + (drag.x - e.clientX) * direction());
  };

  const handlePointerEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setDrag(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const grow = e.key === "ArrowLeft" ? direction() : -direction();
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      setWidth(width + grow * KEY_STEP);
    } else if (e.key === "Home") {
      e.preventDefault();
      setWidth(SIDE_PANEL_MIN_WIDTH);
    } else if (e.key === "End") {
      e.preventDefault();
      setWidth(maxWidth);
    }
  };

  if (collapsed) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-s border-mid-gray/40 bg-deep py-2">
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
    <aside
      style={{ width }}
      className="relative flex min-h-0 shrink-0 flex-col bg-deep"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("meetings.view.resizePanel")}
        aria-valuenow={width}
        aria-valuemin={SIDE_PANEL_MIN_WIDTH}
        aria-valuemax={maxWidth}
        tabIndex={0}
        title={t("meetings.view.resizePanelHint")}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerEnd}
        onPointerCancel={handlePointerEnd}
        onMouseDown={(e) => e.preventDefault()}
        onDoubleClick={reset}
        onKeyDown={handleKeyDown}
        className="group absolute inset-y-0 -start-1 z-10 w-2 cursor-col-resize touch-none focus:outline-none"
      >
        {/* The visible edge of the panel: a thin line, the accent on hover/drag. */}
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute inset-y-0 start-[3px] w-0.5 transition-colors duration-200 group-hover:bg-logo-primary group-focus-visible:bg-logo-primary motion-reduce:transition-none ${
            drag ? "bg-logo-primary" : "bg-mid-gray/40"
          }`}
        />
      </div>
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-2.5 py-1.5">
        <div
          role="tablist"
          aria-label={t("meetings.view.panelLabel")}
          className="shell-tabs flex min-w-0 flex-1 gap-1 overflow-x-auto"
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active === tab.id}
              onClick={() => onChange(tab.id)}
              className={`shrink-0 cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
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
