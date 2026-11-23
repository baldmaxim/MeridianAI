import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
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

/** Max height of the question field (~4 lines of text-sm). */
const INPUT_MAX_HEIGHT = 96;

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
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { messages, asking, ask } = chat;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, asking]);

  // Auto-grow the question field up to ~4 lines.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    // Hidden (display: none) pane measures 0: keep the natural one-row height.
    if (el.scrollHeight === 0) return;
    el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT)}px`;
  }, [text, serverMeetingId]);

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
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-4 py-3">
        {messages.length === 0 && (
          <p className="m-auto max-w-xs text-center text-xs text-muted">
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
      <div className="flex shrink-0 flex-col gap-1.5 border-t border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <div
            role="tablist"
            aria-label={t("meetings.ask.modeLabel")}
            className="flex shrink-0 gap-1"
          >
            {MODES.map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={mode === value}
                onClick={() => setMode(value)}
                className={`shrink-0 cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-medium leading-5 transition-colors duration-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none ${
                  mode === value
                    ? "border-transparent bg-logo-primary text-on-accent"
                    : "border-border text-muted hover:bg-elevated hover:text-text"
                }`}
              >
                {t(`meetings.ask.mode.${value}`)}
              </button>
            ))}
          </div>
          {mode === "anticipate" && (
            <ul
              aria-label={t("meetings.ask.quickLabel")}
              className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {QUICK_KEYS.map((key) => (
                <li key={key} className="shrink-0">
                  <button
                    type="button"
                    disabled={asking}
                    onClick={() => void ask(t(`meetings.ask.quick.${key}`), mode)}
                    className="cursor-pointer whitespace-nowrap rounded-full border border-border px-2.5 py-0.5 text-xs leading-5 text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none"
                  >
                    {t(`meetings.ask.quick.${key}`)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex items-end gap-1.5 rounded-[10px] border border-border bg-surface py-1 pe-1 ps-3 focus-within:border-logo-primary">
          <textarea
            ref={inputRef}
            value={text}
            rows={1}
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
            className="max-h-24 min-w-0 flex-1 resize-none bg-transparent py-1.5 text-sm leading-5 text-text placeholder:text-subtle focus:outline-none"
          />
          <button
            type="button"
            disabled={!canSend}
            onClick={send}
            aria-label={t("meetings.ask.send")}
            title={t("meetings.ask.send")}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-logo-primary text-on-accent transition-colors duration-200 hover:opacity-85 focus:outline-none focus-visible:ring-2 focus-visible:ring-logo-primary disabled:cursor-not-allowed disabled:bg-elevated disabled:text-muted disabled:hover:opacity-100 motion-reduce:transition-none"
          >
            <Send className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
};
