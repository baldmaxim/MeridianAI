import React, { useEffect, useState } from "react";
import { useMeetingStore } from "@/stores/meetingStore";
import { useLibraryStore } from "@/stores/libraryStore";
import { useResumeMeeting } from "@/hooks/useResumeMeeting";
import { LibraryScreen } from "./LibraryScreen";
import { LocalMeetingScreen } from "./LocalMeetingScreen";
import { NewMeetingDialog } from "./NewMeetingDialog";
import { ServerMeetingScreen } from "./ServerMeetingScreen";

interface MeetingsScreenProps {
  onOpenModelSettings: () => void;
  onOpenAccount: () => void;
}

/** "Встречи" section: the library, a local meeting or a site meeting. */
export const MeetingsScreen: React.FC<MeetingsScreenProps> = ({
  onOpenModelSettings,
  onOpenAccount,
}) => {
  const openId = useMeetingStore((s) => s.openId);
  const openServerId = useLibraryStore((s) => s.openServerId);
  const [newOpen, setNewOpen] = useState(false);
  const { resume, resumingId } = useResumeMeeting(onOpenModelSettings);

  // A local meeting opened from elsewhere (the recording pill) wins.
  useEffect(() => {
    if (openId) useLibraryStore.getState().closeServer();
  }, [openId]);

  let screen: React.ReactNode;
  if (openId) {
    screen = (
      <LocalMeetingScreen
        key={openId}
        resuming={resumingId === openId}
        onResume={resume}
      />
    );
  } else if (openServerId !== null) {
    screen = (
      <ServerMeetingScreen key={openServerId} serverMeetingId={openServerId} />
    );
  } else {
    screen = (
      <LibraryScreen
        resumingId={resumingId}
        onNew={() => setNewOpen(true)}
        onOpenAccount={onOpenAccount}
        onResume={resume}
      />
    );
  }

  return (
    <div className="h-full min-h-0">
      {screen}
      <NewMeetingDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        onOpenModelSettings={onOpenModelSettings}
      />
    </div>
  );
};
