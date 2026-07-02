# Channel-aware Capture Protocol v2 Shadow (Stage 16)

Opt-in channel-aware capture как **shadow** слой поверх [audio_device_preflight.md](audio_device_preflight.md)
(Stage 15). Готовит Stage 17/18 (per-channel diagnostics → per-channel STT → source candidates), не
ломая текущий MVP.

## Главный принцип

- **Legacy mono 16k stream = production path** — единственный live STT input, без изменений.
- **Multichannel v2 stream = shadow diagnostics only** — отдельная ветка, опциональная, по умолчанию OFF.
- Если v2 ломается, legacy mono STT продолжает работать (v2 не на критическом пути).

## Что добавляет Stage 16

- **Frontend:** второй AudioWorklet-процессор `mc-shadow-processor` (читает все каналы input,
  interleaved PCM16), MAUD2-builder (`audioFrameV2.ts`), тоггл «Экспериментально: стерео/мультиканал»
  в `AudioPreflightPanel` (только для multi-канальных маршрутов, default OFF), backpressure-дроп v2.
- **Backend:** MAUD2-парсер (`audio_frame_v2.py`), shadow-ingest агрегаты (`multichannel_shadow_state.py`),
  WS-роутинг (`handle_audio_frame` различает MAUD2 vs legacy), safe `audio_multichannel_*` поля в
  `SIGNAL_ENGINE_TRACE` + сводка `audio_multichannel` в анализаторе. Флаги `AI_AUDIO_MULTICHANNEL_SHADOW_*`.

## Формат кадра MAUD2

```
[5 bytes MAGIC "MAUD2"]
[2 bytes uint16 BE header_length]
[header JSON UTF-8]
[payload PCM16 interleaved, little-endian]
```
Header: `protocol_version=2`, `sequence`, `sample_rate`, `channels`, `codec="pcm16"`,
`layout="interleaved"`, `route`, `capture_pipeline="multichannel_shadow_stream"`, `frame_duration_ms`,
`source_is_isolated=false`, `created_at_ms`.

Legacy mono frames (без заголовка) и secondary-shadow frames (начинаются с 2-байтовой длины, не с
MAGIC) не коллизируют — backend различает по первым 5 байтам.

## Как включить из UI

1. В `AudioPreflightPanel` выбрать route `usb_recorder` / `usb_room_mic` / `external_audio_interface`
   (или устройство, которое sound-check видит как 2+ канала).
2. Появится чекбокс «Экспериментально: передавать стерео/мультиканал в shadow-режиме» (default OFF).
3. Включить → выбор персистится (`meridian_audio_multichannel_shadow_enabled_v1`).
4. Начать встречу. Frontend шлёт legacy mono (STT) + параллельно MAUD2 v2 frames (shadow).

> Тоггл показывается только для multi-канальных маршрутов; включается, только если трек реально
> отдаёт ≥2 каналов. Иначе v2 frames не отправляются, метадата остаётся mono/stereo_requested_mono_stream.

## Что backend делает с v2 frames

- различает по MAGIC, направляет в `session.ingest_audio_frame_v2_shadow` (НЕ в legacy STT-очередь);
- валидирует (magic/header cap/JSON/version/channels 1..8/sample_rate 8k..96k/codec/layout/выравнивание);
- считает безопасные агрегаты: счётчики кадров/ошибок/gap'ов, max каналов, rms/peak/clipping по каналам;
- пишет safe-поля в trace.

## Что backend НЕ делает

- НЕ пишет raw audio на диск и не логирует payload;
- НЕ кормит STT (per-channel STT — Stage 17);
- НЕ создаёт source attribution / source candidates;
- НЕ вызывает `set_speaker_audio_metadata`, не создаёт speaker observations;
- НЕ выводит сторону переговоров.

## Почему это не side inference

`route`/`channel index`/`source_kind` — техническая зона записи, НЕ сторона и НЕ личность. left/right/
primary/secondary/Zoom H2n/speakerphone стороной не считаются. Сторона приходит только через
`speaker_identity_hints` + stable attribution link. v2 frames не участвуют ни в каком решении/policy.

## Защищённые raw данные

- raw audio (payload) не логируется и не хранится — только агрегаты;
- нет raw device labels/ids (заголовок их не несёт), нет transcript text, нет speaker labels;
- `ParsedAudioFrameV2.__repr__` скрывает payload; ingest хранит только числовые агрегаты.

## Рекомендуемый тест

1. route `usb_recorder`, sound-check показывает 2 канала;
2. включить экспериментальный shadow;
3. начать встречу;
4. в `SIGNAL_ENGINE_TRACE` смотреть `audio_multichannel_max_channels_seen >= 2`,
   `audio_multichannel_frame_count > 0`, `audio_multichannel_parse_error_count == 0`.

## Trace / анализатор

Safe-поля: `audio_multichannel_shadow_enabled`, `audio_multichannel_frame_count`,
`audio_multichannel_parse_error_count`, `audio_multichannel_sequence_gap_count`,
`audio_multichannel_max_channels_seen`, `audio_multichannel_last_channels`,
`audio_multichannel_last_sample_rate`, `audio_multichannel_clipping_event_count`.

Анализатор (`signal_trace_analysis`) → сводка `audio_multichannel` (p50 счётчиков) + заметки:
- «USB route выбран, но v2 multichannel shadow frames не приходят — проверить frontend opt-in / каналы»;
- «multichannel shadow видит 2+ канала — кандидат на Stage 17 per-channel STT»;
- «v2 frame parse errors — проверить совместимость протокола»; «v2 frame drops/backpressure».

## Ограничения

- v2 sample_rate = AudioContext rate (16 кГц) — каналы есть, но ресемплированы; полноценный
  per-channel захват — отдельный шаг.

## Stage 17: per-channel STT source candidates

Принятые v2-каналы теперь могут (opt-in canary) превращаться в per-channel STT source candidates для
`SourceAttributionReconciler` — см. [per_channel_stt_candidates.md](per_channel_stt_candidates.md).
По умолчанию выключено/shadow; legacy mono STT остаётся production path; сторона не выводится.
