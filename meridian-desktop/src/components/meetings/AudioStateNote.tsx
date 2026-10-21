import React from "react";
import { useTranslation } from "react-i18next";

interface AudioStateNoteProps {
  audioState: string;
}

/** Small remark when the server did not take the meeting's audio. */
export const AudioStateNote: React.FC<AudioStateNoteProps> = ({
  audioState,
}) => {
  const { t } = useTranslation();
  if (audioState !== "no_storage") return null;
  return (
    <span className="text-xs text-subtle">{t("meetings.audio.noStorage")}</span>
  );
};
