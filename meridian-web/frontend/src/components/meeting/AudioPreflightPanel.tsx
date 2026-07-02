import React, { useEffect, useState } from 'react';
import { theme } from '../../styles/theme';
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
  const [open, setOpen] = useState(false);
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
  const statusColor = sc.status === 'ok' ? theme.accent.green
    : sc.status === 'clipping' ? theme.accent.red
      : sc.status === 'too_quiet' ? theme.accent.amber : theme.text.secondary;

  const selectedDevice = devices.find((d) => d.deviceId === selection.deviceId);
  const deviceLabel = selectedDevice?.label
    || (selection.deviceId ? 'Выбранное устройство' : 'Микрофон по умолчанию');

  return (
    <div style={styles.wrap}>
      <button style={styles.header} onClick={() => setOpen((o) => !o)} type="button">
        <span style={styles.headerTitle}>🎙 Микрофон и проверка звука</span>
        <span style={styles.headerMeta}>
          {AUDIO_PRESETS[selection.route]?.label || 'по умолчанию'} {open ? '▾' : '▸'}
        </span>
      </button>

      {open && (
        <div style={styles.body}>
          {!permissionGranted && (
            <div style={styles.hintBox}>
              Разрешите доступ к микрофону, чтобы увидеть устройства.
              <button style={styles.smallBtn} onClick={() => void requestPermission()} type="button">
                Разрешить доступ
              </button>
            </div>
          )}
          {error && <div style={styles.errorBox}>{error}</div>}

          <label style={styles.label}>Устройство</label>
          <select
            style={styles.select}
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

          <label style={styles.label}>Маршрут записи (техническая зона, не сторона)</label>
          <select
            style={styles.select}
            value={selection.route}
            onChange={(e) => setRoute(e.target.value as AudioCaptureRoute)}
          >
            {AUDIO_ROUTE_ORDER.map((r) => (
              <option key={r} value={r}>{AUDIO_PRESETS[r].label}</option>
            ))}
          </select>
          <div style={styles.presetDesc}>{AUDIO_PRESETS[selection.route]?.description}</div>

          <div style={styles.checkRow}>
            {sc.status === 'idle' || sc.status === 'error' ? (
              <button
                style={styles.checkBtn}
                onClick={() => void sc.start(selection.deviceId, presetForRoute(selection.route))}
                type="button"
              >
                Проверить звук
              </button>
            ) : (
              <button style={styles.checkBtnStop} onClick={() => sc.stop()} type="button">
                Остановить
              </button>
            )}
            <span style={{ ...styles.status, color: statusColor }}>{statusText()}</span>
          </div>

          {(sc.status === 'running' || sc.status === 'ok' || sc.status === 'too_quiet'
            || sc.status === 'clipping') && (
            <>
              <div style={styles.meterTrack}>
                <div style={{
                  ...styles.meterFill,
                  width: `${Math.round(sc.rmsLevel * 100)}%`,
                  background: sc.clippingDetected ? theme.accent.red
                    : sc.silenceDetected ? theme.accent.amber : theme.accent.green,
                }} />
              </div>
              <div style={styles.detected}>
                Частота: {sc.sampleRate ? `${sc.sampleRate} Гц` : '—'} · Каналов: {sc.channelCount ?? '—'}
              </div>
            </>
          )}

          {multiCapable && (
            <label style={styles.expRow}>
              <input
                type="checkbox"
                checked={mcShadow}
                onChange={(e) => { setMcShadow(e.target.checked); saveMultichannelShadowEnabled(e.target.checked); }}
              />
              <span style={styles.expText}>
                Экспериментально: передавать стерео/мультиканал в shadow-режиме
                <span style={styles.expHint}>
                  Не влияет на live-распознавание. Основной STT остаётся mono. Не определяет стороны участников.
                  Per-channel STT включается администратором на backend canary; этот переключатель только передаёт каналы.
                </span>
              </span>
            </label>
          )}

          <div style={styles.tips}>
            <div>Zoom H2n / USB-рекордер: выберите «USB-рекордер», поставьте по центру стола.</div>
            <div>Спикерфон: выберите «USB-спикерфон».</div>
            <div>Телефон — запасной (secondary) сценарий, не основной микрофон.</div>
          </div>
          <div style={styles.note}>
            Стрим в обработку остаётся mono 16&nbsp;кГц (multichannel — позже). Метка устройства не
            покидает браузер: в систему уходят только маршрут и хэши. «{deviceLabel}».
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    background: theme.bg.secondary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    margin: '8px 12px',
    overflow: 'hidden',
    flexShrink: 0,
  },
  header: {
    width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
    color: theme.text.primary, fontFamily: theme.font.body, fontSize: 13,
  },
  headerTitle: { fontWeight: 600 },
  headerMeta: { color: theme.text.secondary, fontSize: 11, fontFamily: theme.font.mono },
  body: { padding: '4px 14px 14px', display: 'flex', flexDirection: 'column', gap: 6 },
  label: { color: theme.text.secondary, fontSize: 11, marginTop: 6, fontFamily: theme.font.body },
  select: {
    background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: '7px 9px',
    fontSize: 12, fontFamily: theme.font.body,
  },
  presetDesc: { color: theme.text.muted, fontSize: 11, fontFamily: theme.font.body },
  checkRow: { display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 },
  checkBtn: {
    padding: '7px 14px', background: theme.accent.amber, color: '#080A0F', border: 'none',
    borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: theme.font.body,
  },
  checkBtnStop: {
    padding: '7px 14px', background: theme.bg.elevated, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
    fontFamily: theme.font.body,
  },
  status: { fontSize: 12, fontFamily: theme.font.mono },
  meterTrack: {
    height: 8, background: theme.bg.input, borderRadius: 4, overflow: 'hidden', marginTop: 6,
  },
  meterFill: { height: '100%', transition: 'width 80ms linear', borderRadius: 4 },
  detected: { color: theme.text.secondary, fontSize: 11, fontFamily: theme.font.mono, marginTop: 4 },
  tips: {
    marginTop: 10, display: 'flex', flexDirection: 'column', gap: 3,
    color: theme.text.secondary, fontSize: 11, fontFamily: theme.font.body,
  },
  expRow: {
    display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 10, cursor: 'pointer',
    background: theme.bg.input, borderRadius: 6, padding: '8px 10px',
  },
  expText: { display: 'flex', flexDirection: 'column', gap: 2, color: theme.text.primary, fontSize: 12 },
  expHint: { color: theme.text.muted, fontSize: 10.5, lineHeight: 1.5 },
  note: { marginTop: 8, color: theme.text.muted, fontSize: 10.5, fontFamily: theme.font.body, lineHeight: 1.5 },
  hintBox: {
    display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
    background: theme.bg.input, borderRadius: 6, padding: '8px 10px',
    color: theme.text.secondary, fontSize: 12,
  },
  smallBtn: {
    padding: '5px 10px', background: theme.accent.amber, color: '#080A0F', border: 'none',
    borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: 'pointer',
  },
  errorBox: {
    background: 'rgba(255,75,110,0.1)', color: theme.accent.red, borderRadius: 6,
    padding: '7px 10px', fontSize: 11.5,
  },
};
