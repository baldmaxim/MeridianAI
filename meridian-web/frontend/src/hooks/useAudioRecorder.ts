import { useRef, useCallback, useState } from 'react';

/**
 * Browser audio capture hook.
 * Captures microphone audio, downsamples to 16kHz 16-bit mono PCM,
 * and sends binary chunks via provided sendBinary callback.
 */
export function useAudioRecorder(sendBinary: (data: ArrayBuffer) => void) {
  const [isRecording, setIsRecording] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);

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

      const context = new AudioContext({ sampleRate: 16000 });
      contextRef.current = context;

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
      // Connect to a silent destination to keep the AudioWorklet processing
      // without playing mic audio through speakers (avoids feedback)
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      worklet.connect(silentGain);
      silentGain.connect(context.destination);

      setIsRecording(true);
    } catch (err) {
      console.error('Failed to start audio recording:', err);
      throw err;
    }
  }, [sendBinary]);

  const stop = useCallback(() => {
    if (workletRef.current) {
      workletRef.current.disconnect();
      workletRef.current = null;
    }
    if (contextRef.current) {
      contextRef.current.close();
      contextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setIsRecording(false);
  }, []);

  return { isRecording, start, stop };
}
