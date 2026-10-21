import { useCallback, useRef, useState } from "react";
import { commands, type AskSource } from "@/bindings";

export interface AskMessage {
  id: number;
  role: "user" | "assistant" | "error";
  text: string;
  sources: AskSource[];
}

export interface AskChat {
  messages: AskMessage[];
  asking: boolean;
  ask: (question: string) => Promise<void>;
}

/** Question-answer history of one meeting; lives as long as the screen. */
export const useAskChat = (serverMeetingId: number | null): AskChat => {
  const [messages, setMessages] = useState<AskMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const nextId = useRef(1);

  const push = useCallback(
    (role: AskMessage["role"], text: string, sources: AskSource[] = []) =>
      setMessages((list) => [
        ...list,
        { id: nextId.current++, role, text, sources },
      ]),
    [],
  );

  const ask = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (!text || serverMeetingId === null) return;
      push("user", text);
      setAsking(true);
      const result = await commands.meetingAsk(serverMeetingId, text);
      setAsking(false);
      if (result.status === "ok") {
        push("assistant", result.data.answer, result.data.sources);
      } else {
        push("error", result.error);
      }
    },
    [serverMeetingId, push],
  );

  return { messages, asking, ask };
};
