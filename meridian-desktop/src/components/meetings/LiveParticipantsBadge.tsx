import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Users } from "lucide-react";
import { useMeetingStore } from "@/stores/meetingStore";
import { groupParticipants } from "@/lib/utils/liveParticipants";

/**
 * "N people" of the recording meeting (the devices in its room): shown while
 * the live link is online; a click opens the list of people and their devices.
 */
export const LiveParticipantsBadge: React.FC = () => {
  const { t } = useTranslation();
  const liveState = useMeetingStore((s) => s.live.state);
  const participants = useMeetingStore((s) => s.participants);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverId = useId();

  const people = useMemo(() => groupParticipants(participants), [participants]);
  const visible = liveState === "online" && people.length > 0;

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  if (!visible) return null;

  return (
    <span ref={rootRef} className="relative inline-block">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        aria-label={t("meetings.participants.badge", { count: people.length })}
        onClick={() => setOpen((v) => !v)}
        className="relative inline-flex cursor-pointer items-center gap-1 rounded-full border border-border bg-elevated px-2.5 py-0.5 text-xs text-text transition-colors duration-200 before:absolute before:inset-x-0 before:-inset-y-2.5 before:content-[''] hover:border-logo-primary/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
      >
        <Users className="h-3.5 w-3.5" aria-hidden="true" />
        {people.length}
      </button>
      {open && (
        <div
          id={popoverId}
          role="dialog"
          aria-label={t("meetings.participants.title")}
          className="absolute start-0 top-full z-20 mt-1 flex max-h-72 w-64 max-w-[calc(100vw-2rem)] flex-col gap-2 overflow-y-auto rounded-md border border-border bg-background p-3 shadow-lg"
        >
          <div className="text-xs font-semibold uppercase text-muted">
            {t("meetings.participants.title")}
          </div>
          {people.map((person) => (
            <div key={person.key} className="flex flex-col gap-0.5">
              <span className="break-words text-sm font-semibold text-text">
                {person.name ?? t("meetings.participants.guest")}
              </span>
              {person.devices.map((device) => (
                <div
                  key={device.connectionId}
                  className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted"
                >
                  <span className="break-words">
                    {device.kind === "other"
                      ? device.fallback
                      : t(`meetings.participants.device.${device.kind}`)}
                  </span>
                  {device.isSelf && (
                    <span className="rounded-full border border-logo-primary/40 px-1.5 text-logo-primary">
                      {t("meetings.participants.self")}
                    </span>
                  )}
                  {device.isRecording && (
                    <span className="rounded-full border border-success/40 px-1.5 text-success">
                      {t("meetings.participants.recording")}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </span>
  );
};
