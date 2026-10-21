import React from "react";

interface LevelMeterProps {
  label: string;
  /** 0..1 */
  level: number;
  barClassName: string;
}

export const LevelMeter: React.FC<LevelMeterProps> = ({
  label,
  level,
  barClassName,
}) => {
  const clamped = Math.min(1, Math.max(0, level));
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="shrink-0 text-xs text-muted">{label}</span>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={clamped}
        className="h-1.5 w-20 overflow-hidden rounded-full bg-elevated"
      >
        <div
          className={`h-full w-full origin-left rounded-full transition-transform duration-150 ease-out motion-reduce:transition-none ${barClassName}`}
          style={{ transform: `scaleX(${clamped})` }}
        />
      </div>
    </div>
  );
};
