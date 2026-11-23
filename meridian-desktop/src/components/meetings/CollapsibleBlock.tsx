import React, { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

interface CollapsibleBlockProps {
  title: React.ReactNode;
  /** A short note at the end of the header ("2 из 5"). */
  meta?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

/** A block with a header that opens and closes its content. */
export const CollapsibleBlock: React.FC<CollapsibleBlockProps> = ({
  title,
  meta,
  defaultOpen = false,
  children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  return (
    <section>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full cursor-pointer items-center gap-1.5 rounded-lg py-1 text-start text-sm font-medium text-text transition-colors duration-200 hover:text-logo-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
      >
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-muted transition-transform duration-200 motion-reduce:transition-none ${
            open ? "" : "-rotate-90 rtl:rotate-90"
          }`}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {meta && (
          <span className="shrink-0 text-xs font-normal text-muted">
            {meta}
          </span>
        )}
      </button>
      <div id={bodyId} hidden={!open} className="mt-1.5">
        {children}
      </div>
    </section>
  );
};
