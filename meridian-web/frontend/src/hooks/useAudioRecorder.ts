import { useRef, useCallback, useState } from 'react';

/**
 * Browser audio capture hook.
 * Captures microphone audio, downsamples to 16kHz 16-bit mono PCM,
 * and sends binary chunks via provided sendBinary callback.
 *
 * getUserMedia вызывается ТОЛЬКО из start() (по явному нажатию пользователя) —
 * важно для мобильного Safari/Chrome. onLevel — колбэк уровня сигнала (0..1) для индикатора.
 */
export function useAudioRecorder(
  sendBinary: (data: ArrayBuffer) => void,
  onLevel?: (level: number) => void,
  onInterrupt?: () => void,
) {
  const [isRecording, setIsRecording] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const sinkRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const stoppedRef = useRef(false);
  // onInterrupt держим в ref — чтобы инлайн-колбэк не пересоздавал start/stop.
  const onInterruptRef = useRef(onInterrupt);
  onInterruptRef.current = onInterrupt;

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;
      stoppedRef.current = false;

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

      // Create AudioWorklet for PCM extraction
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

      source.connect(worklet);
      // НЕ подключаем граф к context.destination: на iOS любой активный output
      // поднимает play-and-record аудиосессию, и движок выводит звук в динамик в
      // обход «без звука» — это и есть системный звук старта (как у диктофона).
      // MediaStreamAudioDestinationNode тянет граф (worklet.process() вызывается),
      // но аудио уходит в выбрасываемый MediaStream, а НЕ в динамик.
      const sink = context.createMediaStreamDestination();
      sinkRef.current = sink;
      worklet.connect(sink);

      setIsRecording(true);
    } catch (err) {
      console.error('Failed to start audio recording:', err);
      throw err;
    }
  }, [sendBinary, onLevel]);

  const stop = useCallback(() => {
    stoppedRef.current = true;
    // Снять lifecycle-обработчики ДО close()/track.stop(), иначе они дёрнут onInterrupt.
    if (contextRef.current) contextRef.current.onstatechange = null;
    if (streamRef.current) {
      streamRef.current.getAudioTracks().forEach((t) => { t.onended = null; });
    }
    if (workletRef.current) {
      workletRef.current.disconnect();
      workletRef.current = null;
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
