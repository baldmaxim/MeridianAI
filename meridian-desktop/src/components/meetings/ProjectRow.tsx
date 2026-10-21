import React from "react";
import { Folder, FolderOpen } from "lucide-react";

interface ProjectRowProps {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  /**
   * Shows a folder icon and marks the row as a folder: with meetings it is
   * accented and has a count badge, without meetings it is muted and has no
   * count. Without it the row is a plain one with a count.
   */
  folder?: "closed" | "open";
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
  folder,
  indented = false,
  className = "",
}) => {
  const empty = folder !== undefined && count === 0;
  const FolderIcon = folder === "open" ? FolderOpen : Folder;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "true" : undefined}
      className={`flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 rounded-lg py-1.5 pe-2 text-start text-sm transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
        indented ? "ps-2" : "ps-2.5"
      } ${
        active
          ? "bg-logo-primary/15 text-logo-primary"
          : `${empty ? "text-muted" : "text-text"} hover:bg-elevated`
      } ${className}`}
    >
      <span className="flex min-w-0 items-center gap-2">
        {folder && (
          <FolderIcon
            className={`h-4 w-4 shrink-0 ${
              empty ? "text-muted" : "text-logo-primary"
            }`}
            aria-hidden="true"
          />
        )}
        <span className="min-w-0 truncate">{label}</span>
      </span>
      {!empty &&
        (folder ? (
          <span className="shrink-0 rounded-full bg-logo-primary/15 px-1.5 font-mono text-xs tabular-nums text-logo-primary">
            {count}
          </span>
        ) : (
          <span className="shrink-0 font-mono text-xs tabular-nums text-muted">
            {count}
          </span>
        ))}
    </button>
  );
};
