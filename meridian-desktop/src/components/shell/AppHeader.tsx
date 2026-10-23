import React from "react";
import ModelSelector from "../model-selector";
import { BrandWordmark } from "./BrandMark";
import { RecordPill } from "./RecordPill";
import { SyncIndicator } from "./SyncIndicator";
import { UpdatePill } from "./UpdatePill";

interface AppHeaderProps {
  onOpenAccount: () => void;
  onOpenMeeting: (meetingId: string) => void;
}

/** Top bar: brand on the left; recording, upload and model status on the right. */
export const AppHeader: React.FC<AppHeaderProps> = ({
  onOpenAccount,
  onOpenMeeting,
}) => (
  <header className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4">
    <BrandWordmark className="shrink-0" />
    <div className="flex min-w-0 items-center gap-2 text-xs text-muted">
      <RecordPill onOpenMeeting={onOpenMeeting} />
      <UpdatePill />
      <SyncIndicator onOpenAccount={onOpenAccount} />
      <ModelSelector />
    </div>
  </header>
);
