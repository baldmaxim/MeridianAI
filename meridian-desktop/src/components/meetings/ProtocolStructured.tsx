import React from "react";
import { useTranslation } from "react-i18next";
import type {
  ProtocolActionItem,
  ProtocolDecision,
  ProtocolEvidence,
  ProtocolQuestion,
  ProtocolRisk,
} from "@/bindings";
import { TimecodeText } from "./TimecodeText";

/** The structured part of a protocol (any list may be missing). */
export interface IProtocolStructuredData {
  decisions?: ProtocolDecision[];
  action_items?: ProtocolActionItem[];
  risks?: ProtocolRisk[];
  open_questions?: ProtocolQuestion[];
}

export const hasStructuredProtocol = (
  data: IProtocolStructuredData | undefined,
): boolean =>
  !!data &&
  ((data.decisions?.length ?? 0) > 0 ||
    (data.action_items?.length ?? 0) > 0 ||
    (data.risks?.length ?? 0) > 0 ||
    (data.open_questions?.length ?? 0) > 0);

const BADGE =
  "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none";

const SEVERITY_TONES: Record<string, string> = {
  low: "border-border text-muted",
  medium: "border-amber/40 text-amber",
  high: "border-error/40 text-error",
};

interface EvidenceProps {
  items: ProtocolEvidence[] | undefined;
  onTimecode?: (seconds: number) => void;
}

/** The quotes behind an item: `[time] Speaker: «quote»`. */
const Evidence: React.FC<EvidenceProps> = ({ items, onTimecode }) => {
  const shown = (items ?? []).filter((e) => e.quote?.trim() || e.timecode);
  if (shown.length === 0) return null;
  return (
    <div className="mt-1 flex flex-col gap-0.5">
      {shown.map((e, index) => {
        const stamp = e.timecode ? `[${e.timecode}] ` : "";
        const rest = `${e.speaker ? `${e.speaker}: ` : ""}${e.quote ? `«${e.quote}»` : ""}`;
        return (
          <span
            key={index}
            className="break-words font-mono text-[11px] leading-snug text-muted"
          >
            {onTimecode ? (
              <TimecodeText text={stamp} onTimecode={onTimecode} />
            ) : (
              stamp
            )}
            {rest}
          </span>
        );
      })}
    </div>
  );
};

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

const Section: React.FC<SectionProps> = ({ title, children }) => (
  <section className="rounded-xl border border-border bg-elevated px-3 py-2.5">
    <h3 className="mb-2 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
      {title}
    </h3>
    <div className="flex flex-col gap-2.5">{children}</div>
  </section>
);

interface RowProps {
  lead: React.ReactNode;
  children: React.ReactNode;
}

const Row: React.FC<RowProps> = ({ lead, children }) => (
  <div className="flex items-start gap-2">
    {lead}
    <div className="min-w-0 flex-1">{children}</div>
  </div>
);

interface ProtocolStructuredProps {
  data: IProtocolStructuredData;
  onTimecode?: (seconds: number) => void;
}

/** Decisions, tasks, risks and open questions of a protocol, with quotes. */
export const ProtocolStructured: React.FC<ProtocolStructuredProps> = ({
  data,
  onTimecode,
}) => {
  const { t } = useTranslation();
  const decisions = data.decisions ?? [];
  const tasks = data.action_items ?? [];
  const risks = data.risks ?? [];
  const questions = data.open_questions ?? [];
  const notSet = t("meetings.protocol.structured.notSet");
  const label = (group: string, value: string | null | undefined) =>
    value
      ? t(`meetings.protocol.structured.${group}.${value}`, {
          defaultValue: value,
        })
      : "";

  return (
    <div className="flex select-text flex-col gap-3">
      {decisions.length > 0 && (
        <Section title={t("meetings.protocol.structured.decisions")}>
          {decisions.map((d, index) => (
            <Row
              key={index}
              lead={
                d.status ? (
                  <span className={`${BADGE} border-border text-text`}>
                    {label("decisionStatus", d.status)}
                  </span>
                ) : null
              }
            >
              <p className="break-words text-sm text-text">{d.text}</p>
              <Evidence items={d.evidence} onTimecode={onTimecode} />
            </Row>
          ))}
        </Section>
      )}
      {tasks.length > 0 && (
        <Section title={t("meetings.protocol.structured.tasks")}>
          {tasks.map((a, index) => (
            <Row key={index} lead={null}>
              <p className="break-words text-sm text-text">{a.task}</p>
              <p className="mt-0.5 text-xs text-muted">
                {t("meetings.protocol.structured.owner")}:{" "}
                {a.owner_text?.trim() || notSet} ·{" "}
                {t("meetings.protocol.structured.due")}:{" "}
                {a.due_text?.trim() || notSet}
              </p>
              <Evidence items={a.evidence} onTimecode={onTimecode} />
            </Row>
          ))}
        </Section>
      )}
      {risks.length > 0 && (
        <Section title={t("meetings.protocol.structured.risks")}>
          {risks.map((r, index) => (
            <Row
              key={index}
              lead={
                r.severity ? (
                  <span
                    className={`${BADGE} ${SEVERITY_TONES[r.severity] ?? "border-border text-muted"}`}
                  >
                    {label("severity", r.severity)}
                  </span>
                ) : null
              }
            >
              <p className="break-words text-sm text-text">{r.text}</p>
              <Evidence items={r.evidence} onTimecode={onTimecode} />
            </Row>
          ))}
        </Section>
      )}
      {questions.length > 0 && (
        <Section title={t("meetings.protocol.structured.questions")}>
          {questions.map((q, index) => (
            <Row
              key={index}
              lead={
                <span className="text-sm text-logo-primary" aria-hidden="true">
                  •
                </span>
              }
            >
              <p className="break-words text-sm text-text">{q.text}</p>
              <Evidence items={q.evidence} onTimecode={onTimecode} />
            </Row>
          ))}
        </Section>
      )}
    </div>
  );
};
