import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import type { MeetingInfo } from "@/bindings";
import { useContextAutosave } from "@/hooks/useContextAutosave";
import {
  MeetingContextForm,
  type MeetingContextValue,
} from "./MeetingContextForm";

interface LocalContextTabProps {
  meeting: MeetingInfo;
}

/** Context tab of a local meeting: editable at any time, saved by itself. */
export const LocalContextTab: React.FC<LocalContextTabProps> = ({
  meeting,
}) => {
  const { t } = useTranslation();
  const [value, setValue] = useState<MeetingContextValue>({
    negotiationType: meeting.negotiation_type ?? "",
    keyTerms: meeting.key_terms ?? "",
    opponentWeaknesses: meeting.opponent_weaknesses ?? "",
  });
  const { status, schedule } = useContextAutosave(meeting.id);

  const handleChange = (next: MeetingContextValue) => {
    setValue(next);
    schedule(next);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-4 py-3">
      <MeetingContextForm value={value} onChange={handleChange} />
      <p
        role="status"
        aria-live="polite"
        className={`min-h-4 text-xs ${status.kind === "error" ? "text-error" : "text-muted"}`}
      >
        {status.kind === "saving" && t("meetings.context.saving")}
        {status.kind === "saved" && t("meetings.context.saved")}
        {status.kind === "error" &&
          t("meetings.context.saveFailed", { error: status.message })}
      </p>
      <p className="text-xs text-muted">{t("meetings.context.hint")}</p>
    </div>
  );
};
