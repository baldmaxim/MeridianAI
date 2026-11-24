import type { FC } from 'react';
import { cx } from '../../utils/cx';
import { MarkdownView } from './MarkdownView';
import { ProtocolView } from './ProtocolView';
import { useMeetingProtocol } from './useMeetingProtocol';
import styles from './ProtocolPane.module.css';

interface IProtocolPaneProps {
  meetingId: number;
  /** Смена значения — перезапросить статус (например, после пересборки протокола). */
  refreshKey?: number;
}

const STATUS_LABEL = {
  completed: 'Протокол готов',
  error: 'Ошибка протокола',
  partial: 'Протокол (частично)',
  queued: 'Формируется протокол…',
  running: 'Формируется протокол…',
} as const;

const TONE = {
  completed: styles.toneGreen,
  error: styles.toneRed,
  partial: styles.toneAmber,
  queued: styles.toneBlue,
  running: styles.toneBlue,
} as const;

/** Протокол встречи на всю высоту окна: markdown — как в расшифровке записи, ниже решения/задачи/риски/вопросы. */
export const ProtocolPane: FC<IProtocolPaneProps> = ({ meetingId, refreshKey = 0 }) => {
  const { status, protocol, loading, unavailable, busy, actionError, rebuild } = useMeetingProtocol(meetingId, refreshKey);

  const inProgress = status === 'queued' || status === 'running';
  const hasContent = !!protocol && (
    !!protocol.protocol_markdown || protocol.decisions.length > 0 || protocol.action_items.length > 0
    || protocol.risks.length > 0 || protocol.open_questions.length > 0
  );

  const renderEmpty = () => {
    if (loading) return <div className={styles.empty}>Загрузка…</div>;
    if (unavailable) return <div className={styles.empty}>Статус протокола недоступен</div>;
    if (inProgress) return <div className={styles.empty}>Протокол собирается…</div>;
    if (status === 'error') return <div className={styles.empty}>Не удалось собрать протокол</div>;
    if (status === 'not_started') {
      return (
        <div className={styles.empty}>
          <span>Протокола нет</span>
          <button type="button" className={cx('t-btn t-btn-amber', styles.action)} disabled={busy} onClick={rebuild}>
            Собрать протокол
          </button>
        </div>
      );
    }
    return <div className={styles.empty}>Протокол пуст</div>;
  };

  return (
    <div className={styles.pane}>
      {status !== 'not_started' && !unavailable && (
        <div className={styles.bar}>
          <span className={cx(styles.badge, TONE[status])}>{STATUS_LABEL[status]}</span>
          {status === 'error' && (
            <button type="button" className={styles.action} disabled={busy} onClick={rebuild}>Повторить</button>
          )}
        </div>
      )}
      {actionError && <div className={styles.error} role="alert">{actionError}</div>}
      <div className={styles.scroll}>
        {hasContent && protocol ? (
          <>
            {protocol.protocol_markdown && (
              <div className={styles.doc}><MarkdownView md={protocol.protocol_markdown} highlight /></div>
            )}
            <ProtocolView p={protocol} hideMarkdown />
          </>
        ) : renderEmpty()}
      </div>
    </div>
  );
};
