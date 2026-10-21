import React, { useId } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";

export interface MeetingContextValue {
  negotiationType: string;
  keyTerms: string;
  opponentWeaknesses: string;
}

export const EMPTY_MEETING_CONTEXT: MeetingContextValue = {
  negotiationType: "",
  keyTerms: "",
  opponentWeaknesses: "",
};

export const NEGOTIATION_TYPE_MAX = 50;
export const CONTEXT_TEXT_MAX = 4000;

/** Empty field means "not set" for the backend. */
export const toNullable = (value: string): string | null =>
  value === "" ? null : value;

interface MeetingContextFormProps {
  value: MeetingContextValue;
  onChange: (value: MeetingContextValue) => void;
  disabled?: boolean;
}

/** The three context fields of a meeting, as on the site (controlled). */
export const MeetingContextForm: React.FC<MeetingContextFormProps> = ({
  value,
  onChange,
  disabled = false,
}) => {
  const { t } = useTranslation();
  const uid = useId();
  const listId = `${uid}-types`;
  const typeId = `${uid}-type`;
  const termsId = `${uid}-terms`;
  const weakId = `${uid}-weak`;
  const suggestions = [
    t("meetings.context.typeSale"),
    t("meetings.context.typeClaim"),
    t("meetings.context.typeTerms"),
  ];
  const set = (patch: Partial<MeetingContextValue>) =>
    onChange({ ...value, ...patch });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor={typeId} className="text-muted">
          {t("meetings.context.typeLabel")}
        </label>
        <Input
          id={typeId}
          type="text"
          list={listId}
          className="w-full"
          maxLength={NEGOTIATION_TYPE_MAX}
          placeholder={t("meetings.context.typePlaceholder")}
          value={value.negotiationType}
          disabled={disabled}
          onChange={(e) => set({ negotiationType: e.target.value })}
          onClear={() => set({ negotiationType: "" })}
          clearLabel={`${t("common.clear")}: ${t("meetings.context.typeLabel")}`}
        />
        <datalist id={listId}>
          {suggestions.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      </div>

      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor={termsId} className="text-muted">
          {t("meetings.context.keyTermsLabel")}
        </label>
        <Textarea
          id={termsId}
          rows={5}
          className="w-full"
          maxLength={CONTEXT_TEXT_MAX}
          placeholder={t("meetings.context.keyTermsPlaceholder")}
          value={value.keyTerms}
          disabled={disabled}
          onChange={(e) => set({ keyTerms: e.target.value })}
          onClear={() => set({ keyTerms: "" })}
          clearLabel={`${t("common.clear")}: ${t("meetings.context.keyTermsLabel")}`}
        />
      </div>

      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor={weakId} className="text-muted">
          {t("meetings.context.weaknessesLabel")}
        </label>
        <Textarea
          id={weakId}
          rows={4}
          className="w-full"
          maxLength={CONTEXT_TEXT_MAX}
          placeholder={t("meetings.context.weaknessesPlaceholder")}
          value={value.opponentWeaknesses}
          disabled={disabled}
          onChange={(e) => set({ opponentWeaknesses: e.target.value })}
          onClear={() => set({ opponentWeaknesses: "" })}
          clearLabel={`${t("common.clear")}: ${t("meetings.context.weaknessesLabel")}`}
        />
      </div>
    </div>
  );
};
