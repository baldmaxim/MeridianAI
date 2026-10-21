import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useMeetingStore } from "@/stores/meetingStore";

interface DeleteMeetingDialogProps {
  meetingId: string;
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const DeleteMeetingDialog: React.FC<DeleteMeetingDialogProps> = ({
  meetingId,
  title,
  open,
  onOpenChange,
}) => {
  const { t } = useTranslation();
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setDeleting(true);
    const error = await useMeetingStore.getState().deleteMeeting(meetingId);
    setDeleting(false);
    if (error) {
      toast.error(t("meetings.errors.deleteFailed"), { description: error });
    }
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("meetings.delete.title")}
      closeLabel={t("meetings.newDialog.close")}
      dismissible={!deleting}
      contentFades={false}
      footer={
        <>
          <Button
            variant="secondary"
            disabled={deleting}
            onClick={() => onOpenChange(false)}
          >
            {t("meetings.actions.cancel")}
          </Button>
          <Button
            variant="danger"
            disabled={deleting}
            onClick={() => void handleDelete()}
          >
            {t("meetings.delete.confirm")}
          </Button>
        </>
      }
    >
      <p className="text-sm text-text">
        {t("meetings.delete.text", { title })}
      </p>
    </Dialog>
  );
};
