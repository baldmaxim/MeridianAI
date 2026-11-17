import { useState } from 'react';
import type { FormEvent } from 'react';
import { TextInput } from '../common/TextInput';
import { apiErrorMessage } from '../../lib/apiError';
import { useMe } from '../../hooks/queries/auth';
import { useAsrTerms, useCreateAsrTerm, useRemoveAsrTerm } from '../../hooks/queries/asrTerms';
import styles from './AsrTermsList.module.css';

const splitAliases = (raw: string): string[] => raw.split(';').map((a) => a.trim()).filter(Boolean);

export function AsrTermsList() {
  const { data: me } = useMe();
  const isAdmin = me?.role === 'admin';
  const { data, isPending, error: queryError } = useAsrTerms();
  const createMut = useCreateAsrTerm();
  const removeMut = useRemoveAsrTerm();

  const [term, setTerm] = useState('');
  const [aliases, setAliases] = useState('');
  const [common, setCommon] = useState(false);
  const [query, setQuery] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const items = data ?? [];
  const q = query.trim().toLowerCase();
  const visible = q
    ? items.filter((it) => it.term.toLowerCase().includes(q) || it.aliases.some((a) => a.toLowerCase().includes(q)))
    : items;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!term.trim() || createMut.isPending) return;
    setFormError(null);
    try {
      await createMut.mutateAsync({ term: term.trim(), aliases: splitAliases(aliases), common: isAdmin && common });
      setTerm('');
      setAliases('');
      setCommon(false);
    } catch (err) {
      setFormError(apiErrorMessage(err, 'Не удалось добавить'));
    }
  }

  async function remove(id: number, name: string) {
    if (!window.confirm(`Удалить «${name}»?`)) return;
    setFormError(null);
    try {
      await removeMut.mutateAsync(id);
    } catch (err) {
      setFormError(apiErrorMessage(err, 'Не удалось удалить'));
    }
  }

  return (
    <div className={styles.root}>
      <p className={styles.hint}>
        Названия компаний, объектов, фамилии — помогают распознаванию речи. Варианты — как слово обычно искажается.
      </p>

      <form className={styles.form} onSubmit={submit}>
        <TextInput
          placeholder="Название"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onClear={() => setTerm('')}
          clearLabel="название"
          maxLength={300}
          aria-label="Название"
        />
        <TextInput
          placeholder="Варианты (через ;)"
          value={aliases}
          onChange={(e) => setAliases(e.target.value)}
          onClear={() => setAliases('')}
          clearLabel="варианты"
          aria-label="Варианты через точку с запятой"
        />
        <div className={styles.formRow}>
          {isAdmin && (
            <label className={styles.check}>
              <input type="checkbox" checked={common} onChange={(e) => setCommon(e.target.checked)} />
              Общий для всех
            </label>
          )}
          <span className={styles.spacer} />
          <button type="submit" className={styles.add} disabled={!term.trim() || createMut.isPending}>
            Добавить
          </button>
        </div>
        {formError && <div className={styles.error} role="alert">{formError}</div>}
      </form>

      <TextInput
        type="search"
        placeholder="Поиск по списку"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onClear={() => setQuery('')}
        clearLabel="поиск"
        aria-label="Поиск по списку"
      />

      {isPending ? (
        <div className={styles.muted}>Загрузка…</div>
      ) : queryError ? (
        <div className={styles.error}>{apiErrorMessage(queryError, 'Не удалось загрузить')}</div>
      ) : visible.length === 0 ? (
        <div className={styles.muted}>Пока пусто</div>
      ) : (
        <div className={styles.list}>
          {visible.map((it) => (
            <div key={it.id} className={styles.card}>
              <div className={styles.cardText}>
                <div className={styles.main}>
                  {it.term}
                  {it.is_common && <span className={styles.badge}>Общий</span>}
                </div>
                {it.aliases.length > 0 && <div className={styles.sub}>{it.aliases.join('; ')}</div>}
              </div>
              {it.can_delete && (
                <button
                  type="button"
                  className={styles.remove}
                  aria-label={`Удалить «${it.term}»`}
                  disabled={removeMut.isPending && removeMut.variables === it.id}
                  onClick={() => remove(it.id, it.term)}
                >
                  Удалить
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
