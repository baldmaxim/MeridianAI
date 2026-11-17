import React from "react";
import { useTranslation } from "react-i18next";

export type TranscriptMode = "refined" | "draft";

interface TranscriptModeToggleProps {
  value: TranscriptMode;
  onChange: (mode: TranscriptMode) => void;
}

const MODES: TranscriptMode[] = ["refined", "draft"];

/** Segmented control: the server's refined transcript or the draft from the PC. */
export const TranscriptModeToggle: React.FC<TranscriptModeToggleProps> = ({
  value,
  onChange,
}) => {
  const { t } = useTranslation();
  return (
    <div
      role="radiogroup"
      aria-label={t("meetings.refine.modeLabel")}
      className="mx-4 mt-3 flex shrink-0 rounded-lg border border-border bg-elevated p-0.5"
    >
      {MODES.map((mode) => (
        <button
          key={mode}
          type="button"
          role="radio"
          aria-checked={value === mode}
          onClick={() => onChange(mode)}
          className={`min-h-11 flex-1 cursor-pointer rounded-md px-2 text-xs font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
            value === mode
              ? "bg-logo-primary text-on-accent"
              : "text-muted hover:text-text"
          }`}
        >
          {t(`meetings.refine.mode.${mode}`)}
        </button>
      ))}
    </div>
  );
};
