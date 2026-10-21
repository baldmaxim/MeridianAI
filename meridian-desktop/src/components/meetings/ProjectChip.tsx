import React from "react";
import { useTranslation } from "react-i18next";
import { FolderOpen } from "lucide-react";
import { projectLabel } from "@/lib/utils/library";

interface ProjectChipProps {
  customerName: string | null;
  objectName: string | null;
  /** A click handler makes the chip a button. */
  onClick?: () => void;
  title?: string;
  /** Without a project show a muted "no project" chip. */
  showEmpty?: boolean;
}

const CHIP_CLASS =
  "inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-elevated px-2.5 py-0.5 text-xs text-muted";

/** "Customer · Object" chip. */
export const ProjectChip: React.FC<ProjectChipProps> = ({
  customerName,
  objectName,
  onClick,
  title,
  showEmpty = false,
}) => {
  const { t } = useTranslation();
  const label = projectLabel(customerName, objectName);
  if (!label && !showEmpty) return null;

  const content = (
    <>
      <FolderOpen className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span className="truncate">{label || t("meetings.project.none")}</span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={title}
        className={`${CHIP_CLASS} cursor-pointer transition-colors duration-200 hover:border-logo-primary/60 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none`}
      >
        {content}
      </button>
    );
  }
  return (
    <span title={title} className={CHIP_CLASS}>
      {content}
    </span>
  );
};
