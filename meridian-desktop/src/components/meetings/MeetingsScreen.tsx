import React, { useState } from "react";
import { useMeetingStore } from "@/stores/meetingStore";
import { useResumeMeeting } from "@/hooks/useResumeMeeting";
import { MeetingList } from "./MeetingList";
import { MeetingView } from "./MeetingView";
import { NewMeetingDialog } from "./NewMeetingDialog";

interface MeetingsScreenProps {
  onOpenModelSettings: () => void;
  onOpenAccount: () => void;
}

/** "Встречи" section: the list, or the open meeting. */
export const MeetingsScreen: React.FC<MeetingsScreenProps> = ({
  onOpenModelSettings,
  onOpenAccount,
}) => {
  const openId = useMeetingStore((s) => s.openId);
  const [newOpen, setNewOpen] = useState(false);
  const { resume, resumingId } = useResumeMeeting(onOpenModelSettings);

  return (
    <div className="h-full min-h-0">
      {openId ? (
        <MeetingView resuming={resumingId === openId} onResume={resume} />
      ) : (
        <MeetingList
          resumingId={resumingId}
          onNew={() => setNewOpen(true)}
          onOpenAccount={onOpenAccount}
          onResume={resume}
        />
      )}
      <NewMeetingDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        onOpenModelSettings={onOpenModelSettings}
      />
    </div>
  );
};
