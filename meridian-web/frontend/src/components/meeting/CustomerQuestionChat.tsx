import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FC, KeyboardEvent, ReactNode } from 'react';
import axios from 'axios';
import { askMeeting } from '../../api/meetings';
import type { IAskSource } from '../../api/meetings';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './CustomerQuestionChat.module.css';

const QUICK_QUESTIONS = [
  'Почему так дорого?',
  'Из чего складывается цена?',
  'Какие сроки и график?',
  'Какой аванс и порядок оплаты?',
  'Что не входит в КП?',
];

const MAX_QUESTION = 1000;
const INPUT_MAX_HEIGHT = 96;
const SOURCES_VISIBLE = 3;
const FALLBACK_ERROR = 'Не удалось получить ответ';

interface IChatItem {
  id: number;
  question: string;
  answer: string | null;
  sources: IAskSource[];
  error: string | null;
}

const errorText = (e: unknown): string => {
  if (axios.isAxiosError(e)) {
    const detail: unknown = (e.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return FALLBACK_ERROR;
};

/** `**x**` → <strong>x</strong>, остальной текст — как есть (без HTML). */
const renderInline = (text: string): ReactNode[] =>
  text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>,
  );

/** markdown-lite: строки, `**жирный**`, пункты `- …`. */
const renderAnswer = (text: string): ReactNode[] => {
  const nodes: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    nodes.push(
      <ul key={`ul${nodes.length}`} className={styles.list}>
        {items.map((b, i) => <li key={i}>{renderInline(b)}</li>)}
      </ul>,
    );
  };
  text.split('\n').forEach((raw) => {
    const line = raw.trim();
    if (line.startsWith('- ')) {
      bullets.push(line.slice(2));
      return;
    }
    flush();
    if (line) nodes.push(<p key={`p${nodes.length}`} className={styles.line}>{renderInline(line)}</p>);
  });
  flush();
  return nodes;
};

interface ISourceLabel {
  label: string;
  fullTitle: string | null;
}

const uniqueSourceLabels = (sources: IAskSource[]): ISourceLabel[] => {
  const byLabel = new Map<string, ISourceLabel>();
  sources.forEach((s) => {
    const label = s.ref ? `${s.title} · ${s.ref}` : s.title;
    if (!byLabel.has(label)) byLabel.set(label, { label, fullTitle: s.full_title ?? null });
  });
  return Array.from(byLabel.values());
};

const Sources: FC<{ sources: IAskSource[] }> = ({ sources }) => {
  const [expanded, setExpanded] = useState(false);
  const labels = uniqueSourceLabels(sources);
  if (!labels.length) return null;
  const hidden = labels.length - SOURCES_VISIBLE;
  const visible = expanded || hidden <= 0 ? labels : labels.slice(0, SOURCES_VISIBLE);
  return (
    <>
      <ul className={styles.sources}>
        {visible.map((l) => <li key={l.label} title={l.fullTitle ?? undefined}>{l.label}</li>)}
      </ul>
      {hidden > 0 && !expanded && (
        <button type="button" className={styles.sourcesToggle} onClick={() => setExpanded(true)}>
          ещё {hidden}
        </button>
      )}
    </>
  );
};

/** Окно «Вопрос Заказчика»: готовый короткий ответ по КП и документам встречи. Историю при смене встречи сбрасывает key у родителя. */
export const CustomerQuestionChat: FC = () => {
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const [items, setItems] = useState<IChatItem[]>([]);
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const historyRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const nextId = useRef(1);

  const disabled = meetingId == null || loading;

  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items, loading]);

  // Авто-рост поля ввода до ~4 строк
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT)}px`;
  }, [text]);

  const send = async (raw: string) => {
    const question = raw.trim().slice(0, MAX_QUESTION);
    if (!question || meetingId == null || loading) return;
    const id = nextId.current++;
    setText('');
    setLoading(true);
    setItems((prev) => [...prev, { id, question, answer: null, sources: [], error: null }]);
    let patch: Partial<IChatItem>;
    try {
      const res = await askMeeting(meetingId, question, 'anticipate');
      patch = { answer: res.answer, sources: res.sources ?? [] };
    } catch (e) {
      patch = { error: errorText(e) };
    }
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)));
    setLoading(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text);
    }
  };

  return (
    <div className={styles.root}>
      <div className={styles.history} ref={historyRef} aria-live="polite">
        {items.length === 0 && !loading && (
          <div className={styles.empty}>
            <p className={styles.subtitle}>Ответ по КП и документам встречи</p>
            {meetingId == null && <p className={styles.hint}>Откройте или начните встречу</p>}
          </div>
        )}
        {items.map((it) => (
          <Fragment key={it.id}>
            <div className={styles.question}>{it.question}</div>
            {it.answer != null && (
              <div className={styles.answer}>
                {renderAnswer(it.answer)}
                <Sources sources={it.sources} />
              </div>
            )}
            {it.error != null && <div className={styles.error} role="alert">{it.error}</div>}
          </Fragment>
        ))}
        {loading && <div className={styles.loading}>Готовлю ответ…</div>}
      </div>

      <div className={styles.composer}>
        <div className={styles.chipsRow}>
          <div className={styles.chips}>
            {QUICK_QUESTIONS.map((q) => (
              <button key={q} type="button" className={styles.chip} disabled={disabled} onClick={() => void send(q)}>
                {q}
              </button>
            ))}
          </div>
          {items.length > 0 && (
            <button type="button" className={styles.clearHistory} disabled={loading} onClick={() => setItems([])}>
              Очистить
            </button>
          )}
        </div>
        <div className={styles.inputBox}>
          <textarea
            ref={inputRef}
            className={styles.input}
            rows={1}
            aria-label="Вопрос Заказчика"
            placeholder="Что спросит Заказчик?"
            maxLength={MAX_QUESTION}
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button type="button" className={styles.send} disabled={disabled || !text.trim()} onClick={() => void send(text)}>
            Спросить
          </button>
        </div>
      </div>
    </div>
  );
};
