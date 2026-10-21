import React from "react";

/** Compass mark of the brand (same drawing as the app icon, no background). */
export const CompassMark: React.FC<{ className?: string }> = ({
  className = "",
}) => (
  <svg
    viewBox="4 4 24 24"
    fill="none"
    stroke="currentColor"
    className={className}
    aria-hidden="true"
  >
    <circle cx="16" cy="16" r="10" strokeWidth="1.4" opacity="0.5" />
    <circle cx="16" cy="16" r="6" strokeWidth="1.4" opacity="0.8" />
    <circle cx="16" cy="16" r="2" fill="currentColor" stroke="none" />
    <line
      x1="16"
      y1="5"
      x2="16"
      y2="9"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
    <line
      x1="16"
      y1="23"
      x2="16"
      y2="27"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
    <line
      x1="5"
      y1="16"
      x2="9"
      y2="16"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
    <line
      x1="23"
      y1="16"
      x2="27"
      y2="16"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
  </svg>
);

const BRAND_NAME = "Meridian";

interface BrandWordmarkProps {
  className?: string;
}

/** Compass + "MERIDIAN" in Syne 800. */
export const BrandWordmark: React.FC<BrandWordmarkProps> = ({
  className = "",
}) => (
  <div className={`flex items-center gap-2.5 ${className}`}>
    <CompassMark className="h-7 w-7 shrink-0 text-logo-primary" />
    <span className="font-display text-[17px] font-extrabold uppercase leading-none tracking-[0.18em] text-text">
      {BRAND_NAME}
    </span>
  </div>
);
