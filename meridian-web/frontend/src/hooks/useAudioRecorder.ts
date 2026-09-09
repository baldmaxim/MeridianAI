import { useRef, useCallback, useState } from 'react';
import type {
  AudioCaptureMetadataClient,
  AudioConstraintPreset,
} from '../audio/audioCaptureTypes';
import {
  LEGACY_AUDIO_CONSTRAINTS,
  buildAudioCaptureMetadataClient,
  constraintsFromPreset,
} from '../audio/audioCaptureMetadata';
import { buildAudioFrameV2 } from '../audio/audioFrameV2';
import {
  SystemAudioError,
  SYSTEM_AUDIO_ERROR_TEXT,
  captureSystemAudio,
  onSystemAudioEnded,
  stopSystemAudio,
} from '../audio/systemAudio';
import type { SystemAudioErrorCode } from '../audio/systemAudio';

/** Конфиг захвата (Этап 15/16): устройство/route + пресет + опц. multichannel shadow. */
export interface AudioRecorderCaptureConfig {
  deviceId?: string | null;
  preset?: AudioConstraintPreset;
  multichannelShadowEnabled?: boolean;
  // Онлайн-встреча: дополнительно захватывать звук вкладки/экрана (голос второй стороны).
  systemAudioEnabled?: boolean;
}

/** Уровни двух источников: микрофон = наша сторона, звук встречи = сторона оппонента. */
export interface AudioSourceLevels {
  micRms: number;
  micPeak: number;
  systemRms: number;
  systemPeak: number;
  systemActive: boolean;
}

/** Состояние захвата звука онлайн-встречи (для UI и тостов). */
export interface SystemAudioState {
  active: boolean;
  error?: SystemAudioErrorCode;
  message?: string;
}

/** Опции захвата: динамический getConfig() (читается на каждом start) + emit metadata + v2 shadow. */
export interface AudioRecorderCaptureOptions {
  getConfig?: () => AudioRecorderCaptureConfig | null | undefined;
  onCaptureMetadata?: (metadata: AudioCaptureMetadataClient) => void;
  // Этап 16: отправка MAUD2 v2 shadow-кадров (с backpressure-дропом на стороне вызывающего).
  // Никогда не вызывается для legacy mono — тот идёт через sendBinary как раньше.
  sendShadowFrame?: (data: ArrayBuffer) => void;
  // Онлайн-захват: периодические уровни микрофона и звука встречи (~150 мс) — по ним backend
  // определяет сторону реплики. Числа, без аудио.
  onSourceLevels?: (levels: AudioSourceLevels) => void;
  // Онлайн-захват: включился / отвалился / не выдан. Запись при ошибке НЕ прерывается.
  onSystemAudioState?: (state: SystemAudioState) => void;
}

/** Как часто шлём уровни источников (мс). Совпадает с observer-устройством. */
const SOURCE_LEVELS_INTERVAL_MS = 150;

/**
 * Browser audio capture hook.
 * Captures microphone audio, downsamples to 16kHz 16-bit mono PCM,
 * and sends binary chunks via provided sendBinary callback.
 *
 * getUserMedia вызывается ТОЛЬКО из start() (по явному нажатию пользователя) —
 * важно для мобильного Safari/Chrome. onLevel — колбэк уровня сигнала (0..1) для индикатора.
 *
 * Этап 15: опциональный captureOptions выбирает device/route. Если getConfig вернёт null/undefined
 * (пользователь ничего не выбрал) — поведение как раньше (legacy mono 16k). Бинарный протокол НЕ
 * меняется: стрим остаётся mono 16kHz; preset влияет только на getUserMedia-хинты захвата.
 * TODO(stage16): multichannel PCM protocol / interleaved channels.
 *
 * Онлайн-встречи: при systemAudioEnabled дополнительно берётся звук вкладки/экрана и
 * микшируется в тот же mono 16kHz поток — без него ассистент не слышит вторую сторону
 * (её голос идёт в наушники, а echoCancellation вырезает его из микрофона). Уровни двух
 * источников отдаются наверх через onSourceLevels: микрофон = мы, звук встречи = оппонент.
 * Отказ от захвата экрана никогда не прерывает запись — остаётся очный mic-only сценарий.
 */
export function useAudioRecorder(
  sendBinary: (data: ArrayBuffer) => void,
  onLevel?: (level: number) => void,
  onInterrupt?: () => void,
  captureOptions?: AudioRecorderCaptureOptions,
) {
  const [isRecording, setIsRecording] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const mcWorkletRef = useRef<AudioWorkletNode | null>(null);
  const mcSeqRef = useRef(0);
  const sinkRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const stoppedRef = useRef(false);
  // Онлайн-захват: поток вкладки/экрана + узлы измерения уровней двух источников.
  const sysStreamRef = useRef<MediaStream | null>(null);
  const sysSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const sysUnsubRef = useRef<(() => void) | null>(null);
  const levelsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // onInterrupt держим в ref — чтобы инлайн-колбэк не пересоздавал start/stop.
  const onInterruptRef = useRef(onInterrupt);
  onInterruptRef.current = onInterrupt;
  // captureOptions держим в ref — чтобы свежий выбор устройства читался на каждом start().
  const captureRef = useRef(captureOptions);
  captureRef.current = captureOptions;

  /**
   * preCapturedSystemStream — уже полученный поток вкладки/экрана. Нужен потому, что
   * getDisplayMedia требует «свежего» клика: если между нажатием «Начать» и стартом записи
   * успели сходить за созданием встречи и подключением WS, браузер диалог уже не покажет.
   * Вызывающий берёт поток первым действием обработчика клика и передаёт сюда.
   */
  const start = useCallback(async (preCapturedSystemStream?: MediaStream | null) => {
    try {
      const cfg = captureRef.current?.getConfig?.() || null;
      const preset = cfg?.preset;
      const deviceId = cfg?.deviceId || null;
      const onSysState = captureRef.current?.onSystemAudioState;

      // Звук онлайн-встречи просим ПЕРВЫМ: диалог доступа к микрофону съедает разрешение
      // на getDisplayMedia. Отказ/ошибка НИКОГДА не отменяет запись — просто продолжаем
      // с одного микрофона (очная встреча).
      let sysStream: MediaStream | null = preCapturedSystemStream || null;
      if (sysStream) {
        sysStreamRef.current = sysStream;
      } else if (cfg?.systemAudioEnabled) {
        try {
          sysStream = await captureSystemAudio();
          sysStreamRef.current = sysStream;
        } catch (sysErr) {
          const code = sysErr instanceof SystemAudioError ? sysErr.code : 'failed';
          onSysState?.({ active: false, error: code, message: SYSTEM_AUDIO_ERROR_TEXT[code] });
        }
      }

      // Если ничего не выбрано (нет deviceId и нет/default пресета) — legacy constraints (как раньше).
      const useLegacy = !deviceId && (!preset || preset.route === 'browser_default');
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia(
          useLegacy || !preset ? LEGACY_AUDIO_CONSTRAINTS : constraintsFromPreset(preset, deviceId),
        );
      } catch (constraintErr) {
        // Браузер отклонил ideal/exact (напр. устройство пропало) → safe fallback (MVP не ломаем).
        console.warn('Audio constraints rejected, falling back to default mic:', constraintErr);
        stream = await navigator.mediaDevices.getUserMedia(LEGACY_AUDIO_CONSTRAINTS);
      }
      streamRef.current = stream;
      stoppedRef.current = false;

      // Этап 15: безопасная capture metadata (route/каналы/sample rate + хэши, без raw label/id).
      // Не блокирует и не ломает запись при ошибке.
      try {
        const onMeta = captureRef.current?.onCaptureMetadata;
        if (onMeta && preset) {
          const track = stream.getAudioTracks()[0];
          const meta = await buildAudioCaptureMetadataClient({
            preset,
            deviceId,
            deviceLabel: track?.label || null,
            settings: track?.getSettings?.() || null,
            nowMs: Date.now(),
            multichannelShadowEnabled: !!cfg?.multichannelShadowEnabled,
          });
          onMeta(meta);
        }
      } catch (metaErr) {
        console.warn('Audio capture metadata build failed (ignored):', metaErr);
      }

      const context = new AudioContext({ sampleRate: 16000 });
      contextRef.current = context;

      // iOS/Android: при блокировке экрана / входящем звонке AudioContext уходит в
      // 'interrupted'/'suspended', а mic-трек может завершиться. Сигналим наверх,
      // чтобы UI показал «возобновить запись». Гасим во время намеренного stop().
      // sawRunning гасит ложное 'suspended' на старте (до первого 'running').
      let sawRunning = (context.state as string) === 'running';
      context.onstatechange = () => {
        if (stoppedRef.current) return;
        const st = context.state as string;
        if (st === 'running') { sawRunning = true; return; }
        if (st === 'interrupted' || (st === 'suspended' && sawRunning)) {
          onInterruptRef.current?.();
        }
      };
      stream.getAudioTracks().forEach((t) => {
        t.onended = () => { if (!stoppedRef.current) onInterruptRef.current?.(); };
      });

      // Этап 16: включаем multichannel shadow только если выбрано И трек реально стерео+.
      const trackSettings = stream.getAudioTracks()[0]?.getSettings?.() || {};
      const actualChannels = typeof trackSettings.channelCount === 'number' ? trackSettings.channelCount : 1;
      const enableMulti = !!cfg?.multichannelShadowEnabled
        && actualChannels >= 2
        && !!captureRef.current?.sendShadowFrame;

      // Create AudioWorklet for PCM extraction.
      // pcm-processor = legacy mono (production STT, без изменений).
      // mc-shadow-processor = Этап 16 multichannel interleaved (только shadow, регистрируется всегда,
      // но узел создаётся лишь при enableMulti).
      const workletCode = `
        class PCMProcessor extends AudioWorkletProcessor {
          process(inputs) {
            const input = inputs[0]?.[0];
            if (input && input.length > 0) {
              // Convert Float32 to Int16
              const int16 = new Int16Array(input.length);
              for (let i = 0; i < input.length; i++) {
                const s = Math.max(-1, Math.min(1, input[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
              }
              this.port.postMessage(int16.buffer, [int16.buffer]);
            }
            return true;
          }
        }
        registerProcessor('pcm-processor', PCMProcessor);
        class MCShadowProcessor extends AudioWorkletProcessor {
          constructor(options) {
            super();
            this._channels = (options && options.processorOptions && options.processorOptions.channels) || 1;
          }
          process(inputs) {
            const input = inputs[0];
            if (!input || input.length === 0) return true;
            const ch = Math.min(this._channels, input.length);
            const frames = input[0] ? input[0].length : 0;
            if (ch < 2 || frames === 0) return true;
            const inter = new Int16Array(frames * ch);
            for (let f = 0; f < frames; f++) {
              for (let c = 0; c < ch; c++) {
                const arr = input[c];
                const v = arr ? Math.max(-1, Math.min(1, arr[f])) : 0;
                inter[f * ch + c] = v < 0 ? v * 0x8000 : v * 0x7FFF;
              }
            }
            this.port.postMessage({ interleaved: inter.buffer, channels: ch, frames }, [inter.buffer]);
            return true;
          }
        }
        registerProcessor('mc-shadow-processor', MCShadowProcessor);
      `;

      const blob = new Blob([workletCode], { type: 'application/javascript' });
      const url = URL.createObjectURL(blob);

      await context.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, 'pcm-processor');
      workletRef.current = worklet;

      // Buffer chunks and send every ~100ms (1600 samples at 16kHz = 100ms)
      // 100ms is the low end of ElevenLabs recommended range (0.1-1s)
      // Provides lowest latency for partial transcripts
      let buffer = new Int16Array(0);
      const CHUNK_SIZE = 1600; // 100ms at 16kHz

      worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        const newData = new Int16Array(event.data);

        // Уровень сигнала (RMS, 0..1) для индикатора
        if (onLevel && newData.length) {
          let sum = 0;
          for (let i = 0; i < newData.length; i++) {
            const v = newData[i] / 0x8000;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / newData.length);
          onLevel(Math.min(1, rms * 2.5));
        }

        const merged = new Int16Array(buffer.length + newData.length);
        merged.set(buffer);
        merged.set(newData, buffer.length);
        buffer = merged;

        while (buffer.length >= CHUNK_SIZE) {
          const chunk = buffer.slice(0, CHUNK_SIZE);
          buffer = buffer.slice(CHUNK_SIZE);
          sendBinary(chunk.buffer);
        }
      };

      // Микшер обоих источников. channelCount=1/explicit — принудительный даунмикс в mono:
      // звук встречи часто стерео, а pcm-processor читает только первый канал, и без
      // явного даунмикса правый канал (часть голоса оппонента) потерялся бы.
      const mixNode = context.createGain();
      mixNode.channelCount = 1;
      mixNode.channelCountMode = 'explicit';
      mixNode.channelInterpretation = 'speakers';
      source.connect(mixNode);
      mixNode.connect(worklet);
      // НЕ подключаем граф к context.destination: на iOS любой активный output
      // поднимает play-and-record аудиосессию, и движок выводит звук в динамик в
      // обход «без звука» — это и есть системный звук старта (как у диктофона).
      // MediaStreamAudioDestinationNode тянет граф (worklet.process() вызывается),
      // но аудио уходит в выбрасываемый MediaStream, а НЕ в динамик.
      const sink = context.createMediaStreamDestination();
      sinkRef.current = sink;
      worklet.connect(sink);

      // --- Звук онлайн-встречи: подмешиваем в тот же mono-поток + меряем уровни ---
      // Микрофон = наша сторона, звук встречи = сторона оппонента. Сами уровни (числа,
      // не аудио) уходят наверх и позволяют backend'у пометить, чья это была реплика.
      const micAnalyser = context.createAnalyser();
      micAnalyser.fftSize = 1024;
      source.connect(micAnalyser);

      let sysAnalyser: AnalyserNode | null = null;
      if (sysStream) {
        try {
          const sysSource = context.createMediaStreamSource(sysStream);
          sysSourceRef.current = sysSource;
          sysSource.connect(mixNode);
          sysAnalyser = context.createAnalyser();
          sysAnalyser.fftSize = 1024;
          sysSource.connect(sysAnalyser);
          // Пользователь нажал «Прекратить доступ» / закрыл вкладку встречи.
          sysUnsubRef.current = onSystemAudioEnded(sysStream, () => {
            if (stoppedRef.current) return;
            sysAnalyser = null;
            try { sysSourceRef.current?.disconnect(); } catch { /* уже отключён */ }
            sysSourceRef.current = null;
            onSysState?.({ active: false });
          });
          onSysState?.({ active: true });
        } catch (mixErr) {
          console.warn('System audio mix failed (ignored, mic unaffected):', mixErr);
          stopSystemAudio(sysStream);
          sysStreamRef.current = null;
          onSysState?.({ active: false, error: 'failed', message: SYSTEM_AUDIO_ERROR_TEXT.failed });
        }
      }

      const onSourceLevels = captureRef.current?.onSourceLevels;
      if (onSourceLevels) {
        const micBuf = new Float32Array(micAnalyser.fftSize);
        const sysBuf = new Float32Array(1024);
        const measure = (node: AnalyserNode | null, buf: Float32Array<ArrayBuffer>): [number, number] => {
          if (!node) return [0, 0];
          node.getFloatTimeDomainData(buf);
          let sum = 0;
          let peak = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = buf[i];
            sum += v * v;
            const av = Math.abs(v);
            if (av > peak) peak = av;
          }
          return [Math.sqrt(sum / buf.length), peak];
        };
        levelsTimerRef.current = setInterval(() => {
          if (stoppedRef.current) return;
          const [micRms, micPeak] = measure(micAnalyser, micBuf);
          const [systemRms, systemPeak] = measure(sysAnalyser, sysBuf);
          onSourceLevels({
            micRms, micPeak, systemRms, systemPeak, systemActive: sysAnalyser !== null,
          });
        }, SOURCE_LEVELS_INTERVAL_MS);
      }

      // Этап 16: multichannel v2 shadow-стрим (опционально). Полностью отдельная ветка —
      // если она сломается, legacy mono выше уже работает и не зависит от неё.
      if (enableMulti) {
        try {
          mcSeqRef.current = 0;
          const mcWorklet = new AudioWorkletNode(context, 'mc-shadow-processor', {
            channelCount: actualChannels,
            channelCountMode: 'explicit',
            channelInterpretation: 'discrete',
            processorOptions: { channels: actualChannels },
          });
          mcWorkletRef.current = mcWorklet;
          const sendShadow = captureRef.current?.sendShadowFrame;
          const route = preset?.route || 'unknown';
          const sampleRate = Math.round(context.sampleRate);
          const MC_FRAMES = 1600; // 100мс @16к на канал
          let mcBuffer = new Int16Array(0);
          let mcChannels = actualChannels;

          mcWorklet.port.onmessage = (e: MessageEvent<{ interleaved: ArrayBuffer; channels: number }>) => {
            if (stoppedRef.current || !sendShadow) return;
            const { interleaved, channels } = e.data;
            if (channels !== mcChannels) { mcBuffer = new Int16Array(0); mcChannels = channels; }
            const incoming = new Int16Array(interleaved);
            const merged = new Int16Array(mcBuffer.length + incoming.length);
            merged.set(mcBuffer);
            merged.set(incoming, mcBuffer.length);
            mcBuffer = merged;
            const need = MC_FRAMES * mcChannels;
            while (mcBuffer.length >= need) {
              const chunk = mcBuffer.slice(0, need);
              mcBuffer = mcBuffer.slice(need);
              try {
                const frame = buildAudioFrameV2({
                  protocol_version: 2,
                  sequence: mcSeqRef.current++,
                  sample_rate: sampleRate,
                  channels: mcChannels,
                  codec: 'pcm16',
                  layout: 'interleaved',
                  route,
                  capture_pipeline: 'multichannel_shadow_stream',
                  frame_duration_ms: 100,
                  source_is_isolated: false,
                  created_at_ms: Date.now(),
                }, chunk);
                sendShadow(frame); // backpressure-дроп — на стороне вызывающего
              } catch {
                /* v2 build/send error не должен влиять на legacy mono */
              }
            }
          };
          source.connect(mcWorklet);
          mcWorklet.connect(sink);
        } catch (mcErr) {
          console.warn('Multichannel shadow worklet failed (ignored, mono unaffected):', mcErr);
        }
      }

      setIsRecording(true);
    } catch (err) {
      // Микрофон не поднялся — не оставляем висеть уже выданный захват экрана.
      stopSystemAudio(sysStreamRef.current);
      sysStreamRef.current = null;
      sysSourceRef.current = null;
      console.error('Failed to start audio recording:', err);
      throw err;
    }
  }, [sendBinary, onLevel]);

  const stop = useCallback(() => {
    stoppedRef.current = true;
    // Снять lifecycle-обработчики ДО close()/track.stop(), иначе они дёрнут onInterrupt.
    if (contextRef.current) contextRef.current.onstatechange = null;
    if (levelsTimerRef.current) { clearInterval(levelsTimerRef.current); levelsTimerRef.current = null; }
    if (sysUnsubRef.current) { sysUnsubRef.current(); sysUnsubRef.current = null; }
    if (sysSourceRef.current) {
      try { sysSourceRef.current.disconnect(); } catch { /* ignore */ }
      sysSourceRef.current = null;
    }
    stopSystemAudio(sysStreamRef.current);
    sysStreamRef.current = null;
    if (streamRef.current) {
      streamRef.current.getAudioTracks().forEach((t) => { t.onended = null; });
    }
    if (workletRef.current) {
      workletRef.current.disconnect();
      workletRef.current = null;
    }
    if (mcWorkletRef.current) {
      try { mcWorkletRef.current.port.onmessage = null; mcWorkletRef.current.disconnect(); } catch { /* ignore */ }
      mcWorkletRef.current = null;
    }
    if (sinkRef.current) {
      try { sinkRef.current.disconnect(); } catch { /* ignore */ }
      sinkRef.current = null;
    }
    if (contextRef.current) {
      contextRef.current.close();
      contextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (onLevel) onLevel(0);
    setIsRecording(false);
  }, [onLevel]);

  return { isRecording, start, stop };
}
