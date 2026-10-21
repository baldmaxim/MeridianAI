import React from "react";
import { useTranslation } from "react-i18next";
import { Globe, Monitor } from "lucide-react";
import type { LibrarySource } from "@/bindings";

interface SourceMarkProps {
  source: LibrarySource;
}

/** Tiny icon: recorded in this app (computer) or created on the site. */
export const SourceMark: React.FC<SourceMarkProps> = ({ source }) => {
  const { t } = useTranslation();
  const label =
    source === "desktop"
      ? t("meetings.library.sourceDesktop")
      : t("meetings.library.sourceWeb");
  const Icon = source === "desktop" ? Monitor : Globe;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="inline-flex shrink-0 text-subtle"
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
    </span>
  );
};
