import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { FilePlus2, WifiOff } from "lucide-react";
import type { ServerDocument } from "@/bindings";
import type { MeetingSources } from "@/hooks/useMeetingSources";
import { useOfferSubmissions } from "@/hooks/useOfferSubmissions";
import { buildSourceGroups, countIncluded } from "@/lib/utils/sourceGroups";
import { CollapsibleBlock } from "./CollapsibleBlock";
import { OfferSubmissionSelect } from "./OfferSubmissionSelect";
import { QueuedSourceRow } from "./QueuedSourceRow";
import { SourceRow } from "./SourceRow";

interface SourcesSectionProps {
  sources: MeetingSources;
  serverMeetingId: number | null;
  objectId: number | null;
  /** The meeting's submission and its name, from the server's view. */
  offerSubmission: string | null;
  offerSubmissionLabel: string | null;
  /** The submission was changed: the view must be read again. */
  onOfferSubmissionChanged: () => void;
}

/** The meeting's documents: the submission to talk about, then the groups. */
export const SourcesSection: React.FC<SourcesSectionProps> = ({
  sources,
  serverMeetingId,
  objectId,
  offerSubmission,
  offerSubmissionLabel,
  onOfferSubmissionChanged,
}) => {
  const { t } = useTranslation();
  const { data, rejected, pickFiles, setIncluded, removeQueued, refresh } =
    sources;
  const { options, failed } = useOfferSubmissions(objectId, serverMeetingId);

  const queued = useMemo(() => data?.queued ?? [], [data]);
  const server = useMemo(() => data?.server ?? [], [data]);
  const groups = useMemo(
    () =>
      buildSourceGroups(
        server,
        queued,
        options,
        offerSubmission && offerSubmissionLabel
          ? new Map([[offerSubmission, offerSubmissionLabel]])
          : undefined,
      ),
    [server, queued, options, offerSubmission, offerSubmissionLabel],
  );

  const renderDocs = (docs: ServerDocument[]) => (
    <ul className="flex flex-col gap-0.5 ps-5">
      {docs.map((doc) => (
        <SourceRow
          key={doc.document_id}
          doc={doc}
          onToggle={(item, included) => void setIncluded(item, included)}
        />
      ))}
    </ul>
  );
  const counter = (docs: ServerDocument[]) =>
    t("meetings.sources.groupCounter", {
      included: countIncluded(docs),
      total: docs.length,
    });

  const { added } = groups;
  const nothing = queued.length === 0 && server.length === 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
          {t("meetings.sources.title")}
        </h3>
        {server.length > 0 && (
          <span className="text-xs text-muted">
            {t("meetings.sources.counter", {
              included: countIncluded(server),
              total: server.length,
            })}
          </span>
        )}
      </div>

      <OfferSubmissionSelect
        serverMeetingId={serverMeetingId}
        hasObject={objectId !== null}
        options={options}
        loadFailed={failed}
        value={offerSubmission}
        valueLabel={offerSubmissionLabel}
        onChanged={() => {
          onOfferSubmissionChanged();
          void refresh();
        }}
      />

      <button
        type="button"
        onClick={() => void pickFiles()}
        className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-border px-3 py-1 text-sm font-medium text-text transition-colors duration-200 hover:border-logo-primary/60 hover:bg-elevated focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
      >
        <FilePlus2 className="h-4 w-4" aria-hidden="true" />
        {t("meetings.sources.add")}
      </button>
      {data?.offline && (
        <p className="flex items-start gap-2 rounded-lg bg-amber/10 px-2.5 py-2 text-xs text-amber">
          <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {t("meetings.sources.offline")}
        </p>
      )}
      {rejected.length > 0 && (
        <ul role="status" className="flex flex-col gap-1">
          {rejected.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="break-words rounded-lg bg-error/10 px-2.5 py-1.5 text-xs text-error"
            >
              {t(`meetings.sources.reject.${file.reason}`, { name: file.name })}
            </li>
          ))}
        </ul>
      )}

      {nothing ? (
        data !== null && (
          <p className="px-2 py-4 text-center text-xs text-muted">
            {t("meetings.sources.empty")}
          </p>
        )
      ) : (
        <div className="flex flex-col gap-0.5">
          {groups.submissions.map((group) => (
            <CollapsibleBlock
              key={`submission-${group.value}`}
              defaultOpen
              title={t("meetings.sources.groupSubmission", {
                label: group.label,
              })}
              meta={counter(group.docs)}
            >
              {renderDocs(group.docs)}
            </CollapsibleBlock>
          ))}
          {groups.general.length > 0 && (
            <CollapsibleBlock
              title={t("meetings.sources.groupGeneral")}
              meta={counter(groups.general)}
            >
              {renderDocs(groups.general)}
            </CollapsibleBlock>
          )}
          {(added.docs.length > 0 || added.queued.length > 0) && (
            <CollapsibleBlock
              defaultOpen
              title={t("meetings.sources.groupAdded")}
              meta={added.docs.length > 0 ? counter(added.docs) : undefined}
            >
              <div className="flex flex-col gap-0.5">
                {added.queued.length > 0 && (
                  <ul className="flex flex-col gap-0.5 ps-5">
                    {added.queued.map((item) => (
                      <QueuedSourceRow
                        key={item.id}
                        item={item}
                        onRemove={(id) => void removeQueued(id)}
                      />
                    ))}
                  </ul>
                )}
                {added.docs.length > 0 && renderDocs(added.docs)}
              </div>
            </CollapsibleBlock>
          )}
        </div>
      )}
    </div>
  );
};
