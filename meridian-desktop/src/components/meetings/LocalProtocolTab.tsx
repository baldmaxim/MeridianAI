import React from "react";
import { useTranslation } from "react-i18next";
import { useMeetingView } from "@/hooks/useMeetingView";
import { ProtocolPane } from "./ProtocolPane";

interface LocalProtocolTabProps {
  serverMeetingId: number | null;
}

/** Protocol tab of a local meeting: it exists once the meeting is on the site. */
export const LocalProtocolTab: React.FC<LocalProtocolTabProps> = ({
  serverMeetingId,
}) => {
  const { t } = useTranslation();
  const { view, loading, error, reload } = useMeetingView(serverMeetingId);

  if (serverMeetingId === null) {
    return (
      <p className="px-6 py-8 text-center text-sm text-muted">
        {t("meetings.protocol.needSync")}
      </p>
    );
  }
  return (
    <ProtocolPane
      markdown={view?.protocol_markdown ?? null}
      status={view?.finalization_status ?? null}
      loading={loading && !view}
      error={view ? null : error}
      onReload={reload}
    />
  );
};
