import { useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';
import { isAxiosError } from 'axios';
import { Modal } from '../../components/common/Modal';
import { Icon } from '../../components/common/Icon';
import { SpeakerCard } from '../../components/meeting/SpeakerCard';
import { retryFinalization } from '../../api/finalization';
import { getSpeakerRoles, putSpeakerRole } from '../../api/speakerRoles';
import { toPublicSpeakerSide } from '../../lib/speakerSides';
import type { PublicSpeakerSide } from '../../lib/speakerSides';
import type { SpeakerRoleOut, TranscriptSegmentRecord } from '../../types';
import { buildSpeakerList, humanSpeakerLabel } from './speakerList';
import { SpeakerChips } from './SpeakerChips';
import styles from './SpeakersEditor.module.css';

interface ISpeakersEditorProps {
  meetingId: number;
  segments: TranscriptSegmentRecord[];
  /** Актуальный список ролей (после загрузки и после каждого сохранения) — для имён в транскрипте. */
  onRolesChange?: (roles: SpeakerRoleOut[]) => void;
  /** Пересборка протокола запущена. */
  onProtocolRebuild?: () => void;
}

const noop = () => { /* роль спикера здесь не редактируется */ };

const repliesWord = (n: number): string => {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return 'реплика';
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'реплики';
  return 'реплик';
};

/** Полоса «Спикеры» страницы прошедшей встречи: чипы спикеров; по клику — модалка-редактор (имя, сторона) + пересборка протокола. */
export const SpeakersEditor: FC<ISpeakersEditorProps> = ({
  meetingId, segments, onRolesChange, onProtocolRebuild,
}) => {
  const speakers = useMemo(() => buildSpeakerList(segments), [segments]);
  const [roles, setRoles] = useState<SpeakerRoleOut[]>([]);
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildMsg, setRebuildMsg] = useState<{ text: string; error: boolean } | null>(null);

  useEffect(() => {
    let alive = true;
    getSpeakerRoles(meetingId).then((list) => {
      if (!alive) return;
      setRoles(list);
      setLoadError(false);
      onRolesChange?.(list);
    }).catch(() => { if (alive) setLoadError(true); });
    return () => { alive = false; };
  }, [meetingId, onRolesChange]);

  const roleByLabel = useMemo(() => new Map(roles.map((r) => [r.speaker_label, r])), [roles]);

  if (speakers.length === 0) return null;

  async function save(label: string, body: Parameters<typeof putSpeakerRole>[2]) {
    setErrors((prev) => ({ ...prev, [label]: '' }));
    try {
      const list = await putSpeakerRole(meetingId, label, body);
      setRoles(list);
      setDirty(true);
      setRebuildMsg(null);
      onRolesChange?.(list);
    } catch {
      setErrors((prev) => ({ ...prev, [label]: 'Не удалось сохранить, попробуйте ещё раз' }));
    }
  }

  const handleSetSide = (label: string, side: PublicSpeakerSide | '') => save(label, { side });
  // сторону не трогаем: шлём текущую как есть (в т.ч. устаревшую ally/third_party)
  const handleSetName = (label: string, name: string) => save(label, {
    side: roleByLabel.get(label)?.side ?? null, display_name: name.trim(),
  });

  async function handleRebuild() {
    setRebuilding(true);
    setRebuildMsg(null);
    try {
      await retryFinalization(meetingId);
      setDirty(false);
      setRebuildMsg({ text: 'Протокол пересобирается', error: false });
      onProtocolRebuild?.();
    } catch (e) {
      const busy = isAxiosError(e) && e.response?.status === 409;
      setRebuildMsg({ text: busy ? 'Протокол уже собирается' : 'Не удалось запустить пересборку', error: true });
    } finally {
      setRebuilding(false);
    }
  }

  const close = () => setOpen(false);

  return (
    <section className={styles.wrap}>
      <div className={styles.strip}>
        <button type="button" className={styles.toggle} aria-haspopup="dialog" onClick={() => setOpen(true)}>
          <span className={styles.title}>Спикеры · {speakers.length}</span>
          <span className={styles.action}>Изменить</span>
        </button>
        <div className={styles.chips}>
          <SpeakerChips speakers={speakers} roleByLabel={roleByLabel} onClick={() => setOpen(true)} />
        </div>
      </div>
      <Modal open={open} onClose={close} maxWidth={820}>
        <div className={styles.head}>
          <h2 className={styles.heading}>Спикеры · {speakers.length}</h2>
          <button type="button" className={styles.close} aria-label="Закрыть" onClick={close}>
            <Icon name="close" size={18} aria-hidden />
          </button>
        </div>
        {loadError && <div className={styles.error}>Не удалось загрузить имена и стороны</div>}
        <div className={styles.grid}>
          {speakers.map((s) => {
            const role = roleByLabel.get(s.label);
            return (
              <div key={s.label} className={styles.item}>
                <SpeakerCard
                  label={s.label}
                  name={role?.display_name ?? ''}
                  placeholder={humanSpeakerLabel(s.label)}
                  side={toPublicSpeakerSide(role?.side)}
                  role="unknown"
                  canEdit
                  roleEnabled={false}
                  onSetName={handleSetName}
                  onSetSide={handleSetSide}
                  onSetRole={noop}
                />
                <div className={styles.meta}>
                  <span className={styles.count}>{s.count} {repliesWord(s.count)}</span>
                  {s.sample && <span className={styles.sample}>«{s.sample}»</span>}
                </div>
                {errors[s.label] && <div className={styles.error} role="alert">{errors[s.label]}</div>}
              </div>
            );
          })}
        </div>
        <div className={styles.footer}>
          <span className={styles.status}>
            {rebuildMsg ? (
              <span className={rebuildMsg.error ? styles.error : styles.hint} role="status">{rebuildMsg.text}</span>
            ) : dirty && <span className={styles.hint}>Имена и стороны попадут в протокол после пересборки</span>}
          </span>
          <button
            type="button"
            className={`t-btn t-btn-amber ${styles.rebuildBtn}`}
            disabled={rebuilding}
            onClick={handleRebuild}
          >
            Пересобрать протокол
          </button>
        </div>
      </Modal>
    </section>
  );
};
