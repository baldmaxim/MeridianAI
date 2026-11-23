import React from "react";
import { useTranslation } from "react-i18next";
import type { AskChat } from "@/hooks/useAskChat";
import { AskPane } from "./AskPane";

interface MainChatPaneProps {
  serverMeetingId: number | null;
  chat: AskChat;
}

/** The chat (including «Вопрос Заказчика») filling the main area of a meeting. */
export const MainChatPane: React.FC<MainChatPaneProps> = ({
  serverMeetingId,
  chat,
}) => {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t("meetings.view.mainChat")}
      className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border bg-surface"
    >
      <AskPane serverMeetingId={serverMeetingId} chat={chat} />
    </section>
  );
};
