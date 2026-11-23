import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Send } from "lucide-react";
import type { AskMode } from "@/bindings";
import type { AskChat, AskMessage } from "@/hooks/useAskChat";
import { MarkdownBody } from "./MarkdownBody";

interface AskPaneProps {
  /** `null`: the meeting is not on the server yet. */
  serverMeetingId: number | null;
  chat: AskChat;
}

const MODES: AskMode[] = ["anticipate", "answer"];
const QUICK_KEYS = [
  "expensive",
  "composition",
  "terms",
  "advance",
  "excluded",
] as const;

const AskBubble: React.FC<{ message: AskMessage }> = ({ message }) => {
  const { t } = useTranslation();

  if (message.role === "user") {
    return (
      <div className="meeting-enter ms-8 self-end whitespace-pre-wrap break-words rounded-xl rounded-ee-sm bg-logo-primary/15 px-3 py-2 text-sm text-text">
        {message.text}
      </div>
    );
  }
  if (message.role === "error") {
    return (
      <p
        role="alert"
        className="meeting-enter break-words rounded-xl bg-error/10 px-3 py-2 text-sm text-error"
      >
        {t("meetings.ask.failed")}: {message.text}
      </p>
    );
  }
  return (
    <div className="meeting-enter me-4 rounded-xl rounded-es-sm bg-card px-3 py-2">
      <MarkdownBody markdown={message.text} />
      {message.sources.length > 0 && (
        <ul
          aria-label={t("meetings.ask.sources")}
          className="mt-1 flex flex-wrap gap-1.5"
        >
          {message.sources.map((source, index) => (
            <li
              key={`${source.kind}:${source.ref ?? index}:${source.title}`}
              title={t(`meetings.ask.kind.${source.kind}`, {
                defaultValue: source.kind,
              })}
              className="max-w-full truncate rounded-full border border-border bg-elevated px-2.5 py-0.5 text-xs text-muted"
            >
              {source.title}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

/** Question-and-answer chat about the meeting (server side, needs network). */
export const AskPane: React.FC<AskPaneProps> = ({ serverMeetingId, chat }) => {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AskMode>("anticipate");
  const bottomRef = useRef<HTMLDivElement>(null);
  const { messages, asking, ask } = chat;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, asking]);

  if (serverMeetingId === null) {
    return (
      <p className="px-6 py-8 text-center text-sm text-muted">
        {t("meetings.ask.needSync")}
      </p>
    );
  }

  const canSend = text.trim().length > 0 && !asking;
  const send = () => {
    if (!canSend) return;
    const question = text;
    setText("");
    void ask(question, mode);
  };
  const placeholder =
    mode === "anticipate"
      ? t("meetings.ask.placeholderAnticipate")
      : t("meetings.ask.placeholder");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        role="tablist"
        aria-label={t("meetings.ask.modeLabel")}
        className="flex shrink-0 gap-1.5 border-b border-border px-3 py-2"
      >
        {MODES.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
            className={`shrink-0 cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
              mode === value
                ? "border-transparent bg-logo-primary text-on-accent"
                : "border-border text-muted hover:bg-elevated hover:text-text"
            }`}
          >
            {t(`meetings.ask.mode.${value}`)}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-4 py-3">
        {messages.length === 0 && (
          <p className="mt-6 text-center text-sm text-muted">
            {mode === "anticipate"
              ? t("meetings.ask.emptyAnticipate")
              : t("meetings.ask.empty")}
          </p>
        )}
        {messages.map((message) => (
          <AskBubble key={message.id} message={message} />
        ))}
        {asking && (
          <p className="meeting-rec-dot text-sm text-muted">
            {t("meetings.ask.thinking")}
          </p>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="shrink-0 border-t border-border">
        {mode === "anticipate" && (
          <ul
            aria-label={t("meetings.ask.quickLabel")}
            className="flex flex-wrap gap-1.5 px-3 pt-2.5"
          >
            {QUICK_KEYS.map((key) => (
              <li key={key}>
                <button
                  type="button"
                  disabled={asking}
                  onClick={() => void ask(t(`meetings.ask.quick.${key}`), mode)}
                  className="cursor-pointer rounded-full border border-border px-2.5 py-1 text-xs text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none"
                >
                  {t(`meetings.ask.quick.${key}`)}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-2 p-3">
          <textarea
            value={text}
            rows={2}
            placeholder={placeholder}
            aria-label={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            className="min-w-0 flex-1 resize-none rounded-[10px] border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-subtle focus:border-logo-primary focus:outline-none"
          />
          <button
            type="button"
            disabled={!canSend}
            onClick={send}
            aria-label={t("meetings.ask.send")}
            title={t("meetings.ask.send")}
            className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-[10px] bg-logo-primary text-on-accent transition-opacity duration-200 hover:opacity-85 focus:outline-none focus-visible:ring-2 focus-visible:ring-logo-primary disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none"
          >
            <Send className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
};
