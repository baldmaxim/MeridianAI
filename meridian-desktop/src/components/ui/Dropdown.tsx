import React, {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown } from "lucide-react";

export interface DropdownOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

interface DropdownProps {
  options: DropdownOption[];
  selectedValue: string | null;
  onSelect: (value: string) => void;
  /** Root classes; override the default 220px width here when needed. */
  className?: string;
  placeholder?: string;
  disabled?: boolean;
  onOpen?: () => void;
  /** Leading icon inside the trigger. */
  icon?: React.ReactNode;
  /** Search field above the list; Enter picks the highlighted match. */
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Text for an empty list or no search results (defaults to common.noOptionsFound). */
  emptyLabel?: string;
  ariaLabel?: string;
}

interface PanelPosition {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
  placement: "below" | "above";
}

const PANEL_MAX_HEIGHT = 280;
const PANEL_GAP = 4;
const VIEWPORT_PADDING = 8;

export const Dropdown: React.FC<DropdownProps> = ({
  options,
  selectedValue,
  onSelect,
  className = "w-[220px]",
  placeholder = "Select an option...",
  disabled = false,
  onOpen,
  icon,
  searchable = false,
  searchPlaceholder,
  emptyLabel,
  ariaLabel,
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [position, setPosition] = useState<PanelPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const refocusRef = useRef(false);
  const listId = useId();

  const visibleOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!searchable || !needle) return options;
    return options.filter((option) =>
      option.label.toLowerCase().includes(needle),
    );
  }, [options, query, searchable]);

  const selectedOption = options.find(
    (option) => option.value === selectedValue,
  );

  const close = useCallback((returnFocus: boolean) => {
    setIsOpen(false);
    setQuery("");
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  const open = () => {
    if (disabled) return;
    onOpen?.();
    const selectedIndex = options.findIndex(
      (option) => option.value === selectedValue && !option.disabled,
    );
    setActiveIndex(selectedIndex);
    setIsOpen(true);
  };

  const handleSelect = (option: DropdownOption) => {
    if (option.disabled) return;
    onSelect(option.value);
    // Saving disables the field for a moment; a disabled button drops focus.
    refocusRef.current = true;
    close(true);
  };

  // Place the panel from the trigger rect; flip upwards near the bottom edge.
  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const panelHeight = Math.min(
      panelRef.current?.offsetHeight ?? PANEL_MAX_HEIGHT,
      PANEL_MAX_HEIGHT,
    );
    const spaceBelow =
      window.innerHeight - rect.bottom - PANEL_GAP - VIEWPORT_PADDING;
    const spaceAbove = rect.top - PANEL_GAP - VIEWPORT_PADDING;
    const placement =
      spaceBelow < panelHeight && spaceAbove > spaceBelow ? "above" : "below";
    const available = placement === "below" ? spaceBelow : spaceAbove;
    const maxHeight = Math.max(120, Math.min(PANEL_MAX_HEIGHT, available));
    const height = Math.min(panelHeight, maxHeight);
    setPosition({
      top:
        placement === "below"
          ? rect.bottom + PANEL_GAP
          : rect.top - PANEL_GAP - height,
      left: rect.left,
      width: rect.width,
      maxHeight,
      placement,
    });
  }, []);

  useLayoutEffect(() => {
    if (!isOpen) {
      setPosition(null);
      return;
    }
    updatePosition();
  }, [isOpen, updatePosition, visibleOptions.length]);

  // Close on outside press, resize and scroll of anything but the list itself.
  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) {
        return;
      }
      close(false);
    };
    const handleScroll = (event: Event) => {
      if (panelRef.current?.contains(event.target as Node)) return;
      close(false);
    };
    const handleResize = () => close(false);
    document.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", handleResize);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", handleResize);
    };
  }, [isOpen, close]);

  // The panel is hidden until positioned, and hidden elements cannot be focused.
  const isPositioned = position !== null;
  useEffect(() => {
    if (isOpen && isPositioned && searchable) searchRef.current?.focus();
  }, [isOpen, isPositioned, searchable]);

  useEffect(() => {
    if (!disabled && refocusRef.current) {
      refocusRef.current = false;
      if (document.activeElement === document.body) triggerRef.current?.focus();
    }
  }, [disabled]);

  // A disabled control cannot keep an open list.
  useEffect(() => {
    if (disabled && isOpen) close(false);
  }, [disabled, isOpen, close]);

  const activeId =
    isOpen && activeIndex >= 0 && activeIndex < visibleOptions.length
      ? `${listId}-opt-${activeIndex}`
      : undefined;

  useEffect(() => {
    if (!activeId) return;
    document.getElementById(activeId)?.scrollIntoView({ block: "nearest" });
  }, [activeId]);

  const moveActive = (step: 1 | -1) => {
    const count = visibleOptions.length;
    if (count === 0) return;
    let next = activeIndex;
    for (let i = 0; i < count; i += 1) {
      next = (next + step + count) % count;
      if (!visibleOptions[next].disabled) {
        setActiveIndex(next);
        return;
      }
    }
  };

  const jumpActive = (edge: "first" | "last") => {
    const indices = visibleOptions.map((_, index) => index);
    const ordered = edge === "first" ? indices : indices.reverse();
    const target = ordered.find((index) => !visibleOptions[index].disabled);
    if (target !== undefined) setActiveIndex(target);
  };

  const handleKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement | HTMLInputElement>,
  ) => {
    if (!isOpen) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault();
        open();
      }
      return;
    }
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        moveActive(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveActive(-1);
        break;
      case "Home":
        if (!searchable) {
          event.preventDefault();
          jumpActive("first");
        }
        break;
      case "End":
        if (!searchable) {
          event.preventDefault();
          jumpActive("last");
        }
        break;
      case "Enter": {
        event.preventDefault();
        const option = visibleOptions[activeIndex];
        if (option) handleSelect(option);
        break;
      }
      case " ":
        if (!searchable) {
          event.preventDefault();
          const option = visibleOptions[activeIndex];
          if (option) handleSelect(option);
        }
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation();
        close(true);
        break;
      case "Tab":
        close(false);
        break;
      default:
        break;
    }
  };

  const handleQueryChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(event.target.value);
    // Typing highlights the first match, so Enter picks it.
    setActiveIndex(0);
  };

  const emptyText = emptyLabel ?? t("common.noOptionsFound");

  const panel =
    isOpen && !disabled
      ? createPortal(
          <div
            ref={panelRef}
            style={{
              position: "fixed",
              top: position?.top ?? -9999,
              left: position?.left ?? -9999,
              width: position?.width,
              maxHeight: position?.maxHeight,
              visibility: position ? "visible" : "hidden",
            }}
            className={`dropdown-panel z-[9999] flex flex-col overflow-hidden rounded-lg border border-text/20 bg-card text-text shadow-lg ${
              position?.placement === "above"
                ? "dropdown-panel-above"
                : "dropdown-panel-below"
            }`}
          >
            {searchable && (
              <div className="shrink-0 border-b border-border p-2">
                <input
                  ref={searchRef}
                  type="text"
                  value={query}
                  onChange={handleQueryChange}
                  onKeyDown={handleKeyDown}
                  placeholder={searchPlaceholder}
                  role="combobox"
                  aria-expanded="true"
                  aria-controls={listId}
                  aria-activedescendant={activeId}
                  aria-label={searchPlaceholder ?? ariaLabel}
                  className="h-8 w-full rounded-md border border-border bg-elevated px-2 text-sm text-text placeholder:text-muted focus:border-logo-primary focus:outline-none focus:ring-1 focus:ring-logo-primary"
                />
              </div>
            )}
            <div
              id={listId}
              role="listbox"
              aria-label={ariaLabel}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1"
            >
              {visibleOptions.length === 0 ? (
                <div className="px-3 py-2 text-center text-sm text-muted">
                  {emptyText}
                </div>
              ) : (
                visibleOptions.map((option, index) => {
                  const selected = option.value === selectedValue;
                  const active = index === activeIndex;
                  return (
                    <div
                      key={option.value}
                      id={`${listId}-opt-${index}`}
                      role="option"
                      aria-selected={selected}
                      aria-disabled={option.disabled || undefined}
                      onMouseEnter={() => {
                        if (!option.disabled) setActiveIndex(index);
                      }}
                      onClick={() => handleSelect(option)}
                      className={`flex min-h-[32px] items-center gap-2 px-3 py-1.5 text-sm transition-colors duration-150 motion-reduce:transition-none ${
                        option.disabled
                          ? "cursor-not-allowed opacity-50"
                          : "cursor-pointer"
                      } ${active ? "bg-logo-primary/10" : ""} ${
                        selected ? "font-semibold text-logo-primary" : ""
                      }`}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block whitespace-normal break-words leading-snug">
                          {option.label}
                        </span>
                        {option.description && (
                          <span className="mt-0.5 block whitespace-normal text-xs font-normal leading-snug text-muted">
                            {option.description}
                          </span>
                        )}
                      </span>
                      <Check
                        aria-hidden="true"
                        className={`h-4 w-4 shrink-0 ${selected ? "opacity-100" : "opacity-0"}`}
                      />
                    </div>
                  );
                })
              )}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div className={`relative max-w-full shrink-0 ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listId : undefined}
        aria-activedescendant={searchable ? undefined : activeId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (isOpen ? close(false) : open())}
        onKeyDown={handleKeyDown}
        className={`flex h-[32px] w-full items-center gap-2 rounded-lg border bg-elevated px-3 text-start text-sm font-medium text-text transition-colors duration-150 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
          isOpen ? "border-logo-primary" : "border-text/20"
        } ${
          disabled
            ? "cursor-not-allowed opacity-50"
            : "cursor-pointer hover:border-logo-primary/70"
        }`}
      >
        {icon && (
          <span className="flex shrink-0 items-center text-muted" aria-hidden>
            {icon}
          </span>
        )}
        <span
          className={`min-w-0 flex-1 truncate ${selectedOption ? "" : "text-muted"}`}
        >
          {selectedOption?.label || placeholder}
        </span>
        <ChevronDown
          aria-hidden="true"
          className={`h-4 w-4 shrink-0 text-muted transition-transform duration-200 motion-reduce:transition-none ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>
      {panel}
    </div>
  );
};
