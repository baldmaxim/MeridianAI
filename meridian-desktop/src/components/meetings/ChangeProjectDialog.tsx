import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { commands, type MeetingInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useLibraryStore } from "@/stores/libraryStore";
import { useMeetingStore } from "@/stores/meetingStore";
import { resolveProject, withCurrentProject } from "@/lib/utils/projects";
import { ProjectPicker } from "./ProjectPicker";

interface ChangeProjectDialogProps {
  meeting: MeetingInfo;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Changes the project of a local meeting that is not on the site yet. */
export const ChangeProjectDialog: React.FC<ChangeProjectDialogProps> = ({
  meeting,
  open,
  onOpenChange,
}) => {
  const { t } = useTranslation();
  const projects = useLibraryStore((s) => s.snapshot?.projects);
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [objectId, setObjectId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCustomerId(meeting.customer_id);
    setObjectId(meeting.object_id);
    setSaving(false);
    // The values are taken once per opening.
  }, [open]);

  const customers = withCurrentProject(projects ?? [], {
    customerId: meeting.customer_id,
    objectId: meeting.object_id,
    customerName: meeting.customer_name,
    objectName: meeting.object_name,
  });

  const handleSave = async () => {
    setSaving(true);
    const choice = resolveProject(customers, customerId, objectId);
    const result = await commands.setMeetingProject(
      meeting.id,
      choice.customerId,
      choice.objectId,
      choice.customerName,
      choice.objectName,
    );
    setSaving(false);
    if (result.status === "error") {
      toast.error(t("meetings.errors.projectFailed"), {
        description: result.error,
      });
      return;
    }
    const meetings = useMeetingStore.getState();
    void meetings.loadList();
    void meetings.openMeeting(meeting.id);
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("meetings.project.dialogTitle")}
      closeLabel={t("meetings.newDialog.close")}
      dismissible={!saving}
      contentFades={false}
      footer={
        <>
          <Button
            variant="secondary"
            disabled={saving}
            onClick={() => onOpenChange(false)}
          >
            {t("meetings.actions.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={saving}
            onClick={() => void handleSave()}
          >
            {t("meetings.project.save")}
          </Button>
        </>
      }
    >
      <ProjectPicker
        customers={customers}
        customerId={customerId}
        objectId={objectId}
        disabled={saving}
        onChange={(customer, object) => {
          setCustomerId(customer);
          setObjectId(object);
        }}
      />
    </Dialog>
  );
};
