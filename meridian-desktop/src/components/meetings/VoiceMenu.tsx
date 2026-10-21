import React, { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { VoiceSide } from "@/stores/meetingStore";

interface VoiceMenuProps {
  /** Chip text, e.g. "Голос 1 · Оппонент". */
  caption: string;
  /** Voice name, for the accessible label. */
  voice: string;
  side: VoiceSide;
  /** Classes of the chip text colour. */
  textClass: string;
  onSelect: (side: VoiceSide) => void;
}

const OPTIONS: { side: VoiceSide; key: string }[] = [
  { side: "self", key: "self" },
  { side: "opponent", key: "opponent" },
  { side: null, key: "unknown" },
];

/** Chip with a small menu: whose voice is it (us / opponent / not sure). */
export const VoiceMenu: React.FC<VoiceMenuProps> = ({
  caption,
  voice,
  side,
  textClass,
  onSelect,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const chipRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      chipRef.current?.focus();
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const handleSelect = (value: VoiceSide) => {
    setOpen(false);
    chipRef.current?.focus();
    if (value !== side) onSelect(value);
  };

  return (
    <span ref={rootRef} className="relative inline-block">
      <button
        ref={chipRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        className={`cursor-pointer rounded-full border border-border bg-elevated px-2 py-0.5 text-xs font-semibold transition-colors duration-200 hover:border-logo-primary/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${textClass}`}
      >
        {caption}
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={t("meetings.voice.menuLabel", { voice })}
          className="absolute start-0 top-full z-20 mt-1 flex min-w-36 flex-col overflow-hidden rounded-md border border-border bg-background shadow-lg"
        >
          {OPTIONS.map((option) => {
            const checked = option.side === side;
            return (
              <button
                key={option.key}
                type="button"
                role="menuitemradio"
                aria-checked={checked}
                autoFocus={checked}
                onClick={() => handleSelect(option.side)}
                className={`flex min-h-11 w-full cursor-pointer items-center px-3 text-start text-sm transition-colors duration-150 hover:bg-logo-primary/10 focus:bg-logo-primary/10 focus:outline-none motion-reduce:transition-none ${
                  checked ? "bg-logo-primary/20 font-semibold" : ""
                }`}
              >
                {t(`meetings.voice.${option.key}`)}
              </button>
            );
          })}
        </div>
      )}
    </span>
  );
};
