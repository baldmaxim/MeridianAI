import { theme } from '../../styles/theme';
import type { MeetingProtocol, EvidenceRef } from '../../types';

const DECISION_LABELS: Record<string, string> = {
  accepted: 'принято', preliminary: 'предварительно', rejected: 'отклонено',
  postponed: 'отложено', unclear: 'неясно',
};
const SEVERITY_COLOR: Record<string, string> = {
  low: theme.text.muted, medium: theme.accent.amber, high: theme.accent.red,
};

function Evidence({ ev }: { ev: EvidenceRef[] }) {
  if (!ev || ev.length === 0) return null;
  return (
    <div style={styles.evidence}>
      {ev.map((e, i) => (
        <span key={i} style={styles.evItem}>
          {e.timecode ? `[${e.timecode}] ` : ''}{e.speaker ? `${e.speaker}: ` : ''}«{e.quote}»
        </span>
      ))}
    </div>
  );
}

/** Read-only просмотр протокола встречи (Этап 5). */
export function ProtocolView({ p }: { p: MeetingProtocol }) {
  return (
    <div style={styles.root}>
      {p.protocol_markdown && (
        <section style={styles.card}>
          <div style={styles.label}>ПРОТОКОЛ</div>
          <div style={styles.markdown}>{p.protocol_markdown}</div>
        </section>
      )}

      {p.decisions.length > 0 && (
        <section style={styles.card}>
          <div style={styles.label}>РЕШЕНИЯ</div>
          {p.decisions.map((d) => (
            <div key={d.id} style={styles.row}>
              <span style={styles.badge}>{DECISION_LABELS[d.status] || d.status}</span>
              <div style={styles.rowMain}>
                <div>{d.text}</div>
                <Evidence ev={d.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}

      {p.action_items.length > 0 && (
        <section style={styles.card}>
          <div style={styles.label}>ЗАДАЧИ</div>
          {p.action_items.map((a) => (
            <div key={a.id} style={styles.row}>
              <span style={styles.badge}>{a.status}</span>
              <div style={styles.rowMain}>
                <div>{a.task}</div>
                <div style={styles.meta}>Отв.: {a.owner_text || 'не указано'} · Срок: {a.due_text || 'не указано'}</div>
                <Evidence ev={a.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}

      {p.risks.length > 0 && (
        <section style={styles.card}>
          <div style={styles.label}>РИСКИ</div>
          {p.risks.map((r) => (
            <div key={r.id} style={styles.row}>
              <span style={{ ...styles.badge, color: SEVERITY_COLOR[r.severity], borderColor: SEVERITY_COLOR[r.severity] }}>{r.severity}</span>
              <div style={styles.rowMain}>
                <div>{r.text}</div>
                <Evidence ev={r.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}

      {p.open_questions.length > 0 && (
        <section style={styles.card}>
          <div style={styles.label}>ОТКРЫТЫЕ ВОПРОСЫ</div>
          {p.open_questions.map((q) => (
            <div key={q.id} style={styles.row}>
              <span style={styles.bullet}>•</span>
              <div style={styles.rowMain}>
                <div>{q.text}</div>
                <Evidence ev={q.evidence} />
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', gap: 12 },
  card: { background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 },
  label: { fontFamily: theme.font.mono, fontSize: 10, letterSpacing: '0.12em', color: theme.accent.amber },
  markdown: { whiteSpace: 'pre-wrap' as const, fontSize: 13, color: theme.text.primary, lineHeight: 1.6, fontFamily: theme.font.body },
  row: { display: 'flex', gap: 10, alignItems: 'flex-start' },
  rowMain: { flex: 1, minWidth: 0, fontSize: 13, color: theme.text.primary, lineHeight: 1.5 },
  badge: { padding: '2px 8px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.text.secondary, textTransform: 'uppercase' as const, flexShrink: 0, marginTop: 2 },
  bullet: { color: theme.accent.amber, marginTop: 2 },
  meta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, marginTop: 2 },
  evidence: { display: 'flex', flexDirection: 'column', gap: 2, marginTop: 4 },
  evItem: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
};
