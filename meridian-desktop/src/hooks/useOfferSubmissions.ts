import { useEffect, useState } from "react";
import { commands, type OfferSubmission } from "@/bindings";

export interface OfferSubmissions {
  options: OfferSubmission[];
  /** The list could not be loaded (no connection, no access). */
  failed: boolean;
}

/**
 * The submissions of commercial offers of the meeting's object. Needs the
 * object and the meeting on the server; without them the list is empty.
 */
export const useOfferSubmissions = (
  objectId: number | null,
  serverMeetingId: number | null,
): OfferSubmissions => {
  const [options, setOptions] = useState<OfferSubmission[]>([]);
  const [failed, setFailed] = useState(false);
  const enabled = objectId !== null && serverMeetingId !== null;

  useEffect(() => {
    setOptions([]);
    setFailed(false);
    if (!enabled || objectId === null) return;
    let cancelled = false;
    void commands.objectOfferSubmissions(objectId).then((result) => {
      if (cancelled) return;
      if (result.status === "ok") setOptions(result.data);
      else setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [objectId, enabled]);

  return { options, failed };
};
