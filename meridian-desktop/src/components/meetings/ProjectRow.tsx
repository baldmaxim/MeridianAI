import React from "react";

interface ProjectRowProps {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  /** Nesting depth: 0 for customers, 1 for objects. */
  indented?: boolean;
  className?: string;
}

/** A selectable row of the projects panel with the number of meetings. */
export const ProjectRow: React.FC<ProjectRowProps> = ({
  label,
  count,
  active,
  onClick,
  indented = false,
  className = "",
}) => (
  <button
    type="button"
    onClick={onClick}
    aria-current={active ? "true" : undefined}
    className={`flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 rounded-lg py-1.5 pe-2 text-start text-sm transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
      indented ? "ps-2" : "ps-2.5"
    } ${
      active
        ? "bg-logo-primary/15 text-logo-primary"
        : "text-text hover:bg-elevated"
    } ${className}`}
  >
    <span className="min-w-0 truncate">{label}</span>
    <span className="shrink-0 font-mono text-xs tabular-nums text-muted">
      {count}
    </span>
  </button>
);
