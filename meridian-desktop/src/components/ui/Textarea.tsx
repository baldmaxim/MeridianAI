import React, { useRef } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  variant?: "default" | "compact";
  /** Shows a "clear" cross inside a non-empty, editable field. */
  onClear?: () => void;
  clearLabel?: string;
}

export const Textarea: React.FC<TextareaProps> = ({
  className = "",
  variant = "default",
  disabled,
  readOnly,
  onClear,
  clearLabel,
  ...props
}) => {
  const { t } = useTranslation();
  const areaRef = useRef<HTMLTextAreaElement>(null);

  const baseClasses =
    "px-2 py-1 text-sm font-semibold bg-mid-gray/10 border border-mid-gray/80 rounded-md text-start transition-[background-color,border-color] duration-150 hover:bg-logo-primary/10 hover:border-logo-primary focus:outline-none focus:bg-logo-primary/10 focus:border-logo-primary resize-y";

  const variantClasses = {
    default: "px-3 py-2 min-h-[100px]",
    compact: "px-2 py-1 min-h-[80px]",
  };

  const hasValue = props.value !== undefined && String(props.value) !== "";
  const showClear = !!onClear && hasValue && !disabled && !readOnly;

  const area = (
    <textarea
      ref={areaRef}
      className={`${baseClasses} ${variantClasses[variant]} ${showClear ? "pe-11" : ""} ${className}`}
      disabled={disabled}
      readOnly={readOnly}
      {...props}
    />
  );

  if (!onClear) return area;

  const label = clearLabel ?? t("common.clear");
  return (
    <span className="relative block">
      {area}
      <button
        type="button"
        aria-label={label}
        title={label}
        tabIndex={showClear ? 0 : -1}
        aria-hidden={!showClear}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          onClear();
          areaRef.current?.focus();
        }}
        className={`absolute end-0 top-0 flex h-11 w-11 cursor-pointer items-center justify-center rounded-e-md text-muted transition-opacity duration-150 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
          showClear ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </span>
  );
};
