import type {
  OfferSubmission,
  QueuedDocument,
  ServerDocument,
} from "@/bindings";

/** Documents of one submission of commercial offers. */
export interface SubmissionGroup {
  value: string;
  label: string;
  docs: ServerDocument[];
}

export interface SourceGroups {
  /** Inherited documents of a submission, one group per submission. */
  submissions: SubmissionGroup[];
  /** Inherited documents that belong to no submission. */
  general: ServerDocument[];
  /** Files attached to the meeting itself (and those still on their way). */
  added: { docs: ServerDocument[]; queued: QueuedDocument[] };
}

/** The name to show for a document; the original one goes into the tooltip. */
export const documentName = (doc: ServerDocument): string | null =>
  doc.display_name?.trim() || doc.name;

/** How many of the documents are in the context. */
export const countIncluded = (docs: ServerDocument[]): number =>
  docs.filter((doc) => doc.included).length;

/**
 * Splits the meeting's documents into the groups of the sources block: the
 * submissions (in the order of `submissions`, unknown ones after them),
 * the general documentation, and what was added to the meeting.
 */
export const buildSourceGroups = (
  server: ServerDocument[],
  queued: QueuedDocument[],
  submissions: OfferSubmission[],
  extraLabels: ReadonlyMap<string, string> = new Map(),
): SourceGroups => {
  const added: ServerDocument[] = [];
  const general: ServerDocument[] = [];
  const bySubmission = new Map<string, ServerDocument[]>();
  for (const doc of server) {
    if (doc.source === "meeting") {
      added.push(doc);
    } else if (doc.offer_submission) {
      const list = bySubmission.get(doc.offer_submission) ?? [];
      list.push(doc);
      bySubmission.set(doc.offer_submission, list);
    } else {
      general.push(doc);
    }
  }

  const labels = new Map(extraLabels);
  for (const item of submissions) labels.set(item.value, item.label);
  const order = [
    ...submissions.map((item) => item.value),
    ...[...bySubmission.keys()].filter(
      (value) => !submissions.some((item) => item.value === value),
    ),
  ];
  return {
    submissions: order.flatMap((value) => {
      const docs = bySubmission.get(value);
      return docs ? [{ value, label: labels.get(value) ?? value, docs }] : [];
    }),
    general,
    added: { docs: added, queued },
  };
};
