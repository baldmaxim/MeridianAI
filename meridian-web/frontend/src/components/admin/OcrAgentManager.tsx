import { useCallback, useEffect, useState } from 'react';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import { enrollOcrAgent, getOcrQueueStatus, revokeOcrAgent } from '../../api/ocrAgents';
import type { OcrQueueStatus } from '../../api/ocrAgents';

/** Как часто обновлять состояние: агент отмечается раз в минуту. */
const REFRESH_MS = 30_000;

function ago(iso: string | null): string {
  if (!iso) return 'ни разу';
  // сервер отдаёт UTC без зоны
  const ms = Date.now() - new Date(iso.endsWith('Z') ? iso : `${iso}Z`).getTime();
  const min = Math.round(ms / 60_000);
  if (min < 1) return 'только что';
  if (min < 60) return `${min} мин назад`;
  const h = Math.round(min / 60);
  return h < 48 ? `${h} ч назад` : `${Math.round(h / 24)} дн назад`;
}

/**
 * Распознавание сканов агентом на компьютере с LM Studio.
 *
 * Сервер не достучится до компьютера за NAT, поэтому агент сам забирает сканы из очереди.
 * Здесь — подключить компьютер (выдать токен), увидеть, на связи ли он, и сколько сканов ждёт.
 */
export function OcrAgentManager() {
  const [status, setStatus] = useState<OcrQueueStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('Компьютер с LM Studio');
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await getOcrQueueStatus());
      setError(null);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось получить состояние распознавания'));
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const enroll = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await enrollOcrAgent(name.trim());
      setToken(res.token);
      setCopied(false);
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось подключить компьютер'));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: number, agentName: string) => {
    if (!confirm(`Отключить «${agentName}»? Его незавершённые сканы вернутся в очередь.`)) return;
    try {
      await revokeOcrAgent(id);
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось отключить компьютер'));
    }
  };

  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const anyOnline = status?.agents.some((a) => a.online) ?? false;

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={{ ...styles.dot, background: anyOnline ? theme.accent.green : theme.text.muted }} />
        <span style={styles.title}>Распознавание сканов · агент на компьютере</span>
      </div>
      <p style={styles.desc}>
        Договоры-сканы распознаёт chandra-ocr-2 в LM Studio на вашем компьютере — документы не
        уходят в облако. Сервер до компьютера не достучится, поэтому агент сам забирает сканы из
        очереди. Компьютер выключен — сканы ждут и распознаются, когда его включат.
      </p>

      {error && <div style={styles.errBox}>{error}</div>}

      {status && (
        <div style={styles.queue}>
          <span>ждут: <b>{status.pending}</b></span>
          <span>в работе: <b>{status.leased}</b></span>
          <span>готово: <b>{status.done}</b></span>
          <span style={status.failed ? { color: theme.accent.red } : undefined}>
            не удалось: <b>{status.failed}</b>
          </span>
        </div>
      )}

      {status && status.agents.length > 0 && (
        <div style={styles.list}>
          {status.agents.map((a) => (
            <div key={a.id} style={styles.agentRow}>
              <span style={{ ...styles.dot, background: a.online ? theme.accent.green : theme.text.muted }} />
              <div style={styles.agentMain}>
                <div style={styles.agentName}>{a.name}</div>
                <div style={styles.agentMeta}>
                  {a.online ? 'на связи' : 'не на связи'} · отмечался {ago(a.last_seen_at)}
                  {a.model ? ` · ${a.model}` : ''}
                  {a.agent_version ? ` · v${a.agent_version}` : ''}
                </div>
              </div>
              <button type="button" style={styles.revokeBtn} onClick={() => revoke(a.id, a.name)}>
                Отключить
              </button>
            </div>
          ))}
        </div>
      )}

      {status && status.agents.length === 0 && (
        <div style={styles.hint}>Ни один компьютер не подключён — сканы будут копиться в очереди.</div>
      )}

      <div style={styles.enrollRow}>
        <input
          style={styles.input}
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          placeholder="Название компьютера"
        />
        <button type="button" className="t-btn t-btn-amber" style={styles.btn} onClick={enroll} disabled={busy}>
          {busy ? 'Подключаю…' : 'Подключить компьютер'}
        </button>
      </div>

      {token && (
        <div style={styles.tokenBox}>
          <div style={styles.tokenWarn}>
            Токен показывается один раз — в базе хранится только его хэш. Скопируйте сейчас.
          </div>
          <div style={styles.tokenRow}>
            <code style={styles.token}>{token}</code>
            <button type="button" style={styles.copyBtn} onClick={copy}>{copied ? 'Скопировано' : 'Копировать'}</button>
          </div>
          <div style={styles.hint}>
            На компьютере с LM Studio: загрузите chandra-ocr-2 и запустите сервер, затем дважды
            щёлкните <code style={styles.code}>install.cmd</code> из папки{' '}
            <code style={styles.code}>meridian-web/ocr-agent</code> и вставьте токен.
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12,
    padding: 20, display: 'flex', flexDirection: 'column', gap: 12, marginTop: 16,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  title: { fontFamily: theme.font.heading, fontSize: 15, fontWeight: 700, color: theme.text.primary },
  desc: { margin: 0, color: theme.text.secondary, fontSize: 12.5, lineHeight: 1.55 },
  errBox: {
    background: 'rgba(255,75,110,0.1)', color: theme.accent.red, borderRadius: 8,
    padding: '8px 12px', fontSize: 12,
  },
  queue: {
    display: 'flex', flexWrap: 'wrap', gap: 16, fontFamily: theme.font.mono, fontSize: 12,
    color: theme.text.secondary,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  agentRow: {
    display: 'flex', alignItems: 'center', gap: 10, background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`, borderRadius: 8, padding: '10px 12px',
  },
  agentMain: { flex: 1, minWidth: 0 },
  agentName: { color: theme.text.primary, fontSize: 13, fontWeight: 600 },
  agentMeta: { color: theme.text.muted, fontSize: 11.5, fontFamily: theme.font.mono, overflowWrap: 'anywhere' },
  revokeBtn: {
    minHeight: 36, padding: '6px 12px', background: 'transparent', color: theme.accent.red,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
  },
  hint: { color: theme.text.muted, fontSize: 12, lineHeight: 1.55 },
  enrollRow: { display: 'flex', flexWrap: 'wrap', gap: 8 },
  input: {
    flex: '1 1 200px', minWidth: 0, background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: '9px 10px',
    fontSize: 16, fontFamily: theme.font.body,
  },
  btn: { minHeight: 40 },
  tokenBox: {
    display: 'flex', flexDirection: 'column', gap: 8, background: theme.bg.elevated,
    border: `1px solid ${theme.border.amber}`, borderRadius: 8, padding: 12,
  },
  tokenWarn: { color: theme.accent.amber, fontSize: 12, fontWeight: 600 },
  tokenRow: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  token: {
    flex: '1 1 240px', minWidth: 0, fontFamily: theme.font.mono, fontSize: 12, color: theme.text.primary,
    background: theme.bg.input, borderRadius: 6, padding: '8px 10px', overflowWrap: 'anywhere',
  },
  copyBtn: {
    minHeight: 36, padding: '6px 12px', background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
  },
  code: { fontFamily: theme.font.mono, fontSize: 11.5, color: theme.accent.amber },
};
