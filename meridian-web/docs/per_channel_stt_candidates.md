# Per-channel STT Source Candidates (Stage 17)

Opt-in backend canary, который из Stage 16 MAUD2 multichannel shadow frames делает per-channel STT
source candidates для `SourceAttributionReconciler`. Поверх [channel_aware_capture_v2.md](channel_aware_capture_v2.md).

```
MAUD2 v2 frames → split by channel → VAD/dominance segmentation → per-channel STT (короткие сегменты)
→ SourceAttributionCandidate → SourceAttributionReconciler → source_reconcile shadow/active policy
```

## Главные инварианты

- **Legacy mono 16k STT = production path**, не меняется. Per-channel STT его НЕ заменяет.
- Per-channel STT **не назначает сторону**. `channel_{index}` — техническая зона записи, НЕ сторона
  и НЕ личность. Сторона приходит только позже через `speaker_identity_hints` + stable link,
  которые задаёт оператор в UI «Роли и стороны» (Этап 21) —
  см. [speaker_role_confirmation_ui.md](speaker_role_confirmation_ui.md).
- По умолчанию всё безопасно: `enabled=false`, `shadow_mode=true`.
- STT-адаптер по умолчанию **no-op** (нет безопасного локального STT). Прод не делает внешних
  STT-вызовов, пока не подключён реальный адаптер; кандидаты не появятся (last_error_kind=stt_adapter_unavailable).

## Prerequisites

1. Stage 16 multichannel shadow frames принимаются (`audio_multichannel_frame_count > 0`).
2. `audio_multichannel_max_channels_seen >= 2`.
3. Per-channel STT canary включён через hidden ai-settings (см. ниже) + подключён реальный STT-адаптер.

## Модель управления (hidden per-meeting overrides)

- `audio_per_channel_stt_enabled` — мастер-тумблер (global default false).
- `audio_per_channel_stt_shadow_mode` — true: STT сегментирует/транскрибирует/пишет trace, но
  **не эмитит** candidates в reconciler; false: эмитит candidates в `SourceAttributionReconciler`.
- `source_reconcile_shadow_mode` — отдельный слой: даже когда per-channel STT эмитит candidates,
  сам reconcile может оставаться shadow=true (would_attach считается, но attach не происходит) — безопасно.
- Пороги: `min_rms`, `min_dominance`, `min_segment_ms`, `end_silence_ms`, `max_segment_ms`,
  `min_text_chars`, `max_segments_per_minute`, `max_concurrent_transcribes`, `max_channels`, trace.

## Рекомендуемый rollout

1. Включить **только** Stage 16 multichannel shadow; убедиться `max_channels_seen >= 2`.
2. `audio_per_channel_stt_enabled=true` + `audio_per_channel_stt_shadow_mode=true` — проверить
   стоимость/задержку VAD/STT по `PER_CHANNEL_STT_TRACE`.
3. Если trace показывает `candidate_shadow_suppressed_count>0` и `candidate_emit_count=0` — поставить
   `audio_per_channel_stt_shadow_mode=false`, оставив `source_reconcile_shadow_mode=true`.
4. Анализировать `SOURCE_RECONCILE_TRACE` (would_attach, match reasons).
5. Только позже — `source_reconcile_shadow_mode=false` на ОДНОЙ встрече (Stage 11–14 canary).

### Пример PATCH

`PATCH /api/meetings/{id}/ai-settings`:
```json
{
  "audio_per_channel_stt_enabled": true,
  "audio_per_channel_stt_shadow_mode": true,
  "audio_per_channel_stt_max_channels": 2,
  "audio_per_channel_stt_min_dominance": 0.65
}
```
В логах: `[AudioPerChannelSttCanary] meeting_id=… user_id=… changed_keys=[…]` (только имена ключей).

### Rollback

Те же ключи `null` → возврат к global defaults (`enabled=false`, `shadow=true`).

## Как создаются source candidates

Per-channel сегмент (после VAD/dominance) → STT → `PerChannelSttCandidate` →
`segment_to_source_candidate_payload`:
```
{ text, start_ms, end_ms, audio_source_id="channel_{index}", channel_label="channel_{index}",
  source_is_isolated, source_kind="multi_channel", attribution_source="multi_source_segment",
  attribution_confidence (cap 0.85), candidate_pipeline="per_channel_stt" }
```
→ `observe_source_attribution_candidate(payload)` (тот же контракт, что multi_channel_live). Reconciler
сам решает match/shadow/attach по своей policy. `side` в payload НЕТ.

## Safety

- нет side inference; `channel_{index}` — техническая зона записи;
- raw audio не пишется на диск и не логируется; `pcm16_mono` не попадает в repr/trace;
- raw transcript не логируется (только `text_hash` внутри, в trace вообще нет текста);
- per-channel STT не вызывает `set_speaker_audio_metadata`, не создаёт speaker observations, не трогает
  `speaker_identity_hints`;
- ошибка/таймаут per-channel STT не влияет на legacy mono STT и не закрывает websocket;
  транскрипция идёт в bounded async-задачах (semaphore `max_concurrent_transcribes`).

## PER_CHANNEL_STT_TRACE / анализатор

Маркер: `PER_CHANNEL_STT_TRACE {json}` — только агрегаты (frame/segment/transcribe/candidate счётчики,
max_channels_seen, average_dominance, average_transcribe_latency_ms, last_error_kind). Без raw text/audio/
source ids/labels.

```bash
python -m app.core.context.per_channel_stt_trace_analysis /path/app.log
```
Сводка: candidate_emit/suppressed, transcribe success/error, segment drop rates, max_channels_seen_p50,
average_dominance_p50, latency p95, by_last_error_kind + notes.

`SIGNAL_ENGINE_TRACE` также несёт безопасные `audio_per_channel_stt_*` агрегаты; анализатор
`signal_trace_analysis` даёт сводку `audio_per_channel_stt` и заметки про готовность к active reconcile.

## Troubleshooting

- **нет frames** → Stage 16 shadow не включён / браузер не отдаёт каналы (см. channel_aware_capture_v2).
- **frames есть, но 0 сегментов** → VAD/dominance пороги слишком строгие (понизить `min_rms`/`min_dominance`).
- **сегменты дропаются по dominance** → каналы не изолированы (микрофоны ловят друг друга).
- **STT adapter unavailable** → подключён no-op адаптер; нужен реальный STT-адаптер.
- **candidates есть, но reconcile не матчит** → проверить timestamps/text similarity (Stage 11–14 trace).

## Stage 18: Provider adapter (реальный STT)

Подключает реальный STT-адаптер для per-channel pipeline:
`MAUD2 channel segment → in-memory mono WAV → bounded provider adapter → text → candidate`.

### Provider modes (`audio_per_channel_stt_provider`)

| provider | поведение |
|---|---|
| `noop` (default) | без внешних вызовов; `adapter_unavailable`, кандидатов нет |
| `elevenlabs_batch` / `existing_batch` | переиспользует `BatchTranscriptionService` (Scribe v2), `diarize=false`, in-memory WAV, без temp-файлов |
| неизвестный | безопасный `unknown_provider` (no-op behavior) |

API-ключ берётся из `session._elevenlabs_key` (как в batch-финализации), **НЕ** из meeting snapshot.
Если ключа нет → `api_key_missing` (без падения).

### Bounded: timeout / cache / budget

- **timeout** (`timeout_seconds`, 1..120): provider-вызов вынесен в поток (не блокирует WS-loop),
  ограничен `asyncio.wait_for`; превышение → `timeout`.
- **cache** (`cache_enabled`, `cache_max_entries`): in-memory LRU по hash(audio+provider+model+lang);
  cache hit НЕ тратит budget и не делает повторный вызов; только в памяти, без диска.
- **budget** (`max_provider_calls_per_meeting`, `max_provider_audio_seconds_per_meeting`): защита
  стоимости; при исчерпании → `budget_exhausted`, provider не вызывается. `0` блокирует вызовы.
- **аудио-лимиты**: `max_audio_seconds` (сегмент длиннее → `audio_too_long`), `max_wav_bytes`
  (WAV больше → `audio_too_large`).

### Как candidate создаётся из текста

provider-результат → `normalize_stt_text` → если длина ≥ `min_text_chars` → candidate с
`attribution_confidence = f(dominance, rms, provider confidence)` (cap 0.85), `source="per_channel_stt"`.
provider raw-ответ/text в trace/логи не попадают.

### Пример shadow PATCH

```json
{
  "audio_per_channel_stt_enabled": true,
  "audio_per_channel_stt_shadow_mode": true,
  "audio_per_channel_stt_provider": "elevenlabs_batch",
  "audio_per_channel_stt_timeout_seconds": 20,
  "audio_per_channel_stt_max_provider_calls_per_meeting": 30
}
```
В логах: `[AudioPerChannelSttProviderCanary] meeting_id=… user_id=… changed_keys=[…]` (без значений).

### Rollback

Все `audio_per_channel_stt_*` ключи `null` → возврат к global defaults (`provider=noop`).

### Operational sequence

1. Stage 16 v2 frames принимаются (`max_channels_seen ≥ 2`).
2. Stage 17/18 per-channel STT включён в shadow + `provider=elevenlabs_batch`.
3. `PER_CHANNEL_STT_TRACE`: `transcribe_success > 0` и `candidate_shadow_suppressed > 0`.
4. `audio_per_channel_stt_shadow_mode=false` при `source_reconcile_shadow_mode=true`.
5. Анализ `SOURCE_RECONCILE_TRACE`.
6. Только позже — `source_reconcile_shadow_mode=false` на одной встрече.

### Safety (Stage 18)

- raw audio/text/provider-ответ не логируются; WAV in-memory, без диска;
- API-ключи не в repr/logs/snapshot (`ElevenLabsBatchPerChannelSttAdapter.__repr__` скрывает ключ);
- provider-вызовы ограничены budget+timeout; ошибка/таймаут не ломают legacy mono STT и не закрывают WS;
- side inference нет; `channel_{index}` — техническая зона.

### Trace (Stage 18)

`PER_CHANNEL_STT_TRACE` доп. поля: `provider`, `transcribe_timeout_count`, `transcribe_empty_text_count`,
`transcribe_provider_error_count`, `transcribe_budget_exhausted_count`, `transcribe_cache_hit_count`,
`transcribe_cache_miss_count`, `transcribe_audio_too_long_count`, `transcribe_audio_too_large_count`,
`adapter_unavailable_count`. Анализатор: `by_provider`, `cache_hit_rate`, `budget_exhausted_count`,
`timeout_count`, `provider_error_count` + notes (noop/api_key_missing/timeout/budget/empty_text).
`SIGNAL_ENGINE_TRACE` несёт безопасный subset (`audio_per_channel_stt_provider`,
`...adapter_unavailable_count`, `...cache_hit_count`, `...budget_exhausted_count`, `...timeout_count`).

## Stage 19: canary operations + monitor

Эксплуатационный контур (emit-shadow / plan / emit-candidates / monitor / emit-rollback) для запуска
per-channel STT canary на одной встрече + усиленный provider timeout — см.
[per_channel_stt_canary_operations.md](per_channel_stt_canary_operations.md).

## Ограничения

- per-channel STT использует AudioContext-rate (16 кГц) каналы; качество транскрипции коротких
  сегментов ограничено;
- `elevenlabs_batch` — платный внешний вызов (bounded budget/timeout); следить за стоимостью;
- Stage 20+ может добавить per-channel turn assembly / diarization-aware candidates.
