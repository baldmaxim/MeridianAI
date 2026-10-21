import { useEffect, useState } from 'react';
import { useAudioInputDevices } from '../../hooks/useAudioInputDevices';
import { useAudioSoundCheck } from '../../hooks/useAudioSoundCheck';
import { AUDIO_PRESETS, AUDIO_ROUTE_ORDER, MULTICHANNEL_CAPABLE_ROUTES } from '../../audio/audioCaptureTypes';
import type { AudioCaptureRoute } from '../../audio/audioCaptureTypes';
import {
  loadMultichannelShadowEnabled,
  presetForRoute,
  saveMultichannelShadowEnabled,
} from '../../audio/audioCaptureMetadata';
import type { AudioRecorderCaptureConfig } from '../../hooks/useAudioRecorder';
import styles from './AudioPreflightPanel.module.css';
import tone from './Tone.module.css';

/**
 * Компактная панель выбора микрофона + sound-check (Этап 15).
 * НЕ AI-профиль, НЕ выбор триггеров. Не блокирует старт записи. route — техническая зона записи.
 */
export function AudioPreflightPanel({
  onConfigChange,
}: {
  onConfigChange: (cfg: AudioRecorderCaptureConfig) => void;
}) {
  const { devices, selection, permissionGranted, error, requestPermission, setDevice, setRoute } =
    useAudioInputDevices();
  const sc = useAudioSoundCheck();
  const [open, setOpen] = useState(true);
  const [mcShadow, setMcShadow] = useState(() => loadMultichannelShadowEnabled());

  // Тоггл multichannel shadow показываем только для multi-канальных маршрутов или если sound-check
  // увидел 2+ канала. Default OFF.
  const multiCapable = MULTICHANNEL_CAPABLE_ROUTES.includes(selection.route) || (sc.channelCount ?? 0) >= 2;

  // Сообщать наверх актуальный конфиг захвата (для useAudioRecorder).
  useEffect(() => {
    onConfigChange({
      deviceId: selection.deviceId,
      preset: presetForRoute(selection.route),
      multichannelShadowEnabled: mcShadow && multiCapable,
    });
  }, [selection.deviceId, selection.route, mcShadow, multiCapable, onConfigChange]);

  // Закрытие панели останавливает sound-check (освобождает микрофон).
  useEffect(() => {
    if (!open) sc.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const statusText = (): string => {
    switch (sc.status) {
      case 'requesting_permission': return 'Запрашиваю доступ…';
      case 'running': return 'Идёт проверка…';
      case 'ok': return 'ОК — уровень в норме';
      case 'too_quiet': return 'Слишком тихо';
      case 'clipping': return 'Перегруз / клиппинг';
      case 'error': return sc.error || 'Ошибка';
      default: return '';
    }
  };
  const statusTone = sc.status === 'ok' ? tone.green
    : sc.status === 'clipping' ? tone.red
      : sc.status === 'too_quiet' ? tone.amber : tone.secondary;
  const meterTone = sc.clippingDetected ? tone.bgRed
    : sc.silenceDetected ? tone.bgAmber : tone.bgGreen;

  const selectedDevice = devices.find((d) => d.deviceId === selection.deviceId);
  const deviceLabel = selectedDevice?.label
    || (selection.deviceId ? 'Выбранное устройство' : 'Микрофон по умолчанию');

  return (
    <div className={styles.wrap}>
      <button className={styles.header} onClick={() => setOpen((o) => !o)} type="button">
        <span className={styles.headerTitle}>🎙 Микрофон и проверка звука</span>
        <span className={styles.headerMeta}>
          {AUDIO_PRESETS[selection.route]?.label || 'по умолчанию'} {open ? '▾' : '▸'}
        </span>
      </button>

      {open && (
        <div className={styles.body}>
          {!permissionGranted && (
            <div className={styles.hintBox}>
              Разрешите доступ к микрофону, чтобы увидеть устройства.
              <button className={styles.smallBtn} onClick={() => void requestPermission()} type="button">
                Разрешить доступ
              </button>
            </div>
          )}
          {error && <div className={styles.errorBox}>{error}</div>}

          <label className={styles.label}>Устройство</label>
          <select
            className={styles.select}
            value={selection.deviceId || ''}
            onChange={(e) => setDevice(e.target.value || null)}
          >
            <option value="">Микрофон по умолчанию</option>
            {devices.filter((d) => !d.isDefault || d.label).map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || 'Микрофон'}
              </option>
            ))}
          </select>

          <label className={styles.label}>Маршрут записи (техническая зона, не сторона)</label>
          <select
            className={styles.select}
            value={selection.route}
            onChange={(e) => setRoute(e.target.value as AudioCaptureRoute)}
          >
            {AUDIO_ROUTE_ORDER.map((r) => (
              <option key={r} value={r}>{AUDIO_PRESETS[r].label}</option>
            ))}
          </select>
          <div className={styles.presetDesc}>{AUDIO_PRESETS[selection.route]?.description}</div>

          <div className={styles.checkRow}>
            {sc.status === 'idle' || sc.status === 'error' ? (
              <button
                className={styles.checkBtn}
                onClick={() => void sc.start(selection.deviceId, presetForRoute(selection.route))}
                type="button"
              >
                Проверить звук
              </button>
            ) : (
              <button className={styles.checkBtnStop} onClick={() => sc.stop()} type="button">
                Остановить
              </button>
            )}
            <span className={`${styles.status} ${statusTone}`}>{statusText()}</span>
          </div>

          {(sc.status === 'running' || sc.status === 'ok' || sc.status === 'too_quiet'
            || sc.status === 'clipping') && (
            <>
              <div className={styles.meterTrack}>
                <div
                  className={`${styles.meterFill} ${meterTone}`}
                  style={{ transform: `scaleX(${Math.min(1, Math.max(0, sc.rmsLevel))})` }}
                />
              </div>
              <div className={styles.detected}>
                Частота: {sc.sampleRate ? `${sc.sampleRate} Гц` : '—'} · Каналов: {sc.channelCount ?? '—'}
              </div>
            </>
          )}

          {multiCapable && (
            <label className={styles.expRow}>
              <input
                type="checkbox"
                checked={mcShadow}
                onChange={(e) => { setMcShadow(e.target.checked); saveMultichannelShadowEnabled(e.target.checked); }}
              />
              <span className={styles.expText}>
                Экспериментально: передавать стерео/мультиканал в shadow-режиме
                <span className={styles.expHint}>
                  Не влияет на live-распознавание. Основной STT остаётся mono. Не определяет стороны участников.
                  Per-channel STT включается администратором на backend canary; этот переключатель только передаёт каналы.
                </span>
              </span>
            </label>
          )}

          <div className={styles.tips}>
            <div>Zoom H2n / USB-рекордер: выберите «USB-рекордер», поставьте по центру стола.</div>
            <div>Спикерфон: выберите «USB-спикерфон».</div>
            <div>Телефон — запасной (secondary) сценарий, не основной микрофон.</div>
          </div>
          <div className={styles.note}>
            Стрим в обработку остаётся mono 16&nbsp;кГц (multichannel — позже). Метка устройства не
            покидает браузер: в систему уходят только маршрут и хэши. «{deviceLabel}».
          </div>
        </div>
      )}
    </div>
  );
}
