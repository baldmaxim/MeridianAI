import React from "react";
import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import { Button } from "../ui/Button";
import { formatModelSize } from "../../lib/utils/format";
import type { ModelMigrationPair } from "./retiredModels";

export type Phase = "choose" | "migrating";
export type RowState = "idle" | "ready" | "failed" | number;

interface IProgressRingProps {
  progress: number;
}

const ProgressRing: React.FC<IProgressRingProps> = ({ progress }) => {
  const circumference = 2 * Math.PI * 9;
  return (
    <svg className="w-[22px] h-[22px] -rotate-90" viewBox="0 0 22 22">
      <circle
        cx="11"
        cy="11"
        r="9"
        fill="none"
        strokeWidth="2.5"
        className="stroke-mid-gray/25"
      />
      <circle
        cx="11"
        cy="11"
        r="9"
        fill="none"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - progress / 100)}
        className="stroke-logo-primary transition-[stroke-dashoffset] duration-150 ease-linear motion-reduce:transition-none"
      />
    </svg>
  );
};

export interface IMigrationRowProps {
  pair: ModelMigrationPair;
  phase: Phase;
  chosen: boolean;
  showCheck: boolean;
  state: RowState;
  onToggle: (id: string) => void;
  onRetry: (pair: ModelMigrationPair) => void;
}

export const MigrationRow: React.FC<IMigrationRowProps> = ({
  pair,
  phase,
  chosen,
  showCheck,
  state,
  onToggle,
  onRetry,
}) => {
  const { t } = useTranslation();
  const { retired, replacement } = pair;
  const oldName = retired.name;
  // Checkbox semantics only while choosing; later the row may hold a button.
  const toggleable = showCheck && phase === "choose";

  const status = () => {
    // Checked first: a replacement that downloaded but couldn't be selected
    // still needs its Retry button.
    if (state === "failed") {
      return (
        <>
          <span className="text-error">{t("onboarding.migration.failed")}</span>
          <Button
            variant="secondary"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onRetry(pair);
            }}
          >
            {t("onboarding.migration.retry")}
          </Button>
        </>
      );
    }
    // Already-downloaded picks are as good as ready before anything starts.
    if (state === "ready" || (chosen && replacement.is_downloaded)) {
      return (
        <span
          role="img"
          aria-label={t("modelSelector.modelReady")}
          className="grid place-items-center w-[22px] h-[22px] rounded-full bg-emerald-500/20 text-emerald-500"
        >
          <Check className="w-3 h-3" strokeWidth={3} />
        </span>
      );
    }
    if (typeof state === "number") {
      return (
        <>
          <span className="tabular-nums text-text/50">
            {Math.round(state)}%
          </span>
          <ProgressRing progress={state} />
        </>
      );
    }
    return (
      <span className="text-text/50">
        {formatModelSize(Number(replacement.size_mb))}
      </span>
    );
  };

  return (
    <li
      role={toggleable ? "checkbox" : undefined}
      aria-checked={toggleable ? chosen : undefined}
      tabIndex={toggleable ? 0 : undefined}
      onClick={() => toggleable && onToggle(retired.id)}
      onKeyDown={(e) => {
        if (toggleable && (e.key === " " || e.key === "Enter")) {
          e.preventDefault();
          onToggle(retired.id);
        }
      }}
      className={`flex items-center gap-3 px-4 py-3 ${
        toggleable
          ? "cursor-pointer hover:bg-mid-gray/5 focus-visible:outline-none focus-visible:bg-mid-gray/10"
          : ""
      }`}
    >
      {showCheck && (
        <span
          aria-hidden
          className={`grid place-items-center w-5 h-5 shrink-0 rounded-full border-2 transition-colors ${
            chosen
              ? "bg-background-ui border-background-ui text-white"
              : "border-mid-gray/45"
          } ${toggleable ? "" : "opacity-55"}`}
        >
          {chosen && <Check className="w-3 h-3" strokeWidth={3} />}
        </span>
      )}

      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-text truncate">
          {replacement.name}
        </p>
        <div className="flex items-center gap-2 text-xs text-text/40">
          <span className="truncate">
            {t("onboarding.migration.replaces", { name: oldName })}
          </span>
          <span className="shrink-0 rounded border border-mid-gray/35 px-1.5 text-[11px] font-medium text-text/55">
            {t("onboarding.migration.oldFormat")}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0 text-xs">{status()}</div>
    </li>
  );
};
