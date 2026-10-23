import React from "react";
import { useTranslation } from "react-i18next";
import {
  FilePlus2,
  PanelLeftClose,
  PanelLeftOpen,
  UploadCloud,
  WifiOff,
} from "lucide-react";
import type { ServerDocument } from "@/bindings";
import { useMeetingSources } from "@/hooks/useMeetingSources";
import { useSidePanelCollapsed } from "@/hooks/useSidePanelCollapsed";
import { QueuedSourceRow } from "./QueuedSourceRow";
import { SourceRow } from "./SourceRow";

const STORAGE_KEY = "meridian.meetingSourcesCollapsed";
const GROUPS = ["meeting", "customer", "object"] as const;
type Group = (typeof GROUPS)[number];

const ICON_BUTTON =
  "flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none";

const groupOf = (doc: ServerDocument): Group =>
  doc.source === "customer" || doc.source === "object" ? doc.source : "meeting";

interface SourcesPanelProps {
  /** The local meeting; `null` for a meeting of the site. */
  meetingId: string | null;
  serverMeetingId: number | null;
}

/** Left column of a meeting screen: files of the meeting and drag-and-drop. */
export const SourcesPanel: React.FC<SourcesPanelProps> = ({
  meetingId,
  serverMeetingId,
}) => {
  const { t } = useTranslation();
  const [collapsed, toggle] = useSidePanelCollapsed(STORAGE_KEY);
  const { data, rejected, dragActive, pickFiles, setIncluded, removeQueued } =
    useMeetingSources({ meetingId, serverMeetingId });

  const queued = data?.queued ?? [];
  const server = data?.server ?? [];
  const includedCount = server.filter((doc) => doc.included).length;

  // A drag opens the collapsed panel so the drop target is visible.
  if (collapsed && !dragActive) {
    return (
      <aside className="flex w-12 shrink-0 flex-col items-center border-e border-border bg-deep py-3">
        <button
          type="button"
          onClick={toggle}
          aria-label={t("meetings.sources.expand")}
          title={t("meetings.sources.expand")}
          className={ICON_BUTTON}
        >
          <PanelLeftOpen className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </aside>
    );
  }

  return (
    <aside
      aria-label={t("meetings.sources.panelLabel")}
      className="relative flex min-h-0 w-72 shrink-0 flex-col border-e border-border bg-deep"
    >
      <div className="flex shrink-0 items-start gap-2 border-b border-border px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <h2 className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
            {t("meetings.sources.title")}
          </h2>
          {server.length > 0 && (
            <p className="mt-0.5 text-xs text-muted">
              {t("meetings.sources.counter", {
                included: includedCount,
                total: server.length,
              })}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-label={t("meetings.sources.collapse")}
          title={t("meetings.sources.collapse")}
          className={ICON_BUTTON}
        >
          <PanelLeftClose className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </div>

      <div className="shrink-0 px-3 pt-3">
        <button
          type="button"
          onClick={() => void pickFiles()}
          className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-border px-3 py-1.5 text-sm font-medium text-text transition-colors duration-200 hover:border-logo-primary/60 hover:bg-elevated focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
        >
          <FilePlus2 className="h-4 w-4" aria-hidden="true" />
          {t("meetings.sources.add")}
        </button>
        {data?.offline && (
          <p className="mt-2 flex items-start gap-2 rounded-lg bg-amber/10 px-2.5 py-2 text-xs text-amber">
            <WifiOff
              className="mt-0.5 h-3.5 w-3.5 shrink-0"
              aria-hidden="true"
            />
            {t("meetings.sources.offline")}
          </p>
        )}
        {rejected.length > 0 && (
          <ul role="status" className="mt-2 flex flex-col gap-1">
            {rejected.map((file, index) => (
              <li
                key={`${file.name}-${index}`}
                className="break-words rounded-lg bg-error/10 px-2.5 py-1.5 text-xs text-error"
              >
                {t(`meetings.sources.reject.${file.reason}`, {
                  name: file.name,
                })}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-3">
        {queued.length === 0 && server.length === 0 ? (
          data !== null && (
            <p className="px-2 py-6 text-center text-xs text-muted">
              {t("meetings.sources.empty")}
            </p>
          )
        ) : (
          <div className="flex flex-col gap-4">
            {queued.length > 0 && (
              <ul className="flex flex-col gap-2">
                {queued.map((item) => (
                  <QueuedSourceRow
                    key={item.id}
                    item={item}
                    onRemove={(id) => void removeQueued(id)}
                  />
                ))}
              </ul>
            )}
            {GROUPS.map((group) => {
              const docs = server.filter((doc) => groupOf(doc) === group);
              if (docs.length === 0) return null;
              return (
                <section key={group}>
                  <h3 className="mb-1.5 text-xs font-medium text-muted">
                    {t(`meetings.sources.group.${group}`)}
                  </h3>
                  <ul className="flex flex-col gap-2">
                    {docs.map((doc) => (
                      <SourceRow
                        key={doc.document_id}
                        doc={doc}
                        onToggle={(item, included) =>
                          void setIncluded(item, included)
                        }
                      />
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </div>

      {dragActive && (
        <div
          className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 border-2 border-dashed border-logo-primary bg-deep/90 p-6 text-center"
          aria-hidden="true"
        >
          <UploadCloud className="h-8 w-8 text-logo-primary" />
          <p className="text-sm font-medium text-text">
            {t("meetings.sources.dropHint")}
          </p>
        </div>
      )}
    </aside>
  );
};
