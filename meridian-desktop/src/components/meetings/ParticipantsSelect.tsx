import React from "react";
import { useTranslation } from "react-i18next";

export const MIN_PARTICIPANTS = 2;
export const MAX_PARTICIPANTS = 10;

const COUNTS = Array.from(
  { length: MAX_PARTICIPANTS - MIN_PARTICIPANTS + 1 },
  (_, i) => MIN_PARTICIPANTS + i,
);

interface ParticipantsSelectProps {
  /** `null`: not known. */
  value: number | null;
  disabled?: boolean;
  onChange: (value: number | null) => void;
}

/** How many people speak: «Не знаю» or 2…10. Helps the speaker separation. */
export const ParticipantsSelect: React.FC<ParticipantsSelectProps> = ({
  value,
  disabled = false,
  onChange,
}) => {
  const { t } = useTranslation();
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted">{t("meetings.newDialog.participants")}</span>
      <select
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
        className="min-h-11 rounded-md border border-mid-gray/60 bg-surface px-2 py-2 text-base text-text focus:border-logo-primary focus:outline-none disabled:opacity-60"
      >
        <option value="">{t("meetings.newDialog.participantsUnknown")}</option>
        {COUNTS.map((count) => (
          <option key={count} value={count}>
            {count}
          </option>
        ))}
      </select>
      <span className="text-xs text-muted">
        {t("meetings.newDialog.participantsHint")}
      </span>
    </label>
  );
};
