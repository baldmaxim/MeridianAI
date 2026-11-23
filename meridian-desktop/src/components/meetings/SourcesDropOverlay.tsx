import React from "react";
import { useTranslation } from "react-i18next";
import { UploadCloud } from "lucide-react";

interface SourcesDropOverlayProps {
  active: boolean;
}

/** Covers the meeting screen while files are dragged over the window. */
export const SourcesDropOverlay: React.FC<SourcesDropOverlayProps> = ({
  active,
}) => {
  const { t } = useTranslation();
  if (!active) return null;
  return (
    <div
      className="pointer-events-none absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 border-2 border-dashed border-logo-primary bg-deep/90 p-6 text-center"
      aria-hidden="true"
    >
      <UploadCloud className="h-8 w-8 text-logo-primary" />
      <p className="text-sm font-medium text-text">
        {t("meetings.sources.dropHint")}
      </p>
    </div>
  );
};
