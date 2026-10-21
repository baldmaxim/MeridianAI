import React from "react";
import { useTranslation } from "react-i18next";
import type { MeetingView } from "@/bindings";

interface ServerContextTabProps {
  view: MeetingView;
}

/** Context of a site meeting: read-only. */
export const ServerContextTab: React.FC<ServerContextTabProps> = ({ view }) => {
  const { t } = useTranslation();
  const appNotes = view.app_notes?.trim();
  const fields: { label: string; value: string | null | undefined }[] = [
    { label: t("meetings.context.typeLabel"), value: view.negotiation_type },
    { label: t("meetings.context.keyTermsLabel"), value: view.key_terms },
    {
      label: t("meetings.context.weaknessesLabel"),
      value: view.opponent_weaknesses,
    },
  ];
  if (appNotes) {
    fields.push({ label: t("meetings.context.appNotes"), value: appNotes });
  }

  return (
    <dl className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-4 py-3">
      {fields.map(({ label, value }) => {
        const text = value?.trim();
        return (
          <div key={label} className="flex flex-col gap-1">
            <dt className="text-xs text-muted">{label}</dt>
            <dd
              className={`whitespace-pre-wrap break-words text-sm ${text ? "text-text" : "text-muted"}`}
            >
              {text || t("meetings.context.notSet")}
            </dd>
          </div>
        );
      })}
    </dl>
  );
};
