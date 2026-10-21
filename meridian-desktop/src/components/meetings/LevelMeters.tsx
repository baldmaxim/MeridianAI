import React from "react";
import { useTranslation } from "react-i18next";
import type { CaptureMode } from "@/bindings";
import { useMeetingStore } from "@/stores/meetingStore";
import { LevelMeter } from "./LevelMeter";

interface LevelMetersProps {
  captureMode: CaptureMode;
}

/** Live input levels: two channels online, one microphone in person. */
export const LevelMeters: React.FC<LevelMetersProps> = ({ captureMode }) => {
  const { t } = useTranslation();
  const levels = useMeetingStore((s) => s.levels);

  if (captureMode === "in_person") {
    return (
      <LevelMeter
        label={t("meetings.levels.mic")}
        level={levels.mic}
        barClassName="bg-amber"
      />
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <LevelMeter
        label={t("meetings.levels.us")}
        level={levels.mic}
        barClassName="bg-amber"
      />
      <LevelMeter
        label={t("meetings.levels.opponent")}
        level={levels.system}
        barClassName="bg-info"
      />
    </div>
  );
};
