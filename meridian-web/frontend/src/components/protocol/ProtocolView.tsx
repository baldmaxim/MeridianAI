import type { MeetingProtocol } from '../../types';
import { ProtocolEvidence } from './ProtocolEvidence';
import styles from './ProtocolView.module.css';
import { cx } from '../../utils/cx';

const DECISION_LABELS: Record<string, string> = {
  accepted: 'принято', preliminary: 'предварительно', rejected: 'отклонено',
  postponed: 'отложено', unclear: 'неясно',
};
const SEVERITY_TONES: Record<string, string> = {
  low: styles.sevLow, medium: styles.sevMedium, high: styles.sevHigh,
};

/** Read-only просмотр протокола встречи (Этап 5). */
export function ProtocolView({ p }: { p: MeetingProtocol }) {
  return (
    <div className={styles.root}>
      {p.protocol_markdown && (
        <section className={styles.card}>
          <div className={styles.label}>ПРОТОКОЛ</div>
          <div className={styles.markdown}>{p.protocol_markdown}</div>
        </section>
      )}

      {p.decisions.length > 0 && (
        <section className={styles.card}>
          <div className={styles.label}>РЕШЕНИЯ</div>
          {p.decisions.map((d) => (
            <div key={d.id} className={styles.row}>
              <span className={styles.badge}>{DECISION_LABELS[d.status] || d.status}</span>
              <div className={styles.rowMain}>
                <div>{d.text}</div>
                <ProtocolEvidence ev={d.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}

      {p.action_items.length > 0 && (
        <section className={styles.card}>
          <div className={styles.label}>ЗАДАЧИ</div>
          {p.action_items.map((a) => (
            <div key={a.id} className={styles.row}>
              <span className={styles.badge}>{a.status}</span>
              <div className={styles.rowMain}>
                <div>{a.task}</div>
                <div className={styles.meta}>Отв.: {a.owner_text || 'не указано'} · Срок: {a.due_text || 'не указано'}</div>
                <ProtocolEvidence ev={a.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}

      {p.risks.length > 0 && (
        <section className={styles.card}>
          <div className={styles.label}>РИСКИ</div>
          {p.risks.map((r) => (
            <div key={r.id} className={styles.row}>
              <span className={cx(styles.badge, SEVERITY_TONES[r.severity])}>{r.severity}</span>
              <div className={styles.rowMain}>
                <div>{r.text}</div>
                <ProtocolEvidence ev={r.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}

      {p.open_questions.length > 0 && (
        <section className={styles.card}>
          <div className={styles.label}>ОТКРЫТЫЕ ВОПРОСЫ</div>
          {p.open_questions.map((q) => (
            <div key={q.id} className={styles.row}>
              <span className={styles.bullet}>•</span>
              <div className={styles.rowMain}>
                <div>{q.text}</div>
                <ProtocolEvidence ev={q.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
