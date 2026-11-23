import React from "react";
import { useTranslation } from "react-i18next";

export interface MainViewOption<T extends string> {
  id: T;
  label: string;
}

interface MainViewSwitchProps<T extends string> {
  options: MainViewOption<T>[];
  value: T;
  onChange: (id: T) => void;
}

/** Segmented switch on top of the main area of a meeting (notes/chat, protocol/chat). */
export const MainViewSwitch = <T extends string>({
  options,
  value,
  onChange,
}: MainViewSwitchProps<T>) => {
  const { t } = useTranslation();
  return (
    <div
      role="radiogroup"
      aria-label={t("meetings.view.mainSwitchLabel")}
      className="mb-2 flex shrink-0 self-start rounded-lg border border-border bg-elevated p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          onClick={() => onChange(option.id)}
          className={`min-h-8 min-w-24 cursor-pointer rounded-md px-3 text-xs font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
            value === option.id
              ? "bg-logo-primary text-on-accent"
              : "text-muted hover:text-text"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
};
