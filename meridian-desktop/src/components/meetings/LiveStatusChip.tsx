import React from "react";
import { useTranslation } from "react-i18next";
import type { LiveState } from "@/bindings";
import { useMeetingStore } from "@/stores/meetingStore";

const CHIP_CLASSES: Record<Exclude<LiveState, "off">, string> = {
  connecting: "border-amber/40 text-amber",
  reconnecting: "border-amber/40 text-amber",
  online: "border-success/40 text-success",
  recorder: "border-mid-gray/30 text-muted",
};

/** The live text of the recording meeting: online, reconnecting, or a dictaphone. */
export const LiveStatusChip: React.FC = () => {
  const { t } = useTranslation();
  const live = useMeetingStore((s) => s.live);
  if (live.state === "off") return null;

  return (
    <span
      role="status"
      title={
        live.state === "recorder"
          ? (live.message ?? t("meetings.live.recorderHint"))
          : undefined
      }
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${CHIP_CLASSES[live.state]}`}
    >
      {t(`meetings.live.${live.state}`)}
    </span>
  );
};
