import React, { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { commands, type OfferSubmission } from "@/bindings";

interface OfferSubmissionSelectProps {
  /** The meeting on the server; `null`: the select is not available. */
  serverMeetingId: number | null;
  hasObject: boolean;
  options: OfferSubmission[];
  loadFailed: boolean;
  /** The meeting's choice; `null`: all documents of the object. */
  value: string | null;
  valueLabel: string | null;
  /** The choice was saved: the lists must be read again. */
  onChanged: () => void;
}

/** "Which submission of offers do we talk about" for a meeting of an object. */
export const OfferSubmissionSelect: React.FC<OfferSubmissionSelectProps> = ({
  serverMeetingId,
  hasObject,
  options,
  loadFailed,
  value,
  valueLabel,
  onChanged,
}) => {
  const { t } = useTranslation();
  const id = useId();
  const [selected, setSelected] = useState<string | null>(value);
  const [saving, setSaving] = useState(false);
  const available = hasObject && serverMeetingId !== null;

  useEffect(() => {
    setSelected(value);
  }, [value]);

  const handleChange = async (next: string | null) => {
    if (serverMeetingId === null) return;
    const previous = selected;
    setSelected(next);
    setSaving(true);
    const result = await commands.meetingSetOfferSubmission(
      serverMeetingId,
      next,
    );
    setSaving(false);
    if (result.status === "error") {
      setSelected(previous);
      toast.error(t("meetings.sources.offerFailed"), {
        description: result.error,
      });
      return;
    }
    onChanged();
  };

  // A choice the list does not know (an older submission) stays selectable.
  const known = selected === null || options.some((o) => o.value === selected);

  return (
    <div className="flex flex-col gap-1 text-sm">
      <label htmlFor={id} className="text-muted">
        {t("meetings.sources.offerLabel")}
      </label>
      <select
        id={id}
        value={selected ?? ""}
        disabled={!available || saving}
        onChange={(e) => void handleChange(e.target.value || null)}
        className="w-full rounded-md border border-mid-gray/60 bg-surface px-2 py-2 text-sm text-text focus:border-logo-primary focus:outline-none disabled:opacity-60"
      >
        <option value="">{t("meetings.sources.offerAll")}</option>
        {!known && selected !== null && (
          <option value={selected}>{valueLabel || selected}</option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {`${option.label} (${option.document_count})`}
          </option>
        ))}
      </select>
      {!available && (
        <p className="text-xs text-muted">
          {t("meetings.sources.offerUnavailable")}
        </p>
      )}
      {available && loadFailed && (
        <p className="text-xs text-error">
          {t("meetings.sources.offerLoadFailed")}
        </p>
      )}
    </div>
  );
};
