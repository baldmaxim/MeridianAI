import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComponentProps, FC } from 'react';
import { MeetingAudioSettings } from '../../components/meeting/MeetingAudioSettings';
import { ModeSwitch } from '../../components/meeting/ModeSwitch';
import { RecordingIndicator } from '../../components/meeting/RecordingIndicator';
import { IconSwap } from '../../components/common/IconSwap';
import { useExitTransition } from '../../hooks/useExitTransition';
import { paths } from '../../lib/navigation';
import styles from './MeetingTopBar.module.css';

const LINK_COPIED_MS = 2000;

interface IMeetingTopBarProps {
  onBack: () => void;
  customerName: string | null;
  objectName: string | null;
  meetingDate: string | null;
  meetingId: number | null;
  showToast: (message: string, type?: 'success' | 'error') => void;
  audioSettings: ComponentProps<typeof MeetingAudioSettings>;
}

/**
 * Верхняя панель встречи: «назад» + переключатель вида (диктофон/полный) + ссылка.
 * Общая для обоих режимов — переключатель доступен и в диктофоне, и в полном.
 */
export const MeetingTopBar: FC<IMeetingTopBarProps> = ({
  onBack, customerName, objectName, meetingDate, meetingId, showToast, audioSettings,
}) => {
  const [linkCopied, setLinkCopied] = useState(false);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Инлайн-уведомление о копировании ссылки (panel-reveal под кнопкой).
  const copyNote = useExitTransition(linkCopied, { closeVar: '--panel-close-dur', fallbackMs: 350 });

  useEffect(() => () => {
    if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
  }, []);

  const copyMeetingLink = useCallback(() => {
    if (meetingId == null) return;
    const url = window.location.origin + paths.meetingRoom(meetingId);
    const done = () => {
      // Инлайн-фидбек прямо под кнопкой (вместо тоста): чек + всплывающая подпись.
      setLinkCopied(true);
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), LINK_COPIED_MS);
    };
    const fail = () => showToast('Не удалось скопировать ссылку', 'error');
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done, fail);
    else fail();
  }, [meetingId, showToast]);

  return (
    <div className={styles.topBar}>
      <button onClick={onBack} className={`t-btn ${styles.backBtn}`} aria-label="Назад" title="В главное меню">
        <span>←</span><span className={styles.btnLabel}> Назад</span>
      </button>
      {/* Заказчик/объект/дата — справочно, read-only (привязка задаётся при создании встречи) */}
      {(customerName || objectName || meetingDate) && (
        <div className={styles.refInfo}>
          {customerName && (
            <span className={styles.refItem} title={`Заказчик: ${customerName}`}>
              <span className={styles.refLabel}>Заказчик</span>
              <span className={styles.refVal}>{customerName}</span>
            </span>
          )}
          {objectName && (
            <span className={styles.refItem} title={`Объект: ${objectName}`}>
              <span className={styles.refLabel}>Объект</span>
              <span className={styles.refVal}>{objectName}</span>
            </span>
          )}
          {meetingDate && (
            <span className={styles.refItem} title={`Дата встречи: ${meetingDate}`}>
              <span className={styles.refLabel}>Дата</span>
              <span className={styles.refVal}>{meetingDate}</span>
            </span>
          )}
        </div>
      )}
      <div className={styles.actions}>
        <RecordingIndicator />
        <ModeSwitch />
        {meetingId != null && (
          <div className={styles.linkWrap}>
            <button onClick={copyMeetingLink} className={`t-btn ${styles.linkBtn}`} aria-label="Скопировать ссылку" title="Скопировать ссылку на встречу">
              <IconSwap state={linkCopied ? 'b' : 'a'} a="🔗" b="✓" />
              <span className={styles.btnLabel}> Ссылка</span>
            </button>
            {copyNote.mounted && (
              <div
                className={`t-panel-slide ${styles.copyNote}`}
                data-open={copyNote.open ? 'true' : 'false'}
              >
                Ссылка скопирована
              </div>
            )}
          </div>
        )}
        <MeetingAudioSettings {...audioSettings} />
      </div>
    </div>
  );
};
