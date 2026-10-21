import { useState } from 'react';
import type { FC } from 'react';
import { Modal } from '../components/common';
import { useDesktopDevices, useRevokeDevice } from '../hooks/queries/desktop';
import type { IDesktopDevice } from '../api/desktop';
import { DESKTOP_DOWNLOAD_WINDOWS, DESKTOP_DOWNLOAD_MACOS } from '../lib/desktopDownloads';
import { formatRelativeTime } from '../lib/relativeTime';
import { apiErrorMessage } from '../lib/apiError';
import styles from './DesktopAppPage.module.css';
import { cx } from '../utils/cx';

interface IProps {
  onBack: () => void;
}

const FEATURES = [
  'Запись встречи без интернета: микрофон и звук компьютера пишутся на устройстве.',
  'На Windows записывает звук Zoom, Teams и других программ для встреч.',
  'Распознавание речи идёт на вашем компьютере, а не на сервере.',
  'Готовая встреча сама уходит на сервер, где формируется протокол.',
];

const WINDOWS_STEPS = [
  'Запустите скачанный установщик.',
  'Если появилось «Windows защитил ваш компьютер», нажмите «Подробнее».',
  'Нажмите «Выполнить в любом случае».',
];

const MACOS_STEPS = [
  'Откройте .dmg и перетащите Meridian в «Программы».',
  'Запустите приложение. Система сообщит, что не может проверить разработчика.',
  'Откройте «Системные настройки → Конфиденциальность и безопасность» и нажмите «Всё равно открыть».',
  'При первой записи разрешите доступ к микрофону.',
];

const platformLabel = (platform: string | null): string => {
  const p = (platform ?? '').toLowerCase();
  if (p.startsWith('win')) return 'Windows';
  if (p.startsWith('mac') || p === 'darwin') return 'macOS';
  return platform || 'Неизвестная платформа';
};

const StepList: FC<{ steps: string[] }> = ({ steps }) => (
  <ol className={styles.steps}>
    {steps.map((s) => <li key={s} className="dk-text">{s}</li>)}
  </ol>
);

export const DesktopAppPage: FC<IProps> = ({ onBack }) => {
  const { data: devices = [], isLoading, error, refetch } = useDesktopDevices();
  const revokeMut = useRevokeDevice();
  const [target, setTarget] = useState<IDesktopDevice | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const closeModal = () => {
    if (revokeMut.isPending) return;
    setTarget(null);
    setRevokeError(null);
  };

  const confirmRevoke = async () => {
    if (!target) return;
    setRevokeError(null);
    try {
      await revokeMut.mutateAsync(target.id);
      setTarget(null);
    } catch (e) {
      setRevokeError(apiErrorMessage(e, 'Не удалось отключить устройство'));
    }
  };

  return (
    <div className={cx('dk-page mobile-content-pad', styles.container)}>
      <div className="dk-wrap">
        <div className={styles.topBar}>
          <button type="button" onClick={onBack} className={cx('t-btn dk-device-btn', styles.backBtn)}>
            &larr; Проекты
          </button>
          <span className={styles.topTitle}>ПРИЛОЖЕНИЕ ДЛЯ ПК</span>
        </div>

        <section className={styles.card}>
          <h2 className={styles.h2}>Скачать</h2>
          <div className="dk-downloads">
            <a className={cx('dk-btn t-btn', styles.primaryBtn)} href={DESKTOP_DOWNLOAD_WINDOWS} target="_blank" rel="noopener noreferrer">
              Windows (.exe)
            </a>
            <a className={cx('dk-btn t-btn', styles.primaryBtn)} href={DESKTOP_DOWNLOAD_MACOS} target="_blank" rel="noopener noreferrer">
              macOS, Apple Silicon (.dmg)
            </a>
          </div>
          <ul className={styles.list}>
            {FEATURES.map((f) => <li key={f} className="dk-text">{f}</li>)}
          </ul>
        </section>

        <section className={styles.card}>
          <h2 className={styles.h2}>Установка</h2>
          <div className="dk-steps">
            <div>
              <h3 className={styles.h3}>Windows</h3>
              <StepList steps={WINDOWS_STEPS} />
            </div>
            <div>
              <h3 className={styles.h3}>macOS</h3>
              <StepList steps={MACOS_STEPS} />
            </div>
          </div>
        </section>

        <section className={styles.card}>
          <h2 className={styles.h2}>Мои устройства</h2>
          {isLoading && <p className={styles.muted}>Загрузка...</p>}
          {error && (
            <div className={styles.errorBox} role="alert">
              <span className="dk-text">{apiErrorMessage(error, 'Не удалось загрузить список устройств')}</span>
              <button type="button" className={cx('t-btn dk-device-btn', styles.ghostBtn)} onClick={() => refetch()}>
                Повторить
              </button>
            </div>
          )}
          {!isLoading && !error && devices.length === 0 && (
            <p className={styles.muted}>Устройств пока нет. Войдите в приложении тем же email и паролем.</p>
          )}
          {devices.length > 0 && (
            <div className={styles.deviceList}>
              {devices.map((d) => (
                <div key={d.id} className={cx('dk-device', styles.device)}>
                  <div className={styles.deviceInfo}>
                    <div className={cx('dk-text', styles.deviceName)}>{d.name}</div>
                    <div className={cx('dk-text', styles.deviceMeta)}>
                      {platformLabel(d.platform)}
                      {d.app_version ? ` · версия ${d.app_version}` : ''}
                    </div>
                    <div className={styles.deviceMeta}>В сети: {formatRelativeTime(d.last_seen_at)}</div>
                  </div>
                  <button
                    type="button"
                    className={cx('t-btn t-btn-red dk-device-btn', styles.dangerBtn)}
                    onClick={() => { setRevokeError(null); setTarget(d); }}
                  >
                    Отключить
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <Modal open={target !== null} onClose={closeModal} maxWidth={420}>
        <h3 className={styles.h3}>Отключить устройство?</h3>
        <p className={cx('dk-text', styles.muted)}>
          «{target?.name}» перестанет отправлять встречи. Чтобы вернуть его, войдите в приложении заново.
        </p>
        {revokeError && <div className={cx('dk-text', styles.errorText)} role="alert">{revokeError}</div>}
        <div className={styles.modalActions}>
          <button type="button" className={cx('t-btn dk-device-btn', styles.ghostBtn)} onClick={closeModal} disabled={revokeMut.isPending}>
            Отмена
          </button>
          <button type="button" className={cx('t-btn t-btn-red dk-device-btn', styles.dangerBtn)} onClick={confirmRevoke} disabled={revokeMut.isPending}>
            {revokeMut.isPending ? 'Отключаю...' : 'Отключить'}
          </button>
        </div>
      </Modal>
    </div>
  );
};
