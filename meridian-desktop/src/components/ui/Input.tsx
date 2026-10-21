import React, { useRef } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  variant?: "default" | "compact";
  /** Shows a "clear" cross inside a non-empty, editable field. */
  onClear?: () => void;
  clearLabel?: string;
}

export const Input: React.FC<InputProps> = ({
  className = "",
  variant = "default",
  disabled,
  readOnly,
  onClear,
  clearLabel,
  ...props
}) => {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);

  const baseClasses =
    "px-2 py-1 text-sm font-semibold bg-deep border border-border rounded-[10px] text-start transition-colors duration-150 motion-reduce:transition-none [&::-webkit-search-cancel-button]:hidden [&::-ms-reveal]:hidden [&::-ms-clear]:hidden";

  const interactiveClasses = disabled
    ? "opacity-60 cursor-not-allowed bg-mid-gray/10 border-mid-gray/40"
    : "hover:bg-logo-primary/10 hover:border-logo-primary focus:outline-none focus:bg-logo-primary/20 focus:border-logo-primary";

  const variantClasses = {
    default: "px-3 py-2",
    compact: "px-2 py-1",
  } as const;

  const hasValue = props.value !== undefined && String(props.value) !== "";
  const showClear = !!onClear && hasValue && !disabled && !readOnly;

  const input = (
    <input
      ref={inputRef}
      className={`${baseClasses} ${variantClasses[variant]} ${interactiveClasses} ${showClear ? "pe-11" : ""} ${className}`}
      disabled={disabled}
      readOnly={readOnly}
      {...props}
    />
  );

  if (!onClear) return input;

  const label = clearLabel ?? t("common.clear");
  return (
    <span className="relative block">
      {input}
      <button
        type="button"
        aria-label={label}
        title={label}
        tabIndex={showClear ? 0 : -1}
        aria-hidden={!showClear}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          onClear();
          inputRef.current?.focus();
        }}
        className={`absolute inset-y-0 end-0 flex w-11 cursor-pointer items-center justify-center rounded-e-md text-muted transition-opacity duration-150 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
          showClear ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </span>
  );
};
