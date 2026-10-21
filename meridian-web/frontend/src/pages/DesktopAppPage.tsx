import { useState } from 'react';
import type { FC, CSSProperties } from 'react';
import { Modal } from '../components/common';
import { useDesktopDevices, useRevokeDevice } from '../hooks/queries/desktop';
import type { IDesktopDevice } from '../api/desktop';
import { DESKTOP_DOWNLOAD_WINDOWS, DESKTOP_DOWNLOAD_MACOS } from '../lib/desktopDownloads';
import { formatRelativeTime } from '../lib/relativeTime';
import { apiErrorMessage } from '../lib/apiError';
import { theme } from '../styles/theme';

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
  <ol style={styles.steps}>
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
    <div className="dk-page mobile-content-pad" style={styles.container}>
      <div className="dk-wrap">
        <div style={styles.topBar}>
          <button type="button" onClick={onBack} className="t-btn dk-device-btn" style={styles.backBtn}>
            &larr; Проекты
          </button>
          <span style={styles.topTitle}>ПРИЛОЖЕНИЕ ДЛЯ ПК</span>
        </div>

        <section style={styles.card}>
          <h2 style={styles.h2}>Скачать</h2>
          <div className="dk-downloads">
            <a className="dk-btn t-btn" style={styles.primaryBtn} href={DESKTOP_DOWNLOAD_WINDOWS} target="_blank" rel="noopener noreferrer">
              Windows (.exe)
            </a>
            <a className="dk-btn t-btn" style={styles.primaryBtn} href={DESKTOP_DOWNLOAD_MACOS} target="_blank" rel="noopener noreferrer">
              macOS, Apple Silicon (.dmg)
            </a>
          </div>
          <ul style={styles.list}>
            {FEATURES.map((f) => <li key={f} className="dk-text">{f}</li>)}
          </ul>
        </section>

        <section style={styles.card}>
          <h2 style={styles.h2}>Установка</h2>
          <div className="dk-steps">
            <div>
              <h3 style={styles.h3}>Windows</h3>
              <StepList steps={WINDOWS_STEPS} />
            </div>
            <div>
              <h3 style={styles.h3}>macOS</h3>
              <StepList steps={MACOS_STEPS} />
            </div>
          </div>
        </section>

        <section style={styles.card}>
          <h2 style={styles.h2}>Мои устройства</h2>
          {isLoading && <p style={styles.muted}>Загрузка...</p>}
          {error && (
            <div style={styles.errorBox} role="alert">
              <span className="dk-text">{apiErrorMessage(error, 'Не удалось загрузить список устройств')}</span>
              <button type="button" className="t-btn dk-device-btn" style={styles.ghostBtn} onClick={() => refetch()}>
                Повторить
              </button>
            </div>
          )}
          {!isLoading && !error && devices.length === 0 && (
            <p style={styles.muted}>Устройств пока нет. Войдите в приложении тем же email и паролем.</p>
          )}
          {devices.length > 0 && (
            <div style={styles.deviceList}>
              {devices.map((d) => (
                <div key={d.id} className="dk-device" style={styles.device}>
                  <div style={styles.deviceInfo}>
                    <div className="dk-text" style={styles.deviceName}>{d.name}</div>
                    <div className="dk-text" style={styles.deviceMeta}>
                      {platformLabel(d.platform)}
                      {d.app_version ? ` · версия ${d.app_version}` : ''}
                    </div>
                    <div style={styles.deviceMeta}>В сети: {formatRelativeTime(d.last_seen_at)}</div>
                  </div>
                  <button
                    type="button"
                    className="t-btn t-btn-red dk-device-btn"
                    style={styles.dangerBtn}
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
        <h3 style={styles.h3}>Отключить устройство?</h3>
        <p className="dk-text" style={styles.muted}>
          «{target?.name}» перестанет отправлять встречи. Чтобы вернуть его, войдите в приложении заново.
        </p>
        {revokeError && <div className="dk-text" style={styles.errorText} role="alert">{revokeError}</div>}
        <div style={styles.modalActions}>
          <button type="button" className="t-btn dk-device-btn" style={styles.ghostBtn} onClick={closeModal} disabled={revokeMut.isPending}>
            Отмена
          </button>
          <button type="button" className="t-btn t-btn-red dk-device-btn" style={styles.dangerBtn} onClick={confirmRevoke} disabled={revokeMut.isPending}>
            {revokeMut.isPending ? 'Отключаю...' : 'Отключить'}
          </button>
        </div>
      </Modal>
    </div>
  );
};

const styles: Record<string, CSSProperties> = {
  container: { flex: 1, overflow: 'auto', overscrollBehavior: 'contain', minWidth: 0 },
  topBar: {
    display: 'flex', alignItems: 'center', gap: 12, paddingBottom: 12,
    borderBottom: `1px solid ${theme.border.default}`,
  },
  backBtn: {
    display: 'flex', alignItems: 'center', padding: '0 14px', background: 'transparent',
    border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber,
    cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono, fontWeight: 500, flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.mono, fontSize: 11, fontWeight: 500,
    letterSpacing: '0.16em', color: theme.text.secondary,
  },
  card: {
    background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0,
  },
  h2: { fontFamily: theme.font.heading, fontSize: 16, fontWeight: 800, color: theme.text.primary, letterSpacing: '0.04em' },
  h3: { fontFamily: theme.font.body, fontSize: 14, fontWeight: 600, color: theme.text.primary, marginBottom: 8 },
  primaryBtn: {
    background: theme.accent.amber, color: theme.bg.primary, borderRadius: 8,
    fontFamily: theme.font.body, fontSize: 14, fontWeight: 600, textAlign: 'center',
  },
  list: {
    paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6,
    fontSize: 14, lineHeight: 1.5, color: theme.text.secondary,
  },
  steps: {
    paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6,
    fontSize: 14, lineHeight: 1.5, color: theme.text.secondary,
  },
  muted: { fontSize: 14, lineHeight: 1.5, color: theme.text.secondary },
  deviceList: { display: 'flex', flexDirection: 'column', gap: 8 },
  device: {
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 10,
  },
  deviceInfo: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 },
  deviceName: { fontSize: 14, fontWeight: 600, color: theme.text.primary },
  deviceMeta: { fontSize: 12, color: theme.text.secondary, fontFamily: theme.font.mono },
  dangerBtn: {
    padding: '0 16px', background: theme.accent.redDim, border: `1px solid ${theme.accent.red}`,
    borderRadius: 8, color: theme.accent.red, cursor: 'pointer', fontSize: 13,
    fontFamily: theme.font.body, fontWeight: 600,
  },
  ghostBtn: {
    padding: '0 16px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 8, color: theme.text.primary, cursor: 'pointer', fontSize: 13, fontFamily: theme.font.body,
  },
  errorBox: {
    display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10,
    padding: 12, background: theme.accent.redDim, border: `1px solid ${theme.accent.red}`,
    borderRadius: 8, color: theme.accent.red, fontSize: 14,
  },
  errorText: { color: theme.accent.red, fontSize: 13 },
  modalActions: { display: 'flex', justifyContent: 'flex-end', gap: 10, flexWrap: 'wrap' },
};
