/**
 * Channel-aware audio frame v2 (MAUD2) builder — shadow transport (Этап 16).
 *
 * Симметрично backend-парсеру (app/core/context/audio_frame_v2.py). Используется ТОЛЬКО для
 * опционального multichannel shadow-стрима; legacy mono 16k frames идут как раньше.
 *
 * Формат: [5 bytes "MAUD2"][2 bytes uint16 BE header_length][header JSON UTF-8][PCM16 interleaved LE]
 */

import type { AudioCaptureRoute } from './audioCaptureTypes';

// "MAUD2"
const MAGIC = [0x4d, 0x41, 0x55, 0x44, 0x32];
export const AUDIO_FRAME_V2_MAX_HEADER_BYTES = 4096;

export interface AudioFrameV2Header {
  protocol_version: 2;
  sequence: number;
  sample_rate: number;
  channels: number;
  codec: 'pcm16';
  layout: 'interleaved';
  route: AudioCaptureRoute | string;
  capture_pipeline: 'multichannel_shadow_stream';
  frame_duration_ms?: number;
  source_is_isolated: boolean;
  created_at_ms?: number;
}

/** Собрать MAUD2-кадр из header + interleaved PCM16 payload. */
export function buildAudioFrameV2(header: AudioFrameV2Header, payload: Int16Array): ArrayBuffer {
  const headerBytes = new TextEncoder().encode(JSON.stringify(header));
  if (headerBytes.length > AUDIO_FRAME_V2_MAX_HEADER_BYTES) {
    throw new Error('v2 header too large');
  }
  const payloadBytes = new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength);
  const total = MAGIC.length + 2 + headerBytes.length + payloadBytes.length;
  const buf = new ArrayBuffer(total);
  const u8 = new Uint8Array(buf);
  u8.set(MAGIC, 0);
  new DataView(buf).setUint16(MAGIC.length, headerBytes.length, false); // big-endian
  u8.set(headerBytes, MAGIC.length + 2);
  u8.set(payloadBytes, MAGIC.length + 2 + headerBytes.length);
  return buf;
}

/** Проверка магии (для тестов/диагностики). */
export function isAudioFrameV2(buf: ArrayBuffer): boolean {
  if (buf.byteLength < MAGIC.length + 2) return false;
  const u8 = new Uint8Array(buf, 0, MAGIC.length);
  return MAGIC.every((b, i) => u8[i] === b);
}
