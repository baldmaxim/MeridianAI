import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import type { MeetingInfo, MeetingView } from "@/bindings";
import { useContextAutosave } from "@/hooks/useContextAutosave";
import type { MeetingSources } from "@/hooks/useMeetingSources";
import { CollapsibleBlock } from "./CollapsibleBlock";
import { SourcesSection } from "./SourcesSection";
import {
  MeetingContextForm,
  type MeetingContextValue,
} from "./MeetingContextForm";

interface LocalContextTabProps {
  meeting: MeetingInfo;
  sources: MeetingSources;
  /** The server's view of the meeting (`null` until it is loaded). */
  view: MeetingView | null;
  onReloadView: () => void;
}

/**
 * Context tab of a local meeting: the settings (editable at any time, saved by
 * themselves) and the sources.
 */
export const LocalContextTab: React.FC<LocalContextTabProps> = ({
  meeting,
  sources,
  view,
  onReloadView,
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
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-3 py-2">
      <CollapsibleBlock title={t("meetings.context.paramsTitle")}>
        <div className="flex flex-col gap-2">
          <MeetingContextForm compact value={value} onChange={handleChange} />
          <p
            role="status"
            aria-live="polite"
            className={`min-h-4 text-[11px] ${status.kind === "error" ? "text-error" : "text-muted"}`}
          >
            {status.kind === "saving" && t("meetings.context.saving")}
            {status.kind === "saved" && t("meetings.context.saved")}
            {status.kind === "error" &&
              t("meetings.context.saveFailed", { error: status.message })}
          </p>
          <p className="text-[11px] leading-snug text-muted">
            {t("meetings.context.hint")}
          </p>
        </div>
      </CollapsibleBlock>
      <SourcesSection
        sources={sources}
        serverMeetingId={meeting.server_meeting_id}
        objectId={meeting.object_id ?? view?.object_id ?? null}
        offerSubmission={view?.offer_submission ?? null}
        offerSubmissionLabel={view?.offer_submission_label ?? null}
        onOfferSubmissionChanged={onReloadView}
      />
    </div>
  );
};
