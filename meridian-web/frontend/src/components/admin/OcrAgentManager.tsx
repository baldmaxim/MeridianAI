import { useCallback, useEffect, useState } from 'react';
import { apiErrorMessage } from '../../lib/apiError';
import { enrollOcrAgent, getOcrQueueStatus, revokeOcrAgent } from '../../api/ocrAgents';
import type { OcrQueueStatus } from '../../api/ocrAgents';
import styles from './OcrAgentManager.module.css';
import { cx } from '../../utils/cx';
import { TextInput } from '../common';

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
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={cx(styles.dot, anyOnline ? styles.dotOnline : styles.dotOffline)} />
        <span className={styles.title}>Распознавание сканов · агент на компьютере</span>
      </div>
      <p className={styles.desc}>
        Договоры-сканы распознаёт chandra-ocr-2 в LM Studio на вашем компьютере — документы не
        уходят в облако. Сервер до компьютера не достучится, поэтому агент сам забирает сканы из
        очереди. Компьютер выключен — сканы ждут и распознаются, когда его включат.
      </p>

      {error && <div className={styles.errBox}>{error}</div>}

      {status && (
        <div className={styles.queue}>
          <span>ждут: <b>{status.pending}</b></span>
          <span>в работе: <b>{status.leased}</b></span>
          <span>готово: <b>{status.done}</b></span>
          <span className={cx(status.failed > 0 && styles.queueFailed)}>
            не удалось: <b>{status.failed}</b>
          </span>
        </div>
      )}

      {status && status.agents.length > 0 && (
        <div className={styles.list}>
          {status.agents.map((a) => (
            <div key={a.id} className={styles.agentRow}>
              <span className={cx(styles.dot, a.online ? styles.dotOnline : styles.dotOffline)} />
              <div className={styles.agentMain}>
                <div className={styles.agentName}>{a.name}</div>
                <div className={styles.agentMeta}>
                  {a.online ? 'на связи' : 'не на связи'} · отмечался {ago(a.last_seen_at)}
                  {a.model ? ` · ${a.model}` : ''}
                  {a.agent_version ? ` · v${a.agent_version}` : ''}
                </div>
              </div>
              <button type="button" className={styles.revokeBtn} onClick={() => revoke(a.id, a.name)}>
                Отключить
              </button>
            </div>
          ))}
        </div>
      )}

      {status && status.agents.length === 0 && (
        <div className={styles.hint}>Ни один компьютер не подключён — сканы будут копиться в очереди.</div>
      )}

      <div className={styles.enrollRow}>
        <TextInput
          className={styles.nameField}
          inputClassName={styles.input}
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          onClear={() => setName('')}
          clearLabel="название компьютера"
          placeholder="Название компьютера"
        />
        <button type="button" className={cx('t-btn t-btn-amber', styles.btn)} onClick={enroll} disabled={busy}>
          {busy ? 'Подключаю…' : 'Подключить компьютер'}
        </button>
      </div>

      {token && (
        <div className={styles.tokenBox}>
          <div className={styles.tokenWarn}>
            Токен показывается один раз — в базе хранится только его хэш. Скопируйте сейчас.
          </div>
          <div className={styles.tokenRow}>
            <code className={styles.token}>{token}</code>
            <button type="button" className={styles.copyBtn} onClick={copy}>{copied ? 'Скопировано' : 'Копировать'}</button>
          </div>
          <div className={styles.hint}>
            На компьютере с LM Studio: загрузите chandra-ocr-2 и запустите сервер, затем дважды
            щёлкните <code className={styles.code}>install.cmd</code> из папки{' '}
            <code className={styles.code}>meridian-web/ocr-agent</code> и вставьте токен.
          </div>
        </div>
      )}
    </div>
  );
}
