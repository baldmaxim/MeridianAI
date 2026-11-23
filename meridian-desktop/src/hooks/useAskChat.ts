import { useCallback, useRef, useState } from "react";
import { commands, type AskMode, type AskSource } from "@/bindings";

export interface AskMessage {
  id: number;
  role: "user" | "assistant" | "error";
  text: string;
  sources: AskSource[];
}

export interface AskChat {
  messages: AskMessage[];
  asking: boolean;
  ask: (question: string, mode: AskMode) => Promise<void>;
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
    async (question: string, mode: AskMode) => {
      const text = question.trim();
      if (!text || serverMeetingId === null) return;
      push("user", text);
      setAsking(true);
      let result: Awaited<ReturnType<typeof commands.meetingAsk>>;
      try {
        result = await commands.meetingAsk(serverMeetingId, text, mode);
      } catch (e) {
        push("error", String(e));
        return;
      } finally {
        setAsking(false);
      }
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
