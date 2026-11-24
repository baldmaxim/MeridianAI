import React from "react";
import { useTranslation } from "react-i18next";
import type { IAudioPlayer } from "@/hooks/useAudioPlayer";

interface AudioPlayerBarProps {
  player: IAudioPlayer;
}

/** A slim strip with the native player of the recording; nothing without audio. */
export const AudioPlayerBar: React.FC<AudioPlayerBarProps> = ({ player }) => {
  const { t } = useTranslation();
  if (!player.url) return null;
  return (
    <div className="shrink-0 border-b border-border bg-background px-4 py-1.5">
      <audio
        ref={player.audioRef}
        src={player.url}
        controls
        preload="metadata"
        aria-label={t("audioPlayer.label")}
        onError={player.handleError}
        className="h-10 w-full"
      />
    </div>
  );
};
